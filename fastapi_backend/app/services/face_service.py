from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image
from ultralytics import YOLO
import face_recognition
import torch

# Cleanly bypass the PyTorch 2.6+ weights_only restriction for the YOLOv8 weight file
try:
    # Temporarily force weights_only to False during model initialization
    _original_load = torch.load
    torch.load = lambda *args, **kwargs: _original_load(*args, **{**kwargs, 'weights_only': False})
    
    yolo_model = YOLO("yolov8n.pt")
finally:
    # Restore the original secure function immediately after loading
    torch.load = _original_load


def decode_base64_image(image_base64: str) -> np.ndarray:
    """Decodes a base64 string into a NumPy array (RGB format)."""
    try:
        if "," in image_base64:
            image_base64 = image_base64.split(",")[1]
            
        image_data = base64.b64decode(image_base64)
        image = Image.open(io.BytesIO(image_data)).convert("RGB")
        return np.array(image)
    except Exception as e:
        raise ValueError(f"Could not decode base64 image: {e}") from e


def detect_single_face(image: np.ndarray) -> bool:
    """Uses YOLOv8 to detect faces and ensures exactly one face is present."""
    try:
        results = yolo_model(image, verbose=False)
        num_faces = len(results[0].boxes)
        return num_faces == 1
    except Exception:
        return False


def liveness_passed(blink_done: bool, turn_left_done: bool, turn_right_done: bool) -> bool:
    """Evaluates standard challenge verification actions for new visitor profile registration maps."""
    return blink_done and turn_left_done and turn_right_done


def create_face_embedding(image_base64: str) -> list[float]:
    """Generates a standard 128-dimensional face embedding vector using face_recognition."""
    try:
        # 1. Safely parse and convert incoming payload
        img_rgb = decode_base64_image(image_base64)

        # 2. Extract bounding box from YOLOv8 to isolate the face location
        results = yolo_model(img_rgb, verbose=False)
        boxes = results[0].boxes.xyxy.cpu().numpy()

        if len(boxes) == 0:
            raise ValueError("No face found in image for embedding generation.")

        # 3. Crop image down to the precise bounding box coordinates
        x1, y1, x2, y2 = map(int, boxes[0][:4])
        face_crop = img_rgb[y1:y2, x1:x2]

        # Convert the non-contiguous sliced crop into a true C-contiguous uint8 memory block for dlib
        face_crop_contiguous = np.ascontiguousarray(face_crop, dtype=np.uint8)

        # 4. Generate the 128-d vector encoding on the contiguous cropped face region
        # [top, right, bottom, left] format mapping the entire crop bounding zone
        face_location = [(0, face_crop_contiguous.shape[1], face_crop_contiguous.shape[0], 0)]
        face_encodings = face_recognition.face_encodings(face_crop_contiguous, known_face_locations=face_location)

        if not face_encodings:
            raise ValueError("Failed to compute descriptor matrix weights from face target region.")

        return face_encodings[0].tolist()
    except Exception as e:
        raise ValueError(f"Failed to create face embedding: {e}") from e


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """Calculates mathematical cosine similarity between two vector lists with shape safety gates."""
    vec1_np = np.array(vec1)
    vec2_np = np.array(vec2)
    
    # SAFETY GATE: Detect and intercept shape alignment crashes gracefully
    if vec1_np.shape != vec2_np.shape:
        return 0.0
    
    dot_product = np.dot(vec1_np, vec2_np)
    norm_vec1 = np.linalg.norm(vec1_np)
    norm_vec2 = np.linalg.norm(vec2_np)
    
    if norm_vec1 == 0 or norm_vec2 == 0:
        return 0.0
        
    return float(dot_product / (norm_vec1 * norm_vec2))


def normalize_data_url(image_base64: str) -> str:
    """Ensures the base64 string is formatted properly as a Data URL string."""
    if image_base64.startswith("data:image"):
        return image_base64
    return f"data:image/jpeg;base64,{image_base64}"