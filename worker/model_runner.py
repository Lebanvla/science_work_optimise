from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation

from config import DEVICE, MODEL_NAME, ROAD_CLASS_INDEX, ROAD_CLASS_NAME

logger = logging.getLogger(__name__)


def _resolve_device() -> torch.device:
    if DEVICE == "cuda":
        return torch.device("cuda")
    if DEVICE == "cpu":
        return torch.device("cpu")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class SegFormerCityscapesModel:
    def __init__(self, model_name: str = MODEL_NAME, road_class_name: str = ROAD_CLASS_NAME) -> None:
        self.model_name = model_name
        self.road_class_name = road_class_name.lower().strip()
        self.device = _resolve_device()

        logger.info("Loading processor: %s", self.model_name)
        self.processor = AutoImageProcessor.from_pretrained(self.model_name)

        logger.info("Loading model: %s (device=%s)", self.model_name, self.device)
        self.model = AutoModelForSemanticSegmentation.from_pretrained(self.model_name)
        self.model.to(self.device)
        self.model.eval()

        self.road_class_id = self._resolve_road_class_id()
        logger.info("Road class '%s' -> index %s", self.road_class_name, self.road_class_id)

    def _resolve_road_class_id(self) -> int:
        if ROAD_CLASS_INDEX:
            return int(ROAD_CLASS_INDEX)

        id2label = getattr(self.model.config, "id2label", None) or {}
        normalized = {int(k): str(v).lower().strip() for k, v in id2label.items()}

        for cid, label in normalized.items():
            if label == self.road_class_name:
                return cid
        for cid, label in normalized.items():
            if self.road_class_name in label:
                return cid

        if self.road_class_name == "road":
            logger.warning("No 'road' in id2label=%s, falling back to 0", id2label)
            return 0

        raise ValueError(
            f"Cannot resolve class '{self.road_class_name}'. Set ROAD_CLASS_INDEX explicitly."
        )

    def predict(self, image_path: str) -> np.ndarray:
        image = Image.open(image_path).convert("RGB")
        width, height = image.size

        inputs = self.processor(images=image, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model(**inputs)
            logits = F.interpolate(
                outputs.logits,
                size=(height, width),
                mode="bilinear",
                align_corners=False,
            )
            predicted = logits.argmax(dim=1)[0].cpu().numpy()

        return (predicted == self.road_class_id).astype(np.uint8) * 255


def overlay_mask(image: Image.Image, mask: np.ndarray) -> Image.Image:
    image_np = np.array(image.convert("RGB")).astype(np.float32)
    if mask.shape[:2] != image_np.shape[:2]:
        mask = cv2.resize(mask, (image_np.shape[1], image_np.shape[0]), interpolation=cv2.INTER_NEAREST)

    road = mask > 0
    color = np.array([255, 128, 0], dtype=np.float32)
    alpha = 0.45
    blended = image_np.copy()
    blended[road] = (1.0 - alpha) * blended[road] + alpha * color
    return Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8))


def process_image(input_path: str, output_path: str, model: SegFormerCityscapesModel) -> None:
    src = Path(input_path)
    dst = Path(output_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        raise FileNotFoundError(f"Input image not found: {src}")

    image = Image.open(src).convert("RGB")
    mask = model.predict(str(src))
    overlay_mask(image, mask).save(dst, format="PNG")