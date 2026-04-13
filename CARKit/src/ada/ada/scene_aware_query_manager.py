#!/usr/bin/env python3

import re

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


def normalize_label(label: str) -> str:
    cleaned = label.strip().lower().replace('_', ' ')
    cleaned = re.sub(r'^(a|an|the)\s+', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned


def parse_label_list(value: str):
    return [normalize_label(item) for item in value.split(',') if normalize_label(item)]


def parse_detection_entries(message: str):
    detections = []
    for detection in message.split(';'):
        detection = detection.strip()
        if not detection or detection == 'no detections':
            continue

        box_start = detection.find('[')
        conf_start = detection.rfind('(')
        conf_end = detection.rfind(')')
        if min(box_start, conf_start, conf_end) == -1:
            continue

        label = normalize_label(detection[:box_start])
        try:
            confidence = float(detection[conf_start + 1:conf_end])
        except ValueError:
            continue

        detections.append({
            'label': label,
            'confidence': confidence,
        })

    return detections


class SceneAwareQueryManager(Node):
    def __init__(self):
        super().__init__('scene_aware_query_manager')

        self.declare_parameter('query_topic', '/input_query')
        self.declare_parameter('detections_topic', '/yolo/detections')
        self.declare_parameter('scene_mode_topic', '/scene_mode')
        self.declare_parameter('scene_override', 'auto')
        self.declare_parameter('default_scene_mode', 'indoor')
        self.declare_parameter('startup_delay_sec', 3.0)
        self.declare_parameter('probe_duration_sec', 4.0)
        self.declare_parameter('probe_publish_period_sec', 1.0)
        self.declare_parameter('final_query_publish_period_sec', 5.0)
        self.declare_parameter('min_score_margin', 0.25)
        self.declare_parameter(
            'scene_neutral_labels',
            'person, people, pedestrian, pedestrians, human, humans'
        )
        self.declare_parameter('indoor_probe_query', 'person, people, chair, desk, monitor, bottle, laptop')
        self.declare_parameter(
            'outdoor_probe_query',
            'pedestrian, bicyclist, bicycle, motorcycle, car, truck, bus, stop sign, traffic light, cone'
        )
        self.declare_parameter(
            'indoor_query',
            'person, people, chair, desk, monitor, bottle, laptop, keyboard, cup, box'
        )
        self.declare_parameter(
            'outdoor_query',
            'pedestrian, bicyclist, bicycle, motorcycle, car, truck, bus, stop sign, traffic light, cone, box'
        )

        self.query_topic = self.get_parameter('query_topic').value
        self.detections_topic = self.get_parameter('detections_topic').value
        self.scene_mode_topic = self.get_parameter('scene_mode_topic').value
        self.scene_override = normalize_label(self.get_parameter('scene_override').value)
        self.default_scene_mode = normalize_label(self.get_parameter('default_scene_mode').value)
        self.startup_delay_sec = float(self.get_parameter('startup_delay_sec').value)
        self.probe_duration_sec = float(self.get_parameter('probe_duration_sec').value)
        self.probe_publish_period_sec = float(self.get_parameter('probe_publish_period_sec').value)
        self.final_query_publish_period_sec = float(self.get_parameter('final_query_publish_period_sec').value)
        self.min_score_margin = float(self.get_parameter('min_score_margin').value)
        self.queries = {
            'indoor': self.get_parameter('indoor_query').value,
            'outdoor': self.get_parameter('outdoor_query').value,
        }
        self.probe_queries = {
            'indoor': self.get_parameter('indoor_probe_query').value,
            'outdoor': self.get_parameter('outdoor_probe_query').value,
        }
        self.scene_neutral_labels = set(
            parse_label_list(self.get_parameter('scene_neutral_labels').value)
        )
        self.probe_labels = {
            mode: set(parse_label_list(query))
            for mode, query in self.probe_queries.items()
        }
        self.shared_probe_labels = self.probe_labels['indoor'] & self.probe_labels['outdoor']
        self.ignored_probe_labels = self.shared_probe_labels | self.scene_neutral_labels
        if self.ignored_probe_labels:
            self.probe_labels = {
                mode: labels - self.ignored_probe_labels
                for mode, labels in self.probe_labels.items()
            }

        self.query_publisher = self.create_publisher(String, self.query_topic, 10)
        self.scene_mode_publisher = self.create_publisher(String, self.scene_mode_topic, 10)
        self.create_subscription(String, self.detections_topic, self.detections_callback, 10)

        self.phase = 'startup'
        self.probe_scores = {'indoor': 0.0, 'outdoor': 0.0}
        self.probe_counts = {'indoor': 0, 'outdoor': 0}
        self.phase_started_at = self.get_clock().now()
        self.last_query_publish_at = None
        self.locked_scene_mode = None
        self.last_scene_mode_logged = None

        self.timer = self.create_timer(0.2, self.timer_callback)

        if self.scene_override in ('indoor', 'outdoor'):
            self.lock_scene_mode(self.scene_override)
            self.get_logger().info(
                f'Scene override active: {self.locked_scene_mode}. '
                f'Publishing query "{self.queries[self.locked_scene_mode]}".'
            )
        else:
            self.get_logger().info(
                'Scene-aware query manager started in auto mode. '
                f'Indoor probe="{self.probe_queries["indoor"]}", '
                f'outdoor probe="{self.probe_queries["outdoor"]}".'
            )
            if self.ignored_probe_labels:
                self.get_logger().info(
                    'Ignoring scene-neutral/shared probe labels for scene classification: '
                    f'{sorted(self.ignored_probe_labels)}'
                )

    def detections_callback(self, msg: String):
        if self.phase not in ('probe_indoor', 'probe_outdoor'):
            return

        mode = 'indoor' if self.phase == 'probe_indoor' else 'outdoor'
        valid_labels = self.probe_labels[mode]

        for detection in parse_detection_entries(msg.data):
            if detection['label'] in valid_labels:
                self.probe_scores[mode] += detection['confidence']
                self.probe_counts[mode] += 1

    def timer_callback(self):
        now = self.get_clock().now()
        elapsed = (now - self.phase_started_at).nanoseconds / 1e9

        if self.locked_scene_mode:
            if self.should_publish_query(now, self.final_query_publish_period_sec):
                self.publish_query(self.queries[self.locked_scene_mode])
                self.publish_scene_mode(self.locked_scene_mode)
            return

        if self.phase == 'startup':
            if elapsed >= self.startup_delay_sec:
                self.start_probe('indoor')
            return

        if self.phase in ('probe_indoor', 'probe_outdoor'):
            if self.should_publish_query(now, self.probe_publish_period_sec):
                mode = 'indoor' if self.phase == 'probe_indoor' else 'outdoor'
                self.publish_query(self.probe_queries[mode])

            if elapsed >= self.probe_duration_sec:
                if self.phase == 'probe_indoor':
                    self.start_probe('outdoor')
                else:
                    self.select_scene_mode()

    def should_publish_query(self, now, period_sec: float) -> bool:
        if self.last_query_publish_at is None:
            return True
        return (now - self.last_query_publish_at).nanoseconds / 1e9 >= period_sec

    def start_probe(self, mode: str):
        self.phase = f'probe_{mode}'
        self.phase_started_at = self.get_clock().now()
        self.last_query_publish_at = None
        self.publish_query(self.probe_queries[mode])
        self.get_logger().info(
            f'Starting {mode} scene probe with query "{self.probe_queries[mode]}" '
            f'for {self.probe_duration_sec:.1f}s.'
        )

    def select_scene_mode(self):
        indoor_score = self.probe_scores['indoor']
        outdoor_score = self.probe_scores['outdoor']
        score_margin = indoor_score - outdoor_score

        if abs(score_margin) < self.min_score_margin:
            selected_mode = self.default_scene_mode
            reason = (
                f'scores too close (indoor={indoor_score:.2f}, outdoor={outdoor_score:.2f}); '
                f'falling back to default "{selected_mode}"'
            )
        else:
            selected_mode = 'indoor' if score_margin > 0.0 else 'outdoor'
            reason = (
                f'indoor={indoor_score:.2f} ({self.probe_counts["indoor"]} hits), '
                f'outdoor={outdoor_score:.2f} ({self.probe_counts["outdoor"]} hits)'
            )

        self.lock_scene_mode(selected_mode)
        self.get_logger().info(f'Locked scene mode to {selected_mode}: {reason}.')

    def lock_scene_mode(self, mode: str):
        self.locked_scene_mode = mode
        self.phase = 'locked'
        self.phase_started_at = self.get_clock().now()
        self.last_query_publish_at = None
        self.publish_scene_mode(mode)
        self.publish_query(self.queries[mode])

    def publish_scene_mode(self, mode: str):
        self.scene_mode_publisher.publish(String(data=mode))
        if self.last_scene_mode_logged != mode:
            self.last_scene_mode_logged = mode

    def publish_query(self, query: str):
        self.query_publisher.publish(String(data=query))
        self.last_query_publish_at = self.get_clock().now()


def main(args=None):
    rclpy.init(args=args)
    node = SceneAwareQueryManager()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
