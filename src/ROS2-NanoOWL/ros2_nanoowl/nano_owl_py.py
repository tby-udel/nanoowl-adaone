# SPDX-FileCopyrightText: Copyright (c) <year> NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import Image
from vision_msgs.msg import Detection2D, Detection2DArray, ObjectHypothesisWithPose
from cv_bridge import CvBridge
import cv2
import numpy as np
import os
from PIL import Image as im
from nanoowl.owl_predictor import (OwlPredictor)
from nanoowl.owl_drawing import (draw_owl_output)

class Nano_OWL_Subscriber(Node):

    def __init__(self):
        super().__init__('nano_owl_subscriber')
        
        self.declare_parameter('model', '/workspaces/isaac_ros-dev/my_model')
        self.declare_parameter('device', 'cuda')
        self.declare_parameter('image_encoder_engine', '/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/my_model_image_encoder.engine')
        self.declare_parameter('thresholds', rclpy.Parameter.Type.DOUBLE)
        self.declare_parameter('publish_output_image', False)

        # Subscriber for input query
        self.query_subscription = self.create_subscription(
            String,
            'input_query',
            self.query_listener_callback,
            10)
        self.query_subscription  # prevent unused variable warning

        # Subscriber for input image
        self.image_subscription = self.create_subscription(
            Image,
            'input_image',
            self.listener_callback,
            1)
        self.image_subscription  # prevent unused variable warning

        # To convert ROS image message to OpenCV image
        self.cv_br = CvBridge() 

        self.output_publisher = self.create_publisher(Detection2DArray, 'output_detections', 10)
        self.output_image_publisher = self.create_publisher(Image, 'output_image', 10)

        self.model = self.get_parameter('model').get_parameter_value().string_value
        self.device = self.get_parameter('device').get_parameter_value().string_value
        self.image_encoder_engine = self.get_parameter('image_encoder_engine').get_parameter_value().string_value
        self.publish_output_image = self.get_parameter('publish_output_image').get_parameter_value().bool_value
        self.processing_image = False

        predictor_kwargs = {
            'device': self.device,
        }
        if self.device == 'cuda' and self.image_encoder_engine and os.path.exists(self.image_encoder_engine):
            predictor_kwargs['image_encoder_engine'] = self.image_encoder_engine
        elif self.device == 'cuda' and self.image_encoder_engine:
            self.get_logger().warning(
                f'TensorRT engine not found at {self.image_encoder_engine}; falling back to direct model inference.'
            )

        self.predictor = OwlPredictor(
         self.model,
         **predictor_kwargs
        )

        self.query = "a person, a box"
        self.query_text = []
        self.query_text_encodings = None
        self._update_query_cache(self.query)

    def _update_query_cache(self, query: str):
        self.query = query
        prompt = query.strip("][()")
        self.query_text = [part.strip() for part in prompt.split(',') if part.strip()]
        if not self.query_text:
            self.query_text = ["a person"]
        self.query_text_encodings = self.predictor.encode_text(self.query_text)
        self.get_logger().info('Updated query: %s' % self.query_text)

    def query_listener_callback(self, msg):
        if msg.data != self.query:
            self._update_query_cache(msg.data)


    def listener_callback(self, data):
        if self.processing_image:
            return

        self.processing_image = True

        thresholds = self.get_parameter('thresholds').get_parameter_value().double_value

        try:
            # call model with input_query and input_image
            cv_img = self.cv_br.imgmsg_to_cv2(data, 'rgb8')
            PIL_img = im.fromarray(cv_img)
            text = self.query_text
            thresholds = [thresholds] * len(text)

            output = self.predictor.predict(
                image=PIL_img,
                text=text,
                text_encodings=self.query_text_encodings,
                threshold=thresholds,
                pad_square=False
            )

            detections_arr = Detection2DArray()
            detections_arr.header = data.header

            num_detections = len(output.labels)

            for i in range(num_detections):
                box = output.boxes[i]
                label_index = int(output.labels[i])
                box = [float(x) for x in box]
                top_left = (box[0], box[1])
                bottom_right = (box[2], box[3])
                obj = Detection2D()
                obj.bbox.size_x = abs(box[2] - box[0])
                obj.bbox.size_y = abs(box[1] - box[3])
                obj.bbox.center.position.x = (box[0] + box[2]) / 2.0
                obj.bbox.center.position.y = (box[1] + box[3]) / 2.0
                hyp = ObjectHypothesisWithPose()
                hyp.hypothesis.class_id = str(label_index)
                obj.results.append(hyp)
                obj.header = data.header
                detections_arr.detections.append(obj)

            self.output_publisher.publish(detections_arr)

            if self.publish_output_image:
                image = draw_owl_output(PIL_img, output, text=text, draw_text=True)
                # convert PIL image to ROS2 image message before publishing
                image = np.array(image)
                # convert RGB to BGR
                image = image[:, :, ::-1].copy()

                self.output_image_publisher.publish(self.cv_br.cv2_to_imgmsg(image, "bgr8"))
        finally:
            self.processing_image = False



def main(args=None):
    rclpy.init(args=args)

    nano_owl_subscriber = Nano_OWL_Subscriber()

    rclpy.spin(nano_owl_subscriber)

    # Destroy the node explicitly
    # (optional - otherwise it will be done automatically
    # when the garbage collector destroys the node object)
    nano_owl_subscriber.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
