import io
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pdf2image import convert_from_bytes
from pyzbar.pyzbar import decode

from .rekognition_service import RekognitionError


_REKOGNITION_CLIENT = boto3.client(
    "rekognition",
    region_name=os.getenv("AWS_REKOGNITION_REGION", "us-east-2"),
)


def _normalize_text(value):
    if value is None:
        return ""
    return "".join(value.split()).upper()


def _image_to_jpeg_bytes(image):
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def extract_matricula_from_pdf(pdf_bytes, matricula):
    if not pdf_bytes:
        raise ValueError("pdf_bytes is required")
    if not matricula:
        raise ValueError("matricula is required")

    images = convert_from_bytes(pdf_bytes, dpi=200, first_page=1, last_page=1)
    if not images:
        return False, "", "barcode"

    image = images[0]
    normalized_matricula = _normalize_text(matricula)
    normalized_recibo = _normalize_text("RECIBO PAGADO")

    try:
        decoded = decode(image)
        if decoded:
            detected_text = " ".join(
                code.data.decode("utf-8", errors="ignore") for code in decoded
            )
            normalized_text = _normalize_text(detected_text)
            valid = normalized_matricula in normalized_text and normalized_recibo in normalized_text
            return valid, detected_text, "barcode"
    except Exception:
        pass

    try:
        image_bytes = _image_to_jpeg_bytes(image)
        response = _REKOGNITION_CLIENT.detect_text(Image={"Bytes": image_bytes})
    except (ClientError, BotoCoreError) as exc:
        raise RekognitionError("detect_text failed") from exc

    detected_text = " ".join(
        item.get("DetectedText", "") for item in response.get("TextDetections", [])
    ).strip()
    normalized_text = _normalize_text(detected_text)
    valid = normalized_matricula in normalized_text and normalized_recibo in normalized_text
    return valid, detected_text, "ocr"
