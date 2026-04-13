#!/usr/bin/env python3

import math
import re

import numpy as np
import rclpy
from ackermann_msgs.msg import AckermannDriveStamped
from cv_bridge import CvBridge
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Header, String


def normalize_label(label: str) -> str:
    cleaned = label.strip().lower().replace('_', ' ')
    cleaned = re.sub(r'^(a|an|the)\s+', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned


def parse_label_set(value: str):
    return {normalize_label(item) for item in value.split(',') if normalize_label(item)}


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


class ReactiveBehaviorController(Node):
    def __init__(self):
        super().__init__('reactive_behavior_controller')

        self.declare_parameter('motion_enabled', False)
        self.declare_parameter('detections_topic', '/yolo/detections')
        self.declare_parameter('depth_topic', '/camera/camera/aligned_depth_to_color/image_raw')
        self.declare_parameter('scene_mode_topic', '/scene_mode')
        self.declare_parameter('purepursuit_cmd_topic', '/purepursuit_cmd')
        self.declare_parameter('emergency_cmd_topic', '/emergency_cmd')
        self.declare_parameter('behavior_state_topic', '/reactive_behavior_state')
        self.declare_parameter('target_pose_topic', '/reactive_target_pose')
        self.declare_parameter('horizontal_fov', 69.4)
        self.declare_parameter('control_period_sec', 0.1)
        self.declare_parameter('detection_timeout_sec', 0.5)
        self.declare_parameter('cruise_speed', 0.35)
        self.declare_parameter('slow_speed', 0.18)
        self.declare_parameter('bypass_speed', 0.12)
        self.declare_parameter('stop_distance_m', 1.2)
        self.declare_parameter('slow_distance_m', 2.0)
        self.declare_parameter('bypass_distance_m', 1.5)
        self.declare_parameter('steering_gain', 0.9)
        self.declare_parameter('max_steering_angle', 0.34)
        self.declare_parameter('center_deadband_m', 0.08)
        self.declare_parameter('default_bypass_direction', 'left')
        self.declare_parameter('stop_labels', 'person, stop sign')
        self.declare_parameter('slow_labels', 'cone, chair, box')
        self.declare_parameter('bypass_labels', 'cone, chair, box')

        self.motion_enabled = bool(self.get_parameter('motion_enabled').value)
        self.detections_topic = self.get_parameter('detections_topic').value
        self.depth_topic = self.get_parameter('depth_topic').value
        self.scene_mode_topic = self.get_parameter('scene_mode_topic').value
        self.horizontal_fov = float(self.get_parameter('horizontal_fov').value)
        self.horizontal_fov_rad = math.radians(self.horizontal_fov)
        self.control_period_sec = float(self.get_parameter('control_period_sec').value)
        self.detection_timeout_sec = float(self.get_parameter('detection_timeout_sec').value)
        self.cruise_speed = float(self.get_parameter('cruise_speed').value)
        self.slow_speed = float(self.get_parameter('slow_speed').value)
        self.bypass_speed = float(self.get_parameter('bypass_speed').value)
        self.stop_distance_m = float(self.get_parameter('stop_distance_m').value)
        self.slow_distance_m = float(self.get_parameter('slow_distance_m').value)
        self.bypass_distance_m = float(self.get_parameter('bypass_distance_m').value)
        self.steering_gain = float(self.get_parameter('steering_gain').value)
        self.max_steering_angle = float(self.get_parameter('max_steering_angle').value)
        self.center_deadband_m = float(self.get_parameter('center_deadband_m').value)
        self.default_bypass_direction = normalize_label(self.get_parameter('default_bypass_direction').value)
        self.stop_labels = parse_label_set(self.get_parameter('stop_labels').value)
        self.slow_labels = parse_label_set(self.get_parameter('slow_labels').value)
        self.bypass_labels = parse_label_set(self.get_parameter('bypass_labels').value)

        self.bridge = CvBridge()
        self.depth_image = None
        self.image_width = None
        self.latest_candidates = []
        self.last_detection_at = None
        self.scene_mode = 'unknown'
        self.last_state = None

        self.create_subscription(String, self.detections_topic, self.detections_callback, 10)
        self.create_subscription(Image, self.depth_topic, self.depth_callback, 10)
        self.create_subscription(String, self.scene_mode_topic, self.scene_mode_callback, 10)

        self.purepursuit_publisher = self.create_publisher(
            AckermannDriveStamped, self.get_parameter('purepursuit_cmd_topic').value, 10
        )
        self.emergency_publisher = self.create_publisher(
            AckermannDriveStamped, self.get_parameter('emergency_cmd_topic').value, 10
        )
        self.state_publisher = self.create_publisher(
            String, self.get_parameter('behavior_state_topic').value, 10
        )
        self.target_pose_publisher = self.create_publisher(
            PoseStamped, self.get_parameter('target_pose_topic').value, 10
        )

        self.timer = self.create_timer(self.control_period_sec, self.control_loop)

        self.get_logger().info(
            'Reactive behavior controller started. '
            f'motion_enabled={self.motion_enabled}, stop_labels={sorted(self.stop_labels)}, '
            f'slow_labels={sorted(self.slow_labels)}, bypass_labels={sorted(self.bypass_labels)}.'
        )

    def scene_mode_callback(self, msg: String):
        self.scene_mode = normalize_label(msg.data)

    def depth_callback(self, msg: Image):
        try:
            self.depth_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')
            self.image_width = msg.width
        except Exception as exc:
            self.get_logger().error(f'Failed to convert depth image: {exc}')

    def detections_callback(self, msg: String):
        self.last_detection_at = self.get_clock().now()
        if self.depth_image is None or self.image_width is None:
            self.latest_candidates = []
            return

        candidates = []
        for detection in msg.data.split(';'):
            parsed = self.parse_detection(detection)
            if parsed is None:
                continue

            center_x = (parsed['bbox'][0] + parsed['bbox'][2]) / 2.0
            center_y = (parsed['bbox'][1] + parsed['bbox'][3]) / 2.0
            depth = self.lookup_depth(center_x, center_y)
            if depth is None:
                continue

            x_pos, y_pos, angle_rad = self.calculate_position(center_x, depth)
            parsed.update({
                'center_x': center_x,
                'center_y': center_y,
                'depth': depth,
                'x': x_pos,
                'y': y_pos,
                'angle_rad': angle_rad,
            })
            candidates.append(parsed)

        self.latest_candidates = candidates

    def parse_detection(self, detection: str):
        detection = detection.strip()
        if not detection or detection == 'no detections':
            return None

        box_start = detection.find('[')
        box_end = detection.find(']')
        conf_start = detection.rfind('(')
        conf_end = detection.rfind(')')
        if min(box_start, box_end, conf_start, conf_end) == -1:
            return None

        label = normalize_label(detection[:box_start])
        try:
            bbox = [float(value.strip()) for value in detection[box_start + 1:box_end].split(',')]
            confidence = float(detection[conf_start + 1:conf_end])
        except ValueError:
            return None

        if len(bbox) != 4:
            return None

        return {
            'label': label,
            'bbox': bbox,
            'confidence': confidence,
        }

    def lookup_depth(self, center_x: float, center_y: float):
        if self.depth_image is None:
            return None

        x = int(round(center_x))
        y = int(round(center_y))
        if y < 0 or x < 0 or y >= self.depth_image.shape[0] or x >= self.depth_image.shape[1]:
            return None

        y_min = max(0, y - 2)
        y_max = min(self.depth_image.shape[0], y + 3)
        x_min = max(0, x - 2)
        x_max = min(self.depth_image.shape[1], x + 3)
        patch = self.depth_image[y_min:y_max, x_min:x_max]
        valid = patch[patch > 0]
        if valid.size == 0:
            return None

        return float(np.median(valid)) / 1000.0

    def calculate_position(self, center_x: float, depth: float):
        normalized_pos = -((center_x / self.image_width) - 0.5)
        angle_rad = (normalized_pos / 0.5) * (self.horizontal_fov_rad / 2.0)
        x_pos = depth
        y_pos = x_pos * math.tan(angle_rad)
        return x_pos, y_pos, angle_rad

    def control_loop(self):
        if self.last_detection_at is None:
            self.publish_drive_command(0.0, 0.0, 'waiting_for_detections')
            return

        age_sec = (self.get_clock().now() - self.last_detection_at).nanoseconds / 1e9
        if age_sec > self.detection_timeout_sec:
            self.publish_drive_command(0.0, 0.0, 'detections_timeout')
            return

        stop_candidate = self.select_candidate(self.stop_labels, self.stop_distance_m)
        if stop_candidate is not None:
            self.publish_emergency_stop(stop_candidate)
            return

        bypass_candidate = self.select_candidate(self.bypass_labels, self.bypass_distance_m)
        if bypass_candidate is not None:
            steering = self.compute_avoidance_steering(bypass_candidate['y'])
            speed = self.bypass_speed if self.motion_enabled else 0.0
            self.publish_target_pose(bypass_candidate)
            self.publish_drive_command(
                speed,
                steering,
                f'bypass:{bypass_candidate["label"]}:{bypass_candidate["depth"]:.2f}m:{self.scene_mode}',
            )
            return

        slow_candidate = self.select_candidate(self.slow_labels, self.slow_distance_m)
        if slow_candidate is not None:
            steering = self.compute_avoidance_steering(slow_candidate['y']) * 0.5
            speed = self.slow_speed if self.motion_enabled else 0.0
            self.publish_target_pose(slow_candidate)
            self.publish_drive_command(
                speed,
                steering,
                f'slow:{slow_candidate["label"]}:{slow_candidate["depth"]:.2f}m:{self.scene_mode}',
            )
            return

        cruise_speed = self.cruise_speed if self.motion_enabled else 0.0
        self.publish_drive_command(cruise_speed, 0.0, f'cruise:{self.scene_mode}')

    def select_candidate(self, valid_labels, max_distance_m: float):
        candidates = [
            candidate for candidate in self.latest_candidates
            if candidate['label'] in valid_labels and candidate['depth'] <= max_distance_m
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda item: (item['depth'], -item['confidence']))

    def compute_avoidance_steering(self, lateral_offset_m: float) -> float:
        if abs(lateral_offset_m) < self.center_deadband_m:
            direction = 1.0 if self.default_bypass_direction == 'left' else -1.0
            return direction * self.max_steering_angle

        steering = -self.steering_gain * lateral_offset_m
        return clamp(steering, -self.max_steering_angle, self.max_steering_angle)

    def publish_emergency_stop(self, candidate):
        emergency_cmd = AckermannDriveStamped()
        emergency_cmd.header = Header()
        emergency_cmd.header.stamp = self.get_clock().now().to_msg()
        emergency_cmd.drive.speed = 0.0
        emergency_cmd.drive.steering_angle = 0.0
        self.emergency_publisher.publish(emergency_cmd)
        self.publish_target_pose(candidate)
        self.publish_state(
            f'stop:{candidate["label"]}:{candidate["depth"]:.2f}m:{self.scene_mode}'
        )

    def publish_drive_command(self, speed: float, steering_angle: float, state: str):
        drive_cmd = AckermannDriveStamped()
        drive_cmd.header = Header()
        drive_cmd.header.stamp = self.get_clock().now().to_msg()
        drive_cmd.drive.speed = float(speed)
        drive_cmd.drive.steering_angle = float(steering_angle)
        self.purepursuit_publisher.publish(drive_cmd)
        self.publish_state(state)

    def publish_state(self, state: str):
        self.state_publisher.publish(String(data=state))
        if state != self.last_state:
            self.get_logger().info(f'Reactive state -> {state}')
            self.last_state = state

    def publish_target_pose(self, candidate):
        pose = PoseStamped()
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.header.frame_id = 'camera_link'
        pose.pose.position.x = float(candidate['x'])
        pose.pose.position.y = float(candidate['y'])
        pose.pose.position.z = 0.0
        pose.pose.orientation.z = math.sin(candidate['angle_rad'] / 2.0)
        pose.pose.orientation.w = math.cos(candidate['angle_rad'] / 2.0)
        self.target_pose_publisher.publish(pose)


def main(args=None):
    rclpy.init(args=args)
    node = ReactiveBehaviorController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
