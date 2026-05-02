import os
import boto3
from botocore.exceptions import BotoCoreError, ClientError


class RekognitionError(Exception):
    pass


_REKOGNITION_CLIENT = boto3.client(
    "rekognition",
    region_name=os.getenv("AWS_REKOGNITION_REGION", "us-east-2"),
)


def _get_similarity_threshold():
    raw_value = os.getenv("FACE_SIMILARITY_THRESHOLD", "80")
    try:
        return float(raw_value)
    except ValueError:
        return 80.0


def compare_faces_s3(s3_key, target_bytes):
    if not s3_key:
        raise ValueError("s3_key is required")
    if not target_bytes:
        raise ValueError("target_bytes is required")

    bucket_name = os.getenv("AWS_STORAGE_BUCKET_NAME", "fimeridearchivos")
    threshold = _get_similarity_threshold()

    try:
        response = _REKOGNITION_CLIENT.compare_faces(
            SourceImage={"S3Object": {"Bucket": bucket_name, "Name": s3_key}},
            TargetImage={"Bytes": target_bytes},
            SimilarityThreshold=threshold,
        )
    except (ClientError, BotoCoreError) as exc:
        raise RekognitionError("compare_faces_s3 failed") from exc

    face_matches = response.get("FaceMatches", [])
    if not face_matches:
        return False, 0.0

    similarity = max(match.get("Similarity", 0.0) for match in face_matches)
    return similarity >= threshold, float(similarity)


def compare_faces_bytes(source_bytes, target_bytes):
    if not source_bytes:
        raise ValueError("source_bytes is required")
    if not target_bytes:
        raise ValueError("target_bytes is required")

    threshold = _get_similarity_threshold()

    try:
        response = _REKOGNITION_CLIENT.compare_faces(
            SourceImage={"Bytes": source_bytes},
            TargetImage={"Bytes": target_bytes},
            SimilarityThreshold=threshold,
        )
    except (ClientError, BotoCoreError) as exc:
        raise RekognitionError("compare_faces_bytes failed") from exc

    face_matches = response.get("FaceMatches", [])
    if not face_matches:
        return False, 0.0

    similarity = max(match.get("Similarity", 0.0) for match in face_matches)
    return similarity >= threshold, float(similarity)


def verify_face_present(image_bytes):
    if not image_bytes:
        raise ValueError("image_bytes is required")

    try:
        response = _REKOGNITION_CLIENT.detect_faces(
            Image={"Bytes": image_bytes},
            Attributes=["DEFAULT"],
        )
    except (ClientError, BotoCoreError) as exc:
        raise RekognitionError("verify_face_present failed") from exc

    face_details = response.get("FaceDetails", [])
    if not face_details:
        return False, "no_face_detected"

    return True, "face_detected"
