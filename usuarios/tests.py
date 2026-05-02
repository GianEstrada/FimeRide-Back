from django.test import TestCase, Client
from django.urls import reverse
from unittest.mock import patch, MagicMock
from django.core.files.uploadedfile import SimpleUploadedFile
from .models import Usuario, UsuarioPasajero, DocumentacionPasajero
import io

class VerificationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = Usuario.objects.create_user(
            matricula='A01234567',
            password='testpassword',
            nombre_completo='Test User',
            correo_universitario='test@uanl.edu.mx'
        )
        self.pasajero = UsuarioPasajero.objects.create(usuario=self.user)

    @patch('usuarios.views._authenticate_jwt')
    @patch('usuarios.rekognition_service._REKOGNITION_CLIENT.compare_faces')
    def test_verificar_credencial_success(self, mock_compare, mock_auth):
        mock_auth.return_value = (self.user, None)
        mock_compare.return_value = {
            'FaceMatches': [{'Similarity': 95.0}]
        }
        
        # Mock foto_perfil
        self.user.foto_perfil = SimpleUploadedFile('profile.jpg', b'profile_bytes', content_type='image/jpeg')
        self.user.save()

        credencial = SimpleUploadedFile('credencial.jpg', b'credencial_bytes', content_type='image/jpeg')
        
        response = self.client.post(
            reverse('verificar_credencial'),
            {'usuario_id': self.user.id, 'credencial_frontal': credencial}
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['match'])
        self.assertEqual(data['similarity'], 95.0)
        
        doc = DocumentacionPasajero.objects.get(pasajero=self.pasajero, tipo_documento='credencial_universitaria')
        self.assertTrue(doc.autorizado)
        self.assertEqual(doc.ai_face_similarity, 95.0)

    @patch('usuarios.views._authenticate_jwt')
    @patch('usuarios.barcode_service._REKOGNITION_CLIENT.detect_text')
    @patch('usuarios.barcode_service.convert_from_bytes')
    def test_verificar_boleta_success(self, mock_convert, mock_detect, mock_auth):
        mock_auth.return_value = (self.user, None)
        
        # Mock pdf2image to return a mock image
        mock_image = MagicMock()
        mock_convert.return_value = [mock_image]
        
        # Mock Rekognition to detect matricula and "RECIBO PAGADO"
        mock_detect.return_value = {
            'TextDetections': [
                {'DetectedText': 'MATRICULA A01234567'},
                {'DetectedText': 'RECIBO PAGADO'}
            ]
        }
        
        boleta = SimpleUploadedFile('boleta.pdf', b'pdf_bytes', content_type='application/pdf')
        
        response = self.client.post(
            reverse('verificar_boleta'),
            {'usuario_id': self.user.id, 'boleta_pdf': boleta}
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['valid'])
        self.assertEqual(data['method'], 'ocr')
        
        doc = DocumentacionPasajero.objects.filter(pasajero=self.pasajero, tipo_documento='boleta_rectoria').last()
        self.assertTrue(doc.autorizado)
        self.assertTrue(doc.ai_boleta_valid)

    @patch('usuarios.views._authenticate_jwt')
    @patch('usuarios.barcode_service._REKOGNITION_CLIENT.detect_text')
    @patch('usuarios.barcode_service.convert_from_bytes')
    def test_verificar_boleta_missing_recibo(self, mock_convert, mock_detect, mock_auth):
        mock_auth.return_value = (self.user, None)
        
        mock_image = MagicMock()
        mock_convert.return_value = [mock_image]
        
        # Only matricula, no "RECIBO PAGADO"
        mock_detect.return_value = {
            'TextDetections': [
                {'DetectedText': 'MATRICULA A01234567'},
                {'DetectedText': 'SOLO PAGADO'}
            ]
        }
        
        boleta = SimpleUploadedFile('boleta.pdf', b'pdf_bytes', content_type='application/pdf')
        
        response = self.client.post(
            reverse('verificar_boleta'),
            {'usuario_id': self.user.id, 'boleta_pdf': boleta}
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['valid'])
        
        doc = DocumentacionPasajero.objects.filter(pasajero=self.pasajero, tipo_documento='boleta_rectoria').last()
        self.assertFalse(doc.autorizado)
