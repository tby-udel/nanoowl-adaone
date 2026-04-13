#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import Image
from geometry_msgs.msg import PoseStamped
from cv_bridge import CvBridge
import numpy as np
import re
import math
import tf2_ros
from tf2_geometry_msgs import do_transform_pose

class ObjectPositionNode(Node):
    def __init__(self):
        super().__init__('object_position_node')
        
        # Declare parameters
        self.declare_parameter('target_object_type', 'book')
        self.declare_parameter('horizontal_fov', 69.4)  # degrees
        
        # Get parameter values
        self.target_object_type = self.get_parameter('target_object_type').value
        self.horizontal_fov = self.get_parameter('horizontal_fov').value
        
        # Convert FOV to radians for calculations
        self.horizontal_fov_rad = math.radians(self.horizontal_fov)
        
        # Add parameter change callback
        self.add_on_set_parameters_callback(self.parameter_callback)
        
        # Publisher for object position
        self.position_pub = self.create_publisher(PoseStamped, '/object_position', 10)
        
        # Subscribe to YOLO detections
        self.yolo_sub = self.create_subscription(
            String,
            '/yolo/detections',
            self.yolo_callback,
            10
        )
        
        # Subscribe to depth image
        self.depth_sub = self.create_subscription(
            Image,
            '/camera/camera/aligned_depth_to_color/image_raw',
            self.depth_callback,
            10
        )
        
        self.cv_bridge = CvBridge()
        self.image_width = None
        self.image_height = None
        self.depth_image = None
        self.resolution_printed = False
        
        self.get_logger().info(
            f'Object Position node started. Tracking {self.target_object_type} '
            f'with {self.horizontal_fov}° horizontal FOV'
        )
    
    def parameter_callback(self, params):
        """Handle parameter updates"""
        for param in params:
            if param.name == 'target_object_type':
                self.target_object_type = param.value
                self.get_logger().info(f'Updated target_object_type to {self.target_object_type}')
            elif param.name == 'horizontal_fov':
                self.horizontal_fov = param.value
                self.horizontal_fov_rad = math.radians(self.horizontal_fov)
                self.get_logger().info(f'Updated horizontal_fov to {self.horizontal_fov}°')
        return True
    
    def calculate_position(self, center_x, depth):
        """Calculate position based on center x-coordinate and depth"""
        if self.image_width is None:
            return None
            
        # Convert pixel position to normalized position (-0.5 to 0.5)
        # Note: right is negative, left is positive
        normalized_pos = -((center_x / self.image_width) - 0.5)  # Negated to match convention
        
        # Calculate angle in radians (positive is left, negative is right)
        angle_rad = (normalized_pos / 0.5) * (self.horizontal_fov_rad / 2)
        
        # Calculate x and y coordinates (in camera frame)
        # x is forward distance (depth)
        # y is lateral distance (using tangent)
        x = depth  # forward distance is just the depth
        y = x * math.tan(angle_rad)  # lateral distance using tangent
        
        return x, y, angle_rad
    
    def create_pose_msg(self, x, y, angle_rad):
        """Create PoseStamped message from position and angle"""
        pose_msg = PoseStamped()
        pose_msg.header.stamp = self.get_clock().now().to_msg()
        pose_msg.header.frame_id = "camera_link"
        
        # Set position
        pose_msg.pose.position.x = float(x)
        pose_msg.pose.position.y = float(y)
        pose_msg.pose.position.z = 0.0  # Assuming object is at camera height
        
        # Set orientation (yaw only, from angle)
        # Convert angle to quaternion (rotate around z-axis)
        pose_msg.pose.orientation.x = 0.0
        pose_msg.pose.orientation.y = 0.0
        pose_msg.pose.orientation.z = math.sin(angle_rad / 2)
        pose_msg.pose.orientation.w = math.cos(angle_rad / 2)
        
        return pose_msg
    
    def yolo_callback(self, msg):
        """Process YOLO detections to find specified object"""
        if self.depth_image is None:
            return

        target_detections = []
        for detection in msg.data.split(';'):
            detection = detection.strip()
            if not detection or detection == 'no detections':
                continue

            box_start = detection.find('[')
            box_end = detection.find(']')
            conf_start = detection.rfind('(')
            conf_end = detection.rfind(')')

            if min(box_start, box_end, conf_start, conf_end) == -1:
                continue

            object_type = detection[:box_start].strip()
            bbox_str = detection[box_start + 1:box_end].strip()

            try:
                confidence = float(detection[conf_start + 1:conf_end])
            except ValueError:
                continue

            if object_type == self.target_object_type:
                target_detections.append((bbox_str, confidence))
        
        if target_detections:
            # Get the detection with highest confidence
            best_detection = max(target_detections, key=lambda x: x[1])
            bbox_str, confidence = best_detection
            
            if confidence >= 0.2:  # Only process if confidence is at least 20%
                # Convert bbox string to list of floats
                bbox = [float(x) for x in bbox_str.split(',')]
                
                # Calculate center coordinates
                center_x = (bbox[0] + bbox[2]) / 2
                center_y = (bbox[1] + bbox[3]) / 2
                
                # Get depth at center point
                center_x_int = int(center_x)
                center_y_int = int(center_y)
                if (0 <= center_y_int < self.depth_image.shape[0] and 
                    0 <= center_x_int < self.depth_image.shape[1]):
                    depth = self.depth_image[center_y_int, center_x_int] / 1000.0  # mm to m

                    if depth > 0:  # Only process valid depth values
                        # Calculate position and angle
                        x, y, angle = self.calculate_position(center_x, depth)
                        
                        # Create and publish pose message
                        pose_msg = self.create_pose_msg(x, y, angle)
                        self.position_pub.publish(pose_msg)
                        
                        self.get_logger().debug(
                            f'Found {self.target_object_type} at '
                            f'x={x:.2f}m, y={y:.2f}m, '
                            f'angle={math.degrees(angle):.1f}° '
                            f'(confidence: {confidence:.2%})'
                        )
    
    def depth_callback(self, msg):
        """Process depth image"""
        try:
            self.depth_image = self.cv_bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')
            
            if not self.resolution_printed:
                self.image_height = msg.height
                self.image_width = msg.width
                self.get_logger().info(
                    f'Image resolution: {self.image_width}x{self.image_height}'
                )
                self.resolution_printed = True
                
        except Exception as e:
            self.get_logger().error(f'Error processing depth image: {str(e)}')

def main(args=None):
    rclpy.init(args=args)
    
    node = ObjectPositionNode()
    
    # Override parameter if provided via command line
    if args is not None:
        from rclpy.parameter import Parameter
        import sys
        import argparse
        
        parser = argparse.ArgumentParser()
        parser.add_argument('--target-object-type', type=str, help='Type of object to track')
        parser.add_argument('--horizontal-fov', type=float, help='Horizontal field of view in degrees')
        parser.add_argument('ros_args', nargs=argparse.REMAINDER)
        
        parsed_args = parser.parse_args(args if args is not None else sys.argv[1:])
        
        if parsed_args.target_object_type:
            node.set_parameters([Parameter('target_object_type', Parameter.Type.STRING, parsed_args.target_object_type)])
        if parsed_args.horizontal_fov:
            node.set_parameters([Parameter('horizontal_fov', Parameter.Type.DOUBLE, parsed_args.horizontal_fov)])
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main() 
