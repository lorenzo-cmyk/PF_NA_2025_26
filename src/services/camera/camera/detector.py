"""YOLOv9t ONNX detector — pure inference, no threading."""

from __future__ import annotations

import logging

import cv2
import numpy as np
import onnxruntime as ort

log = logging.getLogger(__name__)

# Model outputs class names; map to MQTT schema names
_CLASS_NAMES = ["Wild Boar", "Wolf", "Deer"]
_ANIMAL_TYPE_MAP = {
    "Wild Boar": "boar",
    "Wolf": "wolf",
    "Deer": "deer",
}
_COLORS = [
    (255, 100, 50),  # Wild Boar — orange
    (100, 100, 255),  # Wolf — blue
    (50, 200, 50),  # Deer — green
]


def _estimate_distance(box_h_px: int, img_h_px: int) -> float:
    """Heuristic: estimate distance in meters from normalised bounding-box height.

    Calibration: a large animal at ~40 m fills ~10% of frame height.
    """
    if img_h_px <= 0 or box_h_px <= 0:
        return 50.0
    frac = box_h_px / img_h_px
    dist = 4.0 / frac  # k = 4 (calibrated)
    return round(min(200.0, max(1.0, dist)), 1)


def _estimate_size(box_w_px: int, box_h_px: int, img_w_px: int, img_h_px: int) -> float:
    """Heuristic: estimate body length in meters from bounding-box area fraction."""
    if img_w_px <= 0 or img_h_px <= 0:
        return 0.8
    area_frac = (box_w_px * box_h_px) / (img_w_px * img_h_px)
    size = area_frac * 8.0
    return round(min(2.5, max(0.2, size)), 2)


class Detector:
    """Loads a YOLOv9t ONNX model and exposes a single ``detect()`` method."""

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = 0.6,
        iou_threshold: float = 0.5,
    ) -> None:
        log.info("Initializing ONNX Runtime …")
        # Load NVIDIA shared libraries from venv site-packages to ensure CUDA support works on all platforms.
        ort.preload_dlls(directory="")
        # Get all available inference providers
        providers = ort.get_available_providers()
        log.info("Available ONNX Runtime providers: %s", providers)
        # Pick the best available provider (prefer GPU)
        if "CUDAExecutionProvider" in providers:
            log.info("Using 'CUDAExecutionProvider' for ONNX Runtime inference.")
            self._execution_provider = "CUDAExecutionProvider"
        elif "CPUExecutionProvider" in providers:
            log.warning(
                "'CUDAExecutionProvider' not available; falling back to CPUExecutionProvider. Inference will be slower."
            )
            self._execution_provider = "CPUExecutionProvider"
        else:
            raise RuntimeError(
                "No suitable ONNX Runtime execution provider found. Aborting."
            )

        log.info("Loading ONNX model from %s …", model_path)
        self._session = ort.InferenceSession(
            model_path, providers=[self._execution_provider]
        )
        model_input = self._session.get_inputs()[0]
        self._input_name: str = model_input.name
        self._input_shape: tuple = tuple(model_input.shape)  # (1, 3, H, W)
        self._model_h: int = int(self._input_shape[2])
        self._model_w: int = int(self._input_shape[3])
        self._confidence_threshold = confidence_threshold
        self._iou_threshold = iou_threshold
        log.info(
            "Detector ready: input=%s %s, conf=%.2f, iou=%.2f",
            self._input_name,
            self._input_shape,
            confidence_threshold,
            iou_threshold,
        )

    def detect(self, frame: np.ndarray) -> tuple[np.ndarray, list[dict]]:
        """Run the full pipeline on *frame* and return (annotated_frame, detections)."""
        img_h, img_w = frame.shape[:2]
        input_data = self._preprocess(frame)
        raw_output = self._session.run(None, {self._input_name: input_data})
        annotated, detections = self._postprocess(
            frame.copy(), raw_output, img_w, img_h
        )
        return annotated, detections

    # -- internals --------------------------------------------------------- #

    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (self._model_w, self._model_h))
        data = img.astype(np.float32) / 255.0
        data = np.transpose(data, (2, 0, 1))  # HWC → CHW
        data = np.expand_dims(data, axis=0)  # add batch
        return np.ascontiguousarray(data)

    def _postprocess(
        self,
        frame: np.ndarray,
        raw_output: list,
        img_w: int,
        img_h: int,
    ) -> tuple[np.ndarray, list[dict]]:
        # raw_output[0] shape: (1, num_classes+4, num_anchors)
        outputs = np.transpose(
            np.squeeze(raw_output[0])
        )  # → (num_anchors, 4+num_classes)
        rows = outputs.shape[0]

        x_scale = img_w / self._model_w
        y_scale = img_h / self._model_h

        boxes, scores, class_ids = [], [], []

        for i in range(rows):
            class_scores = outputs[i][4:]
            max_score = float(np.amax(class_scores))
            if max_score < self._confidence_threshold:
                continue
            class_id = int(np.argmax(class_scores))
            cx, cy, w, h = outputs[i][:4]
            x = int((cx - w / 2) * x_scale)
            y = int((cy - h / 2) * y_scale)
            bw = int(w * x_scale)
            bh = int(h * y_scale)
            boxes.append([max(0, x), max(0, y), max(0, bw), max(0, bh)])
            scores.append(max_score)
            class_ids.append(class_id)

        detections: list[dict] = []
        if not boxes:
            return frame, detections

        indices = cv2.dnn.NMSBoxes(
            boxes, scores, self._confidence_threshold, self._iou_threshold
        )
        if not len(indices):  # pylint: disable=use-implicit-booleaness-not-len
            return frame, detections

        for idx in indices:
            x, y, bw, bh = boxes[idx]
            conf = float(scores[idx])
            cid = class_ids[idx]
            class_name = _CLASS_NAMES[cid] if cid < len(_CLASS_NAMES) else "unknown"
            color = _COLORS[cid] if cid < len(_COLORS) else (200, 200, 200)

            cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
            label = f"{class_name}: {conf:.2f}"
            (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            ly = max(y - 10, lh)
            cv2.rectangle(frame, (x, ly - lh), (x + lw, ly), color, cv2.FILLED)
            cv2.putText(
                frame,
                label,
                (x, ly),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )

            detections.append(
                {
                    "animal_type": _ANIMAL_TYPE_MAP.get(class_name, class_name.lower()),
                    "confidence": round(conf, 4),
                    "distance": _estimate_distance(bh, img_h),
                    "size_estimate": _estimate_size(bw, bh, img_w, img_h),
                    "box": [x, y, bw, bh],
                }
            )

        return frame, detections
