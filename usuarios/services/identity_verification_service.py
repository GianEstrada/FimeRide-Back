import re
from decimal import Decimal

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings


class IdentityVerificationService:
    def __init__(self):
        self.rekognition = boto3.client(
            "rekognition",
            region_name=settings.AWS_S3_REGION_NAME,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
        self.textract = boto3.client(
            "textract",
            region_name=settings.AWS_S3_REGION_NAME,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )

    def _read_bytes(self, uploaded_file):
        uploaded_file.seek(0)
        data = uploaded_file.read()
        uploaded_file.seek(0)
        return data

    def _normalize(self, text):
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip().upper()

    def _extract_text_pdf_or_image(self, uploaded_file):
        raw = self._read_bytes(uploaded_file)
        response = self.textract.detect_document_text(Document={"Bytes": raw})
        lines = [
            block.get("Text", "")
            for block in response.get("Blocks", [])
            if block.get("BlockType") == "LINE"
        ]
        return self._normalize(" ".join(lines)), response

    def _extract_text_image(self, uploaded_file):
        raw = self._read_bytes(uploaded_file)
        response = self.rekognition.detect_text(Image={"Bytes": raw})
        lines = [
            item.get("DetectedText", "")
            for item in response.get("TextDetections", [])
            if item.get("Type") == "LINE"
        ]
        return self._normalize(" ".join(lines)), response

    def _contains_paid_ticket_text(self, text):
        return bool(re.search(r"BOLETA\s+(PAGADA|PAGADO)", text))

    def _clean_matricula(self, value):
        return re.sub(r"[^A-Z0-9]", "", (value or "").upper())

    def _text_has_matricula(self, text, matricula):
        normalized_text = self._clean_matricula(text)
        normalized_matricula = self._clean_matricula(matricula)
        return bool(normalized_matricula) and normalized_matricula in normalized_text

    def compare_faces_bytes(self, source_uploaded_file, target_uploaded_file, threshold):
        source_bytes = self._read_bytes(source_uploaded_file)
        target_bytes = self._read_bytes(target_uploaded_file)

        response = self.rekognition.compare_faces(
            SourceImage={"Bytes": source_bytes},
            TargetImage={"Bytes": target_bytes},
            SimilarityThreshold=threshold,
        )

        matches = response.get("FaceMatches", [])
        if not matches:
            return {
                "match": False,
                "similarity": Decimal("0"),
                "response": response,
            }

        best = max(matches, key=lambda item: item.get("Similarity", 0))
        similarity = Decimal(str(best.get("Similarity", 0)))
        return {
            "match": True,
            "similarity": similarity,
            "response": response,
        }

    def validate_registration_documents(
        self,
        matricula,
        boleta_pdf,
        foto_perfil,
        credencial_frontal=None,
        credencial_digital_pdf=None,
    ):
        threshold = float(getattr(settings, "REKOGNITION_SIMILARITY_THRESHOLD", 90))

        boleta_text, boleta_raw = self._extract_text_pdf_or_image(boleta_pdf)
        if credencial_frontal is not None:
            credencial_text, credencial_raw = self._extract_text_image(credencial_frontal)
            face = self.compare_faces_bytes(
                source_uploaded_file=credencial_frontal,
                target_uploaded_file=foto_perfil,
                threshold=threshold,
            )
        else:
            credencial_text, credencial_raw = self._extract_text_pdf_or_image(credencial_digital_pdf)
            face = {
                "match": True,
                "similarity": Decimal("100"),
                "response": {"detalle": "Face match omitido por credencial digital en PDF"},
            }

        boleta_pagada = self._contains_paid_ticket_text(boleta_text)
        matricula_en_boleta = self._text_has_matricula(boleta_text, matricula)
        matricula_en_credencial = self._text_has_matricula(credencial_text, matricula)
        matricula_coincide = matricula_en_boleta and matricula_en_credencial

        aprobado = boleta_pagada and matricula_coincide and face["match"]

        return {
            "aprobado": aprobado,
            "boleta_pagada": boleta_pagada,
            "matricula_en_boleta": matricula_en_boleta,
            "matricula_en_credencial": matricula_en_credencial,
            "matricula_coincide": matricula_coincide,
            "face_match": face["match"],
            "face_similarity": face["similarity"],
            "motivo": self._build_rejection_reason(
                boleta_pagada=boleta_pagada,
                matricula_coincide=matricula_coincide,
                face_match=face["match"],
            ),
            "raw": {
                "boleta_textract": boleta_raw,
                "credencial_rekognition_text": credencial_raw,
                "face_compare": face["response"],
            },
        }

    def _build_rejection_reason(self, boleta_pagada, matricula_coincide, face_match):
        reasons = []
        if not boleta_pagada:
            reasons.append("La boleta no contiene el texto BOLETA PAGADA/PAGADO.")
        if not matricula_coincide:
            reasons.append("La matricula no coincide entre boleta y credencial.")
        if not face_match:
            reasons.append("La foto de perfil no coincide con el rostro de la credencial.")
        return " ".join(reasons)


identity_verification_service = IdentityVerificationService()


def safe_validate_registration(
    matricula,
    boleta_pdf,
    foto_perfil,
    credencial_frontal=None,
    credencial_digital_pdf=None,
):
    try:
        return identity_verification_service.validate_registration_documents(
            matricula=matricula,
            boleta_pdf=boleta_pdf,
            foto_perfil=foto_perfil,
            credencial_frontal=credencial_frontal,
            credencial_digital_pdf=credencial_digital_pdf,
        )
    except (ClientError, BotoCoreError, ValueError) as exc:
        return {
            "aprobado": False,
            "boleta_pagada": False,
            "matricula_en_boleta": False,
            "matricula_en_credencial": False,
            "matricula_coincide": False,
            "face_match": False,
            "face_similarity": Decimal("0"),
            "motivo": f"Error al verificar documentos en AWS: {exc}",
            "raw": {},
        }


def safe_compare_live_face(reference_photo, live_photo):
    threshold = float(getattr(settings, "REKOGNITION_LOGIN_SIMILARITY_THRESHOLD", 90))
    try:
        result = identity_verification_service.compare_faces_bytes(
            source_uploaded_file=reference_photo,
            target_uploaded_file=live_photo,
            threshold=threshold,
        )
        return {
            "match": result["match"],
            "similarity": result["similarity"],
            "error": None,
        }
    except (ClientError, BotoCoreError, ValueError) as exc:
        return {
            "match": False,
            "similarity": Decimal("0"),
            "error": str(exc),
        }
