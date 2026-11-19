"""YOLO detector node (Yoru V2).

Detects objects from one of four camera sources (ROS topic / USB / RTSP /
video file) and publishes vision_msgs/Detection2DArray in pixel coordinates.

Supports TWO models per frame, merged into one detection array:
  model_path       : main model - stock yolov8n gives 'person' (plus
                     confounders like 'cell phone') via the COCO class map
  extra_model_path : optional specialist model whose class names are used
                     as-is - e.g. a single-class 'cigarette' detector.
                     Both run on the same frame so the event confirmation
                     node sees person + cigarette together.

The custom six-class model (person, cigarette, vape_device, smoke_vapour,
hand_mouth_gesture, hand_face) can replace both via 'model_path' +
use_coco_class_map: false once trained.
"""

import json
import threading
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String
from vision_msgs.msg import Detection2D, Detection2DArray, ObjectHypothesisWithPose

import cv2
from cv_bridge import CvBridge

# Map COCO names to the project class vocabulary (confounders feed C7).
COCO_CLASS_MAP = {
    'person': 'person',
    'cell phone': 'mobile_phone',
    'remote': 'mobile_phone',
    'toothbrush': 'pen',
    'fork': 'pen',
    'cup': 'straw',
    'bottle': 'straw',
}


class YoloDetectorNode(Node):

    def __init__(self):
        super().__init__('yolo_detector_node')

        self.declare_parameter('source_type', 'ros_topic')  # ros_topic|usb|rtsp|video
        self.declare_parameter('ros_topic', '/cctv/image_raw')
        self.declare_parameter('device_index', 0)
        self.declare_parameter('rtsp_url', '')
        self.declare_parameter('video_path', '')
        self.declare_parameter('model_path', 'yolov8n.pt')
        self.declare_parameter('confidence_threshold', 0.4)
        # Optional second model on the same frame (classes used as-is)
        self.declare_parameter('extra_model_path', '')
        self.declare_parameter('extra_confidence_threshold', 0.35)
        self.declare_parameter('input_size', 640)
        self.declare_parameter('process_hz', 5.0)
        # The debug/view image is published at view_hz (smooth CCTV-style
        # video) with the latest detection boxes overlaid; YOLO itself only
        # runs at process_hz. A capture thread drains the camera constantly
        # so frames are always fresh (no OpenCV buffer lag).
        self.declare_parameter('view_hz', 15.0)
        self.declare_parameter('publish_debug_image', True)
        self.declare_parameter('detections_topic', '/compliance/detections')
        self.declare_parameter('debug_image_topic', '/compliance/debug_image')
        self.declare_parameter('use_coco_class_map', True)
        # Compute only, no effect on what is detected: PyTorch CPU threads for
        # this node. 0 keeps the library default (ultralytics sets
        # min(8, CPUs - 1) on its first prediction), which oversubscribes the
        # CPU when two detector nodes share a 16-thread machine
        # (evidence/README.md, "Same laptop, new operating system").
        self.declare_parameter('torch_threads', 0)

        self.source_type = self.get_parameter('source_type').value
        self.conf_threshold = self.get_parameter('confidence_threshold').value
        self.input_size = int(self.get_parameter('input_size').value)
        self.use_coco_map = self.get_parameter('use_coco_class_map').value
        process_hz = self.get_parameter('process_hz').value

        self.bridge = CvBridge()
        self.model = None
        self.capture = None
        self.frame_lock = threading.Lock()
        self.latest_frame = None      # (bgr image, header|None)
        self.last_boxes = []          # [(class_id, conf, x1, y1, x2, y2, color)]
        self.running = True

        det_topic = self.get_parameter('detections_topic').value
        self.det_pub = self.create_publisher(Detection2DArray, det_topic, 10)
        self.alert_pub = self.create_publisher(String, '/compliance/smoking_detected', 10)
        self.debug_pub = None
        self.debug_comp_pub = None
        self.view_count = 0
        if self.get_parameter('publish_debug_image').value:
            debug_topic = self.get_parameter('debug_image_topic').value
            # Raw frames (emailer evidence) go out at ~process_hz; the
            # smooth high-rate view is JPEG-compressed (raw 640x480 at
            # 15 fps is ~14 MB/s and gets dropped by the transport).
            self.debug_pub = self.create_publisher(Image, debug_topic, 2)
            self.debug_comp_pub = self.create_publisher(
                CompressedImage, debug_topic + '/compressed', 2)

        self._load_model()

        if self.source_type == 'ros_topic':
            topic = self.get_parameter('ros_topic').value
            self.create_subscription(Image, topic, self.image_callback, 2)
            self.get_logger().info(f'Camera source: ROS topic {topic}')
        else:
            self._open_capture()
            threading.Thread(target=self._capture_loop, daemon=True).start()

        self.create_timer(1.0 / max(process_hz, 0.5), self.process_frame)
        if self.debug_pub is not None:
            view_hz = self.get_parameter('view_hz').value
            self.create_timer(1.0 / max(view_hz, 1.0), self.view_tick)
        self.get_logger().info(
            f'YOLO detector ready (model={self.get_parameter("model_path").value}, '
            f'source={self.source_type}, publishing {det_topic})')

    def _load_model(self):
        model_path = self.get_parameter('model_path').value
        try:
            from ultralytics import YOLO
            self.model = YOLO(model_path)
        except Exception as exc:  # noqa: BLE001 - report and run degraded
            self.get_logger().error(
                f'Could not load YOLO model "{model_path}": {exc}. '
                'Node stays alive but publishes no detections.')
            self.model = None

        self.extra_model = None
        extra_path = self.get_parameter('extra_model_path').value
        if extra_path:
            try:
                from ultralytics import YOLO
                self.extra_model = YOLO(extra_path)
                self.get_logger().info(
                    f'Extra model loaded: {extra_path} '
                    f'(classes: {list(self.extra_model.names.values())})')
            except Exception as exc:  # noqa: BLE001 - main model still runs
                self.get_logger().error(
                    f'Could not load extra model "{extra_path}": {exc}. '
                    'Continuing with the main model only.')
        self._limit_torch_threads()

    def _limit_torch_threads(self):
        threads = int(self.get_parameter('torch_threads').value)
        if threads <= 0 or self.model is None:
            return
        import numpy as np
        import torch
        # ultralytics resets the thread count on its first prediction only, so
        # warm every model up once on a blank frame, then apply the limit.
        blank = np.zeros((self.input_size, self.input_size, 3), np.uint8)
        for model in (self.model, self.extra_model):
            if model is not None:
                model.predict(blank, imgsz=self.input_size, verbose=False)
        default = torch.get_num_threads()
        torch.set_num_threads(threads)
        self.get_logger().info(
            f'torch_threads={torch.get_num_threads()} (library default {default})')

    def _open_capture(self):
        if self.source_type == 'usb':
            src = int(self.get_parameter('device_index').value)
        elif self.source_type == 'rtsp':
            src = self.get_parameter('rtsp_url').value
        elif self.source_type == 'video':
            src = self.get_parameter('video_path').value
        else:
            self.get_logger().error(f'Unknown source_type: {self.source_type}')
            return
        self.capture = cv2.VideoCapture(src)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.capture.isOpened():
            self.get_logger().error(f'Failed to open camera source: {src}')

    def _capture_loop(self):
        """Continuously drains the camera so the newest frame is always
        available - reading only at process_hz lets V4L/RTSP buffers queue
        stale frames, which is what makes the view lag and stutter."""
        video_pacing = 1.0 / 25.0 if self.source_type == 'video' else 0.0
        while self.running:
            if self.capture is None or not self.capture.isOpened():
                time.sleep(1.0)
                continue
            ok, frame = self.capture.read()
            if not ok:
                if self.source_type == 'video':  # loop test videos
                    self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                else:
                    time.sleep(0.5)
                continue
            with self.frame_lock:
                self.latest_frame = (frame, None)
            if video_pacing:
                time.sleep(video_pacing)

    def image_callback(self, msg):
        frame = self.bridge.imgmsg_to_cv2(msg, 'bgr8')
        with self.frame_lock:
            self.latest_frame = (frame, msg.header)

    def view_tick(self):
        """Publishes the smooth view: newest frame + latest boxes overlay.
        JPEG-compressed at full view_hz; raw every 3rd frame (emailer)."""
        with self.frame_lock:
            snap = self.latest_frame
            boxes = list(self.last_boxes)
        if snap is None:
            return
        frame = snap[0].copy()
        for class_id, conf, x1, y1, x2, y2, color in boxes:
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)),
                          color, 2)
            cv2.putText(frame, f'{class_id} {conf:.2f}',
                        (int(x1), max(int(y1) - 5, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        ok, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            msg = CompressedImage()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.format = 'jpeg'
            msg.data = jpg.tobytes()
            self.debug_comp_pub.publish(msg)

        self.view_count += 1
        if self.view_count % 3 == 0:   # raw at ~view_hz/3 for the emailer
            self.debug_pub.publish(self.bridge.cv2_to_imgmsg(frame, 'bgr8'))

    def process_frame(self):
        if self.model is None:
            return
        with self.frame_lock:
            snap = self.latest_frame
        if snap is None:
            return
        frame, header = snap[0].copy(), snap[1]

        array = Detection2DArray()
        if header is not None:
            array.header = header
        else:
            array.header.stamp = self.get_clock().now().to_msg()
            array.header.frame_id = 'camera'

        alert_classes = []
        boxes = []
        # Main model (COCO map filters it to the project vocabulary)
        self._detect(self.model, frame, self.conf_threshold,
                     self.use_coco_map, array, alert_classes, boxes, (0, 200, 0))
        # Specialist model, e.g. the smoking/vape detector (classes as-is)
        if self.extra_model is not None:
            extra_conf = self.get_parameter('extra_confidence_threshold').value
            self._detect(self.extra_model, frame, extra_conf,
                         False, array, alert_classes, boxes, (0, 0, 230))

        self.det_pub.publish(array)
        with self.frame_lock:
            self.last_boxes = boxes   # view_tick overlays these

        if alert_classes:
            alert = String()
            alert.data = json.dumps({
                'stamp': float(self.get_clock().now().nanoseconds) * 1e-9,
                'classes': alert_classes,
            })
            self.alert_pub.publish(alert)

    def _detect(self, model, frame, conf, use_coco_map, array, alert_classes,
                boxes, color):
        """Runs one model on the frame, appending detections to the shared
        array (and box overlays to the shared list) so both models' results
        arrive in a single message for the confirmation node."""
        results = model.predict(
            frame, imgsz=self.input_size, conf=conf, verbose=False)
        names = results[0].names
        for box in results[0].boxes:
            raw_name = names[int(box.cls[0])]
            if use_coco_map:
                class_id = COCO_CLASS_MAP.get(raw_name)
                if class_id is None:
                    continue
            else:
                class_id = raw_name

            x1, y1, x2, y2 = [float(v) for v in box.xyxy[0]]
            det = Detection2D()
            det.header = array.header
            det.bbox.center.position.x = (x1 + x2) / 2.0
            det.bbox.center.position.y = (y1 + y2) / 2.0
            det.bbox.size_x = x2 - x1
            det.bbox.size_y = y2 - y1
            hyp = ObjectHypothesisWithPose()
            hyp.hypothesis.class_id = class_id
            hyp.hypothesis.score = float(box.conf[0])
            det.results.append(hyp)
            array.detections.append(det)
            if class_id in ('cigarette', 'vape_device'):
                alert_classes.append(class_id)
            boxes.append((class_id, float(box.conf[0]), x1, y1, x2, y2, color))


def main(args=None):
    rclpy.init(args=args)
    node = YoloDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
