# Plan de Implementación: Verificación de Identidad con Reconocimiento Facial
## Sistema FimeRide - Amazon Rekognition + Django

---

## Tabla de Contenidos

1. [Resumen Ejecutivo](#1-resumen-ejecutivo)
2. [Requisitos Previos](#2-requisitos-previos)
3. [Arquitectura de la Solución](#3-arquitectura-de-la-solución)
4. [Configuración de AWS](#4-configuración-de-aws)
5. [Modificaciones al Backend Django](#5-modificaciones-al-backend-django)
6. [Implementación Paso a Paso](#6-implementación-paso-a-paso)
7. [Seguridad y Privacidad](#7-seguridad-y-privacidad)
8. [Pruebas y Validación](#8-pruebas-y-validación)
9. [Costos Estimados](#9-costos-estimados)
10. [Manejo de Errores](#10-manejo-de-errores)
11. [Mantenimiento y Monitoreo](#11-mantenimiento-y-monitoreo)

---

## 1. Resumen Ejecutivo

### 1.1 Objetivo
Implementar un sistema de verificación de identidad facial para nuevos usuarios de FimeRide que compare:
- **Imagen de Identificación Oficial** (INE, credencial universitaria, etc.)
- **Selfie en Tiempo Real** del usuario

### 1.2 Tecnología Principal
**Amazon Rekognition** - Servicio de análisis de imágenes y reconocimiento facial basado en deep learning.

### 1.3 Funcionalidad Clave
Utilizar la API `CompareFaces` de Rekognition para:
- Detectar rostros en ambas imágenes
- Calcular similitud facial (0-100%)
- Validar que las imágenes corresponden a la misma persona
- Detectar intentos de fraude (fotos de fotos, etc.)

### 1.4 Beneficios
- Mayor seguridad en el registro de usuarios  
- Reducción de perfiles falsos  
- Cumplimiento con políticas de verificación KYC  
- Proceso automatizado (sin revisión manual)  
- Escalable y de alta precisión  

---

## 2. Requisitos Previos

### 2.1 Infraestructura Actual (Ya Disponible)
- Django 5.1.7
- AWS S3 configurado (bucket: `fimeridearchivos`)
- boto3 instalado
- Credenciales AWS configuradas
- Modelos de Usuario y Documentación existentes

### 2.2 Servicios AWS Requeridos
- **Amazon S3** - Almacenamiento de imágenes (ya configurado)
- **Amazon Rekognition** - Servicio de reconocimiento facial (a configurar)
- **IAM Policies** - Permisos adicionales necesarios

### 2.3 Dependencias de Python
```txt
# Ya instaladas:
boto3==1.28.0
Pillow==11.2.1

# A instalar:
boto3>=1.34.0  # Actualizar a versión más reciente si es necesario
botocore>=1.34.0
python-magic-bin==0.4.14  # Para validación de tipos de archivo (opcional)
```

### 2.4 Requisitos de Cuenta AWS
- Cuenta AWS activa
- Acceso a la consola de AWS
- Permisos de administrador para configurar IAM
- Región compatible con Rekognition (recomendado: `us-east-2` - tu región actual)

---

## 3. Arquitectura de la Solución

### 3.1 Flujo del Proceso

```
┌─────────────────┐
│  Usuario crea   │
│  nueva cuenta   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│ 1. Usuario sube:        │
│    - Foto de ID oficial │
│    - Selfie             │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ 2. Django Backend:      │
│    - Valida formato     │
│    - Sube a S3          │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ 3. AWS Rekognition:     │
│    - CompareFaces API   │
│    - Analiza similitud  │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ 4. Decisión:            │
│    - Similitud ≥ 90%    │
│      Verificado         │
│    - Similitud < 90%    │
│      Rechazado          │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ 5. Actualiza DB:        │
│    - Estado verificación│
│    - Puntaje similitud  │
│    - Timestamp          │
└─────────────────────────┘
```

### 3.2 Componentes del Sistema

#### A. Frontend/Cliente (Mobile App)
- Captura selfie con cámara
- Carga imagen de identificación
- Envía ambas imágenes al backend

#### B. Django Backend
- **Endpoint de verificación**: `/api/verificar-identidad/`
- **Validaciones previas**:
  - Formato de imagen (JPEG, PNG)
  - Tamaño máximo (5MB)
  - Resolución mínima (640x480)
- **Procesamiento**:
  - Almacenamiento en S3
  - Llamada a Rekognition
  - Registro en base de datos

#### C. Amazon Rekognition
- **Operación**: `CompareFaces`
- **Entrada**: 2 imágenes (source y target)
- **Salida**: 
  - Similarity score (0-100)
  - BoundingBox del rostro
  - Confidence level
  - FaceMatches array

#### D. Base de Datos
- Registro de verificación
- Metadatos de las imágenes
- Resultado de comparación
- Auditoría

---

## 4. Configuración de AWS

### 4.1 Configurar Permisos IAM

#### Paso 1: Crear Política Personalizada
1. Ve a **AWS Console** → **IAM** → **Policies**
2. Click en **Create Policy**
3. Selecciona la pestaña **JSON**
4. Pega la siguiente política:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "RekognitionFaceComparison",
            "Effect": "Allow",
            "Action": [
                "rekognition:CompareFaces",
                "rekognition:DetectFaces",
                "rekognition:DetectModerationLabels"
            ],
            "Resource": "*"
        },
        {
            "Sid": "S3ImageAccess",
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:PutObjectAcl"
            ],
            "Resource": [
                "arn:aws:s3:::fimeridearchivos/*",
                "arn:aws:s3:::fimeridearchivos/verificacion-identidad/*"
            ]
        }
    ]
}
```

5. Nombra la política: `FimeRide-Rekognition-Policy`
6. Click **Create Policy**

#### Paso 2: Adjuntar Política al Usuario IAM
1. Ve a **IAM** → **Users**
2. Selecciona el usuario que usa tu aplicación
3. Click en **Add permissions** → **Attach policies directly**
4. Busca y selecciona `FimeRide-Rekognition-Policy`
5. Click **Add permissions**

### 4.2 Verificar Región de Rekognition

Amazon Rekognition está disponible en las siguientes regiones:
- **us-east-2** (Ohio) - Tu región actual
- us-east-1 (Virginia)
- us-west-2 (Oregon)
- eu-west-1 (Irlanda)
- ap-southeast-1 (Singapur)

**No requieres cambios** - `us-east-2` es compatible.

### 4.3 Crear Carpeta en S3 para Verificación

```bash
# Estructura recomendada en tu bucket:
fimeridearchivos/
├── documentos/
│   ├── conductores/
│   └── pasajeros/
├── fotos_perfil/
└── verificacion-identidad/     # NUEVA CARPETA
    ├── identificaciones/        # Fotos de ID oficial
    └── selfies/                 # Selfies de usuarios
```

**Opción 1: Crear desde AWS Console**
1. Ve a S3 → `fimeridearchivos`
2. Click **Create folder**
3. Nombre: `verificacion-identidad`
4. Crea subcarpetas: `identificaciones` y `selfies`

**Opción 2: Crear desde código (se hará automáticamente al subir archivos)**

### 4.4 Probar Acceso a Rekognition

Ejecuta este comando desde tu terminal local o servidor:

```bash
aws rekognition describe-projects --region us-east-2
```

**Respuesta esperada**: Lista de proyectos (puede estar vacía) sin errores.

---

## 5. Modificaciones al Backend Django

### 5.1 Actualizar Modelos de Base de Datos

#### Archivo: `usuarios/models.py`

Agregar nuevo modelo para verificación de identidad:

```python
class VerificacionIdentidad(models.Model):
    """
    Modelo para almacenar resultados de verificación facial
    """
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('verificado', 'Verificado'),
        ('rechazado', 'Rechazado'),
        ('error', 'Error en Verificación'),
    ]
    
    id = models.AutoField(primary_key=True)
    usuario = models.OneToOneField(
        Usuario, 
        on_delete=models.CASCADE,
        related_name='verificacion_identidad'
    )
    
    # Imágenes almacenadas en S3
    imagen_identificacion = models.ImageField(
        upload_to='verificacion-identidad/identificaciones/',
        help_text='Foto de identificación oficial'
    )
    imagen_selfie = models.ImageField(
        upload_to='verificacion-identidad/selfies/',
        help_text='Selfie del usuario'
    )
    
    # Resultados de Rekognition
    similitud_facial = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Porcentaje de similitud (0-100)'
    )
    confianza_rekognition = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Nivel de confianza de Rekognition'
    )
    rostro_detectado_id = models.BooleanField(
        default=False,
        help_text='Se detectó rostro en identificación'
    )
    rostro_detectado_selfie = models.BooleanField(
        default=False,
        help_text='Se detectó rostro en selfie'
    )
    
    # Estado y auditoría
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default='pendiente'
    )
    fecha_verificacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    # Metadatos adicionales
    respuesta_rekognition = models.JSONField(
        null=True,
        blank=True,
        help_text='Respuesta completa de AWS Rekognition (para auditoría)'
    )
    mensaje_error = models.TextField(
        null=True,
        blank=True,
        help_text='Mensaje de error si la verificación falla'
    )
    
    # Información de revisión manual (si aplica)
    requiere_revision_manual = models.BooleanField(default=False)
    revisado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verificaciones_revisadas'
    )
    notas_revision = models.TextField(null=True, blank=True)
    
    class Meta:
        db_table = 'verificacion_identidad'
        verbose_name = 'Verificación de Identidad'
        verbose_name_plural = 'Verificaciones de Identidad'
        ordering = ['-fecha_verificacion']
    
    def __str__(self):
        return f"Verificación de {self.usuario.matricula} - {self.estado}"
    
    @property
    def es_verificado(self):
        """Retorna True si el usuario está verificado"""
        return self.estado == 'verificado'
    
    @property
    def cumple_umbral_similitud(self):
        """Verifica si cumple con el umbral mínimo de similitud (90%)"""
        if self.similitud_facial:
            return self.similitud_facial >= 90.0
        return False
```

#### Modificar modelo Usuario para incluir flag de verificación:

```python
class Usuario(AbstractBaseUser, PermissionsMixin):
    # ... campos existentes ...
    
    # AGREGAR ESTE CAMPO:
    identidad_verificada = models.BooleanField(
        default=False,
        help_text='Indica si la identidad del usuario fue verificada con reconocimiento facial'
    )
    fecha_verificacion_identidad = models.DateTimeField(
        null=True, 
        blank=True,
        help_text='Fecha en que se verificó la identidad'
    )
    
    # ... resto del modelo ...
```

### 5.2 Crear Servicio de Rekognition

#### Archivo: `usuarios/services/rekognition_service.py` (NUEVO)

```python
"""
Servicio para interactuar con Amazon Rekognition
"""
import boto3
import logging
from decimal import Decimal
from django.conf import settings
from botocore.exceptions import ClientError, BotoCoreError

logger = logging.getLogger(__name__)

class RekognitionService:
    """
    Servicio para comparación de rostros usando AWS Rekognition
    """
    
    def __init__(self):
        """Inicializa el cliente de Rekognition"""
        self.client = boto3.client(
            'rekognition',
            region_name=settings.AWS_S3_REGION_NAME,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )
        self.s3_bucket = settings.AWS_STORAGE_BUCKET_NAME
    
    def comparar_rostros(self, imagen_fuente_path, imagen_objetivo_path, umbral_similitud=90):
        """
        Compara dos rostros usando Rekognition CompareFaces API
        
        Args:
            imagen_fuente_path (str): Ruta en S3 de la imagen de identificación
            imagen_objetivo_path (str): Ruta en S3 del selfie
            umbral_similitud (int): Umbral mínimo de similitud (0-100)
        
        Returns:
            dict: Resultados de la comparación
                {
                    'exito': bool,
                    'rostros_coinciden': bool,
                    'similitud': Decimal,
                    'confianza': Decimal,
                    'rostro_detectado_fuente': bool,
                    'rostro_detectado_objetivo': bool,
                    'numero_rostros_fuente': int,
                    'numero_rostros_objetivo': int,
                    'respuesta_completa': dict,
                    'mensaje_error': str
                }
        """
        try:
            # Llamar a CompareFaces API
            response = self.client.compare_faces(
                SourceImage={
                    'S3Object': {
                        'Bucket': self.s3_bucket,
                        'Name': imagen_fuente_path
                    }
                },
                TargetImage={
                    'S3Object': {
                        'Bucket': self.s3_bucket,
                        'Name': imagen_objetivo_path
                    }
                },
                SimilarityThreshold=umbral_similitud,
                QualityFilter='AUTO'  # Filtra imágenes de baja calidad
            )
            
            # Procesar respuesta
            face_matches = response.get('FaceMatches', [])
            unmatched_faces = response.get('UnmatchedFaces', [])
            source_face = response.get('SourceImageFace', {})
            
            # Determinar si hay coincidencia
            rostros_coinciden = len(face_matches) > 0
            
            # Extraer similitud y confianza
            similitud = Decimal('0.0')
            confianza = Decimal('0.0')
            
            if rostros_coinciden and face_matches:
                # Tomar la primera coincidencia (normalmente solo hay una)
                mejor_coincidencia = face_matches[0]
                similitud = Decimal(str(mejor_coincidencia['Similarity']))
                confianza = Decimal(str(mejor_coincidencia['Face']['Confidence']))
            
            resultado = {
                'exito': True,
                'rostros_coinciden': rostros_coinciden,
                'similitud': similitud,
                'confianza': confianza,
                'rostro_detectado_fuente': source_face.get('Confidence', 0) > 0,
                'rostro_detectado_objetivo': len(face_matches) > 0 or len(unmatched_faces) > 0,
                'numero_rostros_fuente': 1 if source_face else 0,
                'numero_rostros_objetivo': len(face_matches) + len(unmatched_faces),
                'respuesta_completa': response,
                'mensaje_error': None
            }
            
            logger.info(f"Comparación exitosa: Similitud={similitud}%, Coinciden={rostros_coinciden}")
            return resultado
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            logger.error(f"Error de Rekognition: {error_code} - {error_message}")
            
            # Mensajes de error específicos
            mensaje_usuario = self._traducir_error_rekognition(error_code, error_message)
            
            return {
                'exito': False,
                'rostros_coinciden': False,
                'similitud': Decimal('0.0'),
                'confianza': Decimal('0.0'),
                'rostro_detectado_fuente': False,
                'rostro_detectado_objetivo': False,
                'numero_rostros_fuente': 0,
                'numero_rostros_objetivo': 0,
                'respuesta_completa': None,
                'mensaje_error': mensaje_usuario
            }
            
        except Exception as e:
            logger.error(f"Error inesperado en comparación: {str(e)}")
            return {
                'exito': False,
                'rostros_coinciden': False,
                'similitud': Decimal('0.0'),
                'confianza': Decimal('0.0'),
                'rostro_detectado_fuente': False,
                'rostro_detectado_objetivo': False,
                'numero_rostros_fuente': 0,
                'numero_rostros_objetivo': 0,
                'respuesta_completa': None,
                'mensaje_error': f'Error interno: {str(e)}'
            }
    
    def detectar_rostro_individual(self, imagen_path):
        """
        Detecta rostros en una sola imagen
        Útil para validación previa antes de comparar
        
        Args:
            imagen_path (str): Ruta en S3 de la imagen
        
        Returns:
            dict: Información de detección
        """
        try:
            response = self.client.detect_faces(
                Image={
                    'S3Object': {
                        'Bucket': self.s3_bucket,
                        'Name': imagen_path
                    }
                },
                Attributes=['DEFAULT']
            )
            
            face_details = response.get('FaceDetails', [])
            
            return {
                'exito': True,
                'rostros_detectados': len(face_details),
                'detalles': face_details,
                'mensaje_error': None
            }
            
        except ClientError as e:
            error_message = e.response['Error']['Message']
            logger.error(f"Error al detectar rostro: {error_message}")
            
            return {
                'exito': False,
                'rostros_detectados': 0,
                'detalles': [],
                'mensaje_error': error_message
            }
    
    def _traducir_error_rekognition(self, codigo, mensaje_original):
        """
        Traduce errores técnicos de Rekognition a mensajes amigables en español
        """
        errores_comunes = {
            'InvalidParameterException': 'Los parámetros de la imagen son inválidos. Verifica el formato.',
            'ImageTooLargeException': 'La imagen es demasiado grande. Tamaño máximo: 5MB.',
            'InvalidImageFormatException': 'Formato de imagen no soportado. Usa JPEG o PNG.',
            'InvalidS3ObjectException': 'No se pudo acceder a la imagen en S3. Verifica la ruta.',
            'AccessDeniedException': 'Acceso denegado a Rekognition. Verifica permisos IAM.',
            'ThrottlingException': 'Demasiadas solicitudes. Intenta de nuevo en unos segundos.',
            'ProvisionedThroughputExceededException': 'Límite de tasa excedido. Intenta más tarde.',
            'InvalidImageQualityException': 'La calidad de la imagen es muy baja.',
        }
        
        return errores_comunes.get(codigo, f'Error: {mensaje_original}')

# Instancia global del servicio
rekognition_service = RekognitionService()
```

### 5.3 Crear Vista para Verificación

#### Archivo: `usuarios/views.py` (AGREGAR)

```python
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from .models import Usuario, VerificacionIdentidad
from .services.rekognition_service import rekognition_service
import logging

logger = logging.getLogger(__name__)

@csrf_exempt
@api_view(['POST'])
def verificar_identidad_facial(request):
    """
    Endpoint para verificar la identidad de un usuario comparando
    su identificación oficial con un selfie usando AWS Rekognition
    
    Método: POST
    Datos esperados (multipart/form-data):
        - usuario_id: ID del usuario
        - imagen_identificacion: Archivo de imagen de ID oficial
        - imagen_selfie: Archivo de imagen selfie
    
    Respuesta:
        {
            "exito": true/false,
            "verificado": true/false,
            "similitud": 95.5,
            "mensaje": "Verificación exitosa",
            "detalles": {...}
        }
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        # Obtener datos del request
        usuario_id = request.POST.get('usuario_id')
        imagen_id = request.FILES.get('imagen_identificacion')
        imagen_selfie = request.FILES.get('imagen_selfie')
        
        # Validaciones básicas
        if not usuario_id:
            return JsonResponse({
                'exito': False,
                'mensaje': 'Se requiere el ID del usuario'
            }, status=400)
        
        if not imagen_id or not imagen_selfie:
            return JsonResponse({
                'exito': False,
                'mensaje': 'Se requieren ambas imágenes: identificación y selfie'
            }, status=400)
        
        # Validar que el usuario existe
        try:
            usuario = Usuario.objects.get(id=usuario_id)
        except Usuario.DoesNotExist:
            return JsonResponse({
                'exito': False,
                'mensaje': 'Usuario no encontrado'
            }, status=404)
        
        # Validar que no exista una verificación previa exitosa
        verificacion_existente = VerificacionIdentidad.objects.filter(
            usuario=usuario,
            estado='verificado'
        ).first()
        
        if verificacion_existente:
            return JsonResponse({
                'exito': True,
                'verificado': True,
                'mensaje': 'El usuario ya está verificado',
                'fecha_verificacion': verificacion_existente.fecha_verificacion.isoformat()
            }, status=200)
        
        # Validar formato de imágenes
        formatos_permitidos = ['image/jpeg', 'image/jpg', 'image/png']
        if imagen_id.content_type not in formatos_permitidos:
            return JsonResponse({
                'exito': False,
                'mensaje': f'Formato de identificación no válido. Usa: JPEG o PNG'
            }, status=400)
        
        if imagen_selfie.content_type not in formatos_permitidos:
            return JsonResponse({
                'exito': False,
                'mensaje': f'Formato de selfie no válido. Usa: JPEG o PNG'
            }, status=400)
        
        # Validar tamaño de imágenes (máximo 5MB)
        max_size = 5 * 1024 * 1024  # 5MB
        if imagen_id.size > max_size:
            return JsonResponse({
                'exito': False,
                'mensaje': 'La imagen de identificación excede el tamaño máximo (5MB)'
            }, status=400)
        
        if imagen_selfie.size > max_size:
            return JsonResponse({
                'exito': False,
                'mensaje': 'El selfie excede el tamaño máximo (5MB)'
            }, status=400)
        
        # Crear o actualizar registro de verificación
        with transaction.atomic():
            verificacion, created = VerificacionIdentidad.objects.get_or_create(
                usuario=usuario,
                defaults={
                    'estado': 'pendiente'
                }
            )
            
            # Guardar imágenes en S3 (Django lo hace automáticamente con S3Boto3Storage)
            verificacion.imagen_identificacion = imagen_id
            verificacion.imagen_selfie = imagen_selfie
            verificacion.save()
            
            # Obtener rutas de S3
            ruta_id = verificacion.imagen_identificacion.name
            ruta_selfie = verificacion.imagen_selfie.name
            
            logger.info(f"Imágenes guardadas - ID: {ruta_id}, Selfie: {ruta_selfie}")
        
        # Comparar rostros con Rekognition
        resultado_comparacion = rekognition_service.comparar_rostros(
            imagen_fuente_path=ruta_id,
            imagen_objetivo_path=ruta_selfie,
            umbral_similitud=90  # Umbral mínimo del 90%
        )
        
        # Actualizar registro con resultados
        with transaction.atomic():
            verificacion.similitud_facial = resultado_comparacion['similitud']
            verificacion.confianza_rekognition = resultado_comparacion['confianza']
            verificacion.rostro_detectado_id = resultado_comparacion['rostro_detectado_fuente']
            verificacion.rostro_detectado_selfie = resultado_comparacion['rostro_detectado_objetivo']
            verificacion.respuesta_rekognition = resultado_comparacion.get('respuesta_completa')
            
            # Determinar estado de verificación
            if not resultado_comparacion['exito']:
                verificacion.estado = 'error'
                verificacion.mensaje_error = resultado_comparacion['mensaje_error']
            elif resultado_comparacion['rostros_coinciden'] and resultado_comparacion['similitud'] >= 90:
                verificacion.estado = 'verificado'
                # Actualizar usuario
                usuario.identidad_verificada = True
                usuario.fecha_verificacion_identidad = timezone.now()
                usuario.save()
            else:
                verificacion.estado = 'rechazado'
                verificacion.mensaje_error = f'Similitud insuficiente: {resultado_comparacion["similitud"]}%'
                # Si está cerca del umbral, marcar para revisión manual
                if resultado_comparacion['similitud'] >= 80:
                    verificacion.requiere_revision_manual = True
            
            verificacion.save()
        
        # Preparar respuesta
        respuesta = {
            'exito': resultado_comparacion['exito'],
            'verificado': verificacion.estado == 'verificado',
            'estado': verificacion.estado,
            'similitud': float(verificacion.similitud_facial) if verificacion.similitud_facial else 0,
            'confianza': float(verificacion.confianza_rekognition) if verificacion.confianza_rekognition else 0,
            'detalles': {
                'rostro_detectado_id': verificacion.rostro_detectado_id,
                'rostro_detectado_selfie': verificacion.rostro_detectado_selfie,
                'requiere_revision_manual': verificacion.requiere_revision_manual
            }
        }
        
        if verificacion.estado == 'verificado':
            respuesta['mensaje'] = 'Identidad verificada exitosamente'
        elif verificacion.estado == 'rechazado':
            respuesta['mensaje'] = 'Las imágenes no coinciden suficientemente'
        elif verificacion.estado == 'error':
            respuesta['mensaje'] = f'Error en verificación: {verificacion.mensaje_error}'
        
        if verificacion.requiere_revision_manual:
            respuesta['mensaje'] += ' (En revisión manual)'
        
        status_code = 200 if resultado_comparacion['exito'] else 500
        return JsonResponse(respuesta, status=status_code)
        
    except Exception as e:
        logger.error(f"Error en verificación facial: {str(e)}", exc_info=True)
        return JsonResponse({
            'exito': False,
            'mensaje': f'Error interno del servidor: {str(e)}'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def obtener_estado_verificacion(request, usuario_id):
    """
    Obtiene el estado de verificación de un usuario
    
    Método: GET
    URL: /api/verificacion-identidad/estado/<usuario_id>/
    
    Respuesta:
        {
            "verificado": true/false,
            "estado": "verificado|pendiente|rechazado|error",
            "similitud": 95.5,
            "fecha_verificacion": "2026-03-05T10:30:00Z"
        }
    """
    try:
        usuario = Usuario.objects.get(id=usuario_id)
        
        try:
            verificacion = VerificacionIdentidad.objects.get(usuario=usuario)
            return JsonResponse({
                'verificado': usuario.identidad_verificada,
                'estado': verificacion.estado,
                'similitud': float(verificacion.similitud_facial) if verificacion.similitud_facial else None,
                'fecha_verificacion': verificacion.fecha_verificacion.isoformat(),
                'requiere_revision_manual': verificacion.requiere_revision_manual
            })
        except VerificacionIdentidad.DoesNotExist:
            return JsonResponse({
                'verificado': False,
                'estado': 'sin_verificar',
                'mensaje': 'El usuario no ha iniciado el proceso de verificación'
            })
            
    except Usuario.DoesNotExist:
        return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
```

### 5.4 Configurar URLs

#### Archivo: `usuarios/urls.py` (AGREGAR)

```python
from django.urls import path
from . import views

urlpatterns = [
    # ... URLs existentes ...
    
    # Verificación de identidad facial
    path('api/verificar-identidad/', views.verificar_identidad_facial, name='verificar_identidad_facial'),
    path('api/verificacion-identidad/estado/<int:usuario_id>/', views.obtener_estado_verificacion, name='estado_verificacion'),
]
```

### 5.5 Actualizar Settings

#### Archivo: `fimeride_backend/settings.py` (AGREGAR)

```python
# Configuración de Amazon Rekognition
REKOGNITION_SIMILARITY_THRESHOLD = 90  # Umbral mínimo de similitud (0-100)
REKOGNITION_MIN_CONFIDENCE = 80  # Confianza mínima para detección de rostros

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'rekognition.log',
        },
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'usuarios.services.rekognition_service': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
```

---

## 6. Implementación Paso a Paso

### Fase 1: Preparación del Entorno (Día 1)

#### Paso 1.1: Actualizar Dependencias
```bash
# En tu entorno virtual
pip install --upgrade boto3 botocore
pip freeze > requirements.txt
```

#### Paso 1.2: Configurar Permisos AWS
- [ ] Crear política IAM (ver sección 4.1)
- [ ] Adjuntar política al usuario IAM
- [ ] Verificar acceso a Rekognition

```bash
# Probar conexión
python manage.py shell
```

```python
import boto3
from django.conf import settings

client = boto3.client(
    'rekognition',
    region_name=settings.AWS_S3_REGION_NAME,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
)

# Esto debe ejecutarse sin errores
print(client.describe_projects())
```

### Fase 2: Modificaciones de Base de Datos (Día 1-2)

#### Paso 2.1: Crear Directorio de Servicios
```bash
mkdir -p usuarios/services
touch usuarios/services/__init__.py
touch usuarios/services/rekognition_service.py
```

#### Paso 2.2: Agregar Modelo VerificacionIdentidad
1. Editar `usuarios/models.py`
2. Agregar el código del modelo (ver sección 5.1)

#### Paso 2.3: Crear Migraciones
```bash
python manage.py makemigrations usuarios
python manage.py migrate
```

#### Paso 2.4: Registrar en Admin (Opcional)
```python
# usuarios/admin.py
from django.contrib import admin
from .models import VerificacionIdentidad

@admin.register(VerificacionIdentidad)
class VerificacionIdentidadAdmin(admin.ModelAdmin):
    list_display = ['usuario', 'estado', 'similitud_facial', 'fecha_verificacion']
    list_filter = ['estado', 'requiere_revision_manual']
    search_fields = ['usuario__matricula', 'usuario__nombre_completo']
    readonly_fields = ['fecha_verificacion', 'fecha_actualizacion']
```

### Fase 3: Implementar Servicio de Rekognition (Día 2-3)

#### Paso 3.1: Crear rekognition_service.py
- Copiar código de la sección 5.2
- Guardar en `usuarios/services/rekognition_service.py`

#### Paso 3.2: Probar Servicio Individualmente
```python
# python manage.py shell
from usuarios.services.rekognition_service import rekognition_service

# Subir dos imágenes de prueba a S3 manualmente primero
resultado = rekognition_service.comparar_rostros(
    'verificacion-identidad/test/id.jpg',
    'verificacion-identidad/test/selfie.jpg'
)

print(resultado)
```

### Fase 4: Crear Endpoints (Día 3-4)

#### Paso 4.1: Agregar Vistas
- Copiar código de la sección 5.3
- Agregar a `usuarios/views.py`

#### Paso 4.2: Configurar URLs
- Actualizar `usuarios/urls.py` (ver sección 5.4)

#### Paso 4.3: Probar con Postman/cURL

**Prueba 1: Verificar identidad**
```bash
curl -X POST http://localhost:8000/api/verificar-identidad/ \
  -F "usuario_id=1" \
  -F "imagen_identificacion=@/path/to/id.jpg" \
  -F "imagen_selfie=@/path/to/selfie.jpg"
```

**Respuesta esperada:**
```json
{
  "exito": true,
  "verificado": true,
  "estado": "verificado",
  "similitud": 95.5,
  "confianza": 99.8,
  "mensaje": "Identidad verificada exitosamente",
  "detalles": {
    "rostro_detectado_id": true,
    "rostro_detectado_selfie": true,
    "requiere_revision_manual": false
  }
}
```

**Prueba 2: Consultar estado**
```bash
curl -X GET http://localhost:8000/api/verificacion-identidad/estado/1/
```

### Fase 5: Pruebas y Validación (Día 4-5)

#### Paso 5.1: Casos de Prueba

| **Caso** | **Descripción** | **Resultado Esperado** |
|----------|-----------------|------------------------|
| Caso 1 | Misma persona en ambas fotos | Verificado (≥90%) |
| Caso 2 | Personas diferentes | Rechazado (<90%) |
| Caso 3 | Imagen borrosa/baja calidad | Error o Rechazado |
| Caso 4 | Sin rostro en ID | Error: "No se detectó rostro" |
| Caso 5 | Sin rostro en selfie | Error: "No se detectó rostro" |
| Caso 6 | Múltiples rostros | Procesa el rostro principal |
| Caso 7 | Formato inválido (BMP, TIFF) | Error: Formato no soportado |
| Caso 8 | Archivo muy grande (>5MB) | Error: Tamaño excedido |

#### Paso 5.2: Script de Pruebas Automatizadas

```python
# test_verificacion.py
import requests

BASE_URL = "http://localhost:8000"

def test_verificacion_exitosa():
    """Prueba con imágenes de la misma persona"""
    url = f"{BASE_URL}/api/verificar-identidad/"
    files = {
        'imagen_identificacion': open('tests/imagenes/id_juan.jpg', 'rb'),
        'imagen_selfie': open('tests/imagenes/selfie_juan.jpg', 'rb')
    }
    data = {'usuario_id': 1}
    
    response = requests.post(url, files=files, data=data)
    assert response.status_code == 200
    assert response.json()['verificado'] == True
    assert response.json()['similitud'] >= 90

def test_verificacion_rechazada():
    """Prueba con imágenes de personas diferentes"""
    url = f"{BASE_URL}/api/verificar-identidad/"
    files = {
        'imagen_identificacion': open('tests/imagenes/id_juan.jpg', 'rb'),
        'imagen_selfie': open('tests/imagenes/selfie_maria.jpg', 'rb')
    }
    data = {'usuario_id': 2}
    
    response = requests.post(url, files=files, data=data)
    assert response.status_code == 200
    assert response.json()['verificado'] == False

# Ejecutar pruebas
if __name__ == '__main__':
    test_verificacion_exitosa()
    test_verificacion_rechazada()
    print("Todas las pruebas pasaron")
```

### Fase 6: Integración con Frontend (Día 5-6)

#### Paso 6.1: Flujo en la App Móvil

```javascript
// Ejemplo de integración (React Native / Flutter)

// 1. Capturar selfie
const capturarSelfie = async () => {
  const result = await ImagePicker.launchCameraAsync({
    mediaTypes: ImagePicker.MediaTypeOptions.Images,
    quality: 0.8,
    allowsEditing: true,
    aspect: [3, 4]
  });
  
  if (!result.cancelled) {
    setSelfie(result.uri);
  }
};

// 2. Seleccionar foto de ID
const seleccionarID = async () => {
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ImagePicker.MediaTypeOptions.Images,
    quality: 0.8
  });
  
  if (!result.cancelled) {
    setFotoID(result.uri);
  }
};

// 3. Enviar para verificación
const verificarIdentidad = async () => {
  const formData = new FormData();
  formData.append('usuario_id', usuarioId);
  formData.append('imagen_identificacion', {
    uri: fotoID,
    type: 'image/jpeg',
    name: 'identificacion.jpg'
  });
  formData.append('imagen_selfie', {
    uri: selfie,
    type: 'image/jpeg',
    name: 'selfie.jpg'
  });
  
  try {
    const response = await fetch(
      'https://fimeride.onrender.com/api/verificar-identidad/',
      {
        method: 'POST',
        body: formData,
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      }
    );
    
    const data = await response.json();
    
    if (data.verificado) {
      Alert.alert('Verificación Exitosa', 
        'Tu identidad ha sido verificada correctamente');
      // Navegar a la siguiente pantalla
    } else {
      Alert.alert('Verificación Fallida', 
        data.mensaje);
    }
  } catch (error) {
    Alert.alert('Error', 'No se pudo verificar la identidad');
  }
};
```

---

## 7. Seguridad y Privacidad

### 7.1 Protección de Datos Personales

#### Datos Sensibles
- Imágenes de identificaciones oficiales
- Fotografías de rostros (biométricos)
- Resultados de verificación

#### Medidas de Seguridad

**1. Cifrado en Tránsito**
```python
# settings.py
SECURE_SSL_REDIRECT = True  # Forzar HTTPS en producción
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

**2. Cifrado en Reposo (S3)**
```python
# Configurar cifrado en bucket S3
AWS_S3_OBJECT_PARAMETERS = {
    'CacheControl': 'max-age=86400',
    'ServerSideEncryption': 'AES256'  # AGREGAR
}
```

**3. Control de Acceso**
```python
# Política de acceso restrictiva
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Deny",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::fimeridearchivos/verificacion-identidad/*",
            "Condition": {
                "StringNotEquals": {
                    "aws:PrincipalAccount": "TU_ACCOUNT_ID"
                }
            }
        }
    ]
}
```

**4. Retención de Datos**
```python
# Configurar política de eliminación automática
# Después de 90 días, eliminar imágenes de verificación

from datetime import timedelta
from django.utils import timezone

def limpiar_imagenes_antiguas():
    """
    Tarea programada para eliminar imágenes de verificación antiguas
    """
    fecha_limite = timezone.now() - timedelta(days=90)
    verificaciones_antiguas = VerificacionIdentidad.objects.filter(
        fecha_verificacion__lt=fecha_limite
    )
    
    for verificacion in verificaciones_antiguas:
        # Eliminar de S3
        verificacion.imagen_identificacion.delete(save=False)
        verificacion.imagen_selfie.delete(save=False)
        # Mantener registro pero sin imágenes
        verificacion.save()
```

**5. Auditoría**
```python
# Registrar todos los intentos de verificación
class LogVerificacion(models.Model):
    verificacion = models.ForeignKey(VerificacionIdentidad, on_delete=models.CASCADE)
    accion = models.CharField(max_length=50)
    usuario_accion = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True)
    ip_address = models.GenericIPAddressField()
    timestamp = models.DateTimeField(auto_now_add=True)
    detalles = models.JSONField()
```

### 7.2 Cumplimiento Legal

#### GDPR / LFPDPPP (Ley Federal de Protección de Datos Personales)

**Consentimiento Informado**
```python
class ConsentimientoVerificacion(models.Model):
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    acepta_terminos = models.BooleanField(default=False)
    acepta_uso_biometricos = models.BooleanField(default=False)
    fecha_aceptacion = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField()
    texto_consentimiento = models.TextField()  # Guardar versión exacta aceptada
```

**Aviso de Privacidad**
Debe informar:
- Qué datos se recopilan (imágenes faciales)
- Para qué se usan (verificación de identidad)
- Cómo se protegen (cifrado, AWS)
- Quién tiene acceso (solo sistema automatizado)
- Cuánto tiempo se conservan (90 días)
- Derechos ARCO (Acceso, Rectificación, Cancelación, Oposición)

### 7.3 Prevención de Fraudes

**1. Detección de Fotos de Fotos**
```python
# Usar DetectModerationLabels para detectar pantallas/fotos
def detectar_foto_de_foto(imagen_path):
    response = client.detect_moderation_labels(
        Image={'S3Object': {'Bucket': bucket, 'Name': imagen_path}}
    )
    # Buscar labels como "Screen", "Monitor", etc.
```

**2. Limitar Intentos**
```python
class LimiteIntentos(models.Model):
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    intentos_fallidos = models.IntegerField(default=0)
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)
    
    def puede_intentar(self):
        if self.bloqueado_hasta and timezone.now() < self.bloqueado_hasta:
            return False
        return self.intentos_fallidos < 3
    
    def registrar_fallo(self):
        self.intentos_fallidos += 1
        if self.intentos_fallidos >= 3:
            self.bloqueado_hasta = timezone.now() + timedelta(hours=24)
        self.save()
```

**3. Validación de Metadatos EXIF**
```python
from PIL import Image
from PIL.ExifTags import TAGS

def validar_imagen_original(imagen_file):
    """Verifica que la imagen tenga metadatos EXIF de cámara"""
    try:
        img = Image.open(imagen_file)
        exif_data = img._getexif()
        
        if exif_data:
            # Buscar datos de cámara
            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag in ['Make', 'Model', 'DateTime']:
                    return True
        return False  # No tiene EXIF (sospechoso)
    except:
        return False
```

---

## 8. Pruebas y Validación

### 8.1 Conjunto de Datos de Prueba

#### Crear Dataset
```
tests/
├── imagenes/
│   ├── validas/
│   │   ├── persona1_id.jpg
│   │   ├── persona1_selfie.jpg
│   │   ├── persona2_id.jpg
│   │   └── persona2_selfie.jpg
│   ├── invalidas/
│   │   ├── baja_calidad.jpg
│   │   ├── sin_rostro.jpg
│   │   ├── multiple_rostros.jpg
│   │   └── foto_de_foto.jpg
│   └── fraudulentas/
│       ├── persona1_id.jpg
│       └── persona2_selfie.jpg  # ← Diferentes personas
```

### 8.2 Pruebas Funcionales

#### Test 1: Verificación Exitosa
```python
def test_verificacion_misma_persona():
    # Cargar usuario
    usuario = Usuario.objects.create(
        matricula='1234567',
        nombre_completo='Juan Pérez',
        correo_universitario='juan@ejemplo.com'
    )
    
    # Simular carga de imágenes
    with open('tests/imagenes/validas/persona1_id.jpg', 'rb') as id_file:
        with open('tests/imagenes/validas/persona1_selfie.jpg', 'rb') as selfie_file:
            response = client.post('/api/verificar-identidad/', {
                'usuario_id': usuario.id,
                'imagen_identificacion': id_file,
                'imagen_selfie': selfie_file
            })
    
    assert response.status_code == 200
    data = response.json()
    assert data['verificado'] == True
    assert data['similitud'] >= 90
    
    # Verificar que se actualizó el usuario
    usuario.refresh_from_db()
    assert usuario.identidad_verificada == True
```

#### Test 2: Verificación Rechazada
```python
def test_verificacion_personas_diferentes():
    usuario = Usuario.objects.create(...)
    
    with open('tests/imagenes/fraudulentas/persona1_id.jpg', 'rb') as id_file:
        with open('tests/imagenes/fraudulentas/persona2_selfie.jpg', 'rb') as selfie_file:
            response = client.post('/api/verificar-identidad/', {
                'usuario_id': usuario.id,
                'imagen_identificacion': id_file,
                'imagen_selfie': selfie_file
            })
    
    data = response.json()
    assert data['verificado'] == False
    assert data['estado'] == 'rechazado'
```

### 8.3 Pruebas de Carga

```python
# locustfile.py (para Locust)
from locust import HttpUser, task, between

class UsuarioVerificacion(HttpUser):
    wait_time = between(1, 3)
    
    @task
    def verificar_identidad(self):
        files = {
            'imagen_identificacion': open('test_id.jpg', 'rb'),
            'imagen_selfie': open('test_selfie.jpg', 'rb')
        }
        self.client.post('/api/verificar-identidad/', 
                        data={'usuario_id': 1}, 
                        files=files)
```

```bash
# Ejecutar prueba de carga
locust -f locustfile.py --host=http://localhost:8000
# Simular 100 usuarios concurrentes
```

### 8.4 Métricas de Calidad

| **Métrica** | **Objetivo** | **Descripción** |
|-------------|--------------|-----------------|
| True Positive Rate (TPR) | ≥ 95% | Detecta correctamente misma persona |
| False Positive Rate (FPR) | ≤ 2% | Rechaza incorrectamente misma persona |
| True Negative Rate (TNR) | ≥ 98% | Rechaza correctamente personas diferentes |
| False Negative Rate (FNR) | ≤ 5% | Acepta incorrectamente personas diferentes |
| Tiempo de Respuesta | < 3 seg | Tiempo total de verificación |

---

## 9. Costos Estimados

### 9.1 Precios de AWS Rekognition (Región us-east-2)

#### CompareFaces API
| **Volumen Mensual** | **Precio por Imagen** | **Ejemplo 1,000 usuarios** |
|---------------------|-----------------------|----------------------------|
| Primeras 1M imágenes | $0.001 por imagen | $2.00 |
| Siguientes 9M | $0.0008 por imagen | - |
| Más de 10M | $0.0006 por imagen | - |

**Nota**: Cada verificación procesa 2 imágenes = $0.002 por usuario

#### Cálculo de Costos

**Escenario 1: Universidad Pequeña**
- 5,000 nuevos usuarios/año
- 5,000 × 2 imágenes = 10,000 imágenes
- **Costo anual**: $10.00 USD

**Escenario 2: Universidad Mediana**
- 20,000 nuevos usuarios/año
- 20,000 × 2 = 40,000 imágenes
- **Costo anual**: $40.00 USD

**Escenario 3: Universidad Grande**
- 100,000 nuevos usuarios/año
- 100,000 × 2 = 200,000 imágenes
- **Costo anual**: $200.00 USD

### 9.2 Costos de S3

**Almacenamiento**
- Promedio 500 KB por imagen
- 2 imágenes por usuario = 1 MB
- 10,000 usuarios = 10 GB
- **Costo**: $0.23/mes × 10 GB = $2.30/mes

**Transferencia de Datos**
- GET requests (descarga): $0.0004 por 1,000 requests
- PUT requests (carga): $0.005 por 1,000 requests
- **Costo estimado**: < $1/mes para 10,000 usuarios

### 9.3 Costo Total Estimado

| **Componente** | **Costo Mensual** | **Costo Anual** |
|----------------|-------------------|-----------------|
| Rekognition (10k usuarios/año) | $0.83 | $10.00 |
| S3 Storage | $2.30 | $27.60 |
| S3 Requests | $0.50 | $6.00 |
| **TOTAL** | **$3.63** | **$43.60** |

**Muy económico** para el valor agregado en seguridad

### 9.4 Optimización de Costos

**1. Limitar reintentos**
- Máximo 3 intentos por usuario
- Evitar verificaciones duplicadas

**2. Limpiar imágenes antiguas**
- Eliminar después de 90 días
- Reducir costos de almacenamiento S3

**3. Usar calidad óptima**
- Comprimir imágenes a 80% JPEG
- Reducir a 1920x1080 máximo
- Ahorra transferencia de datos

---

## 10. Manejo de Errores

### 10.1 Errores Comunes y Soluciones

| **Error** | **Causa** | **Solución** |
|-----------|-----------|--------------|
| `InvalidImageFormatException` | Formato no soportado | Validar JPEG/PNG antes de enviar |
| `ImageTooLargeException` | Imagen > 5MB | Comprimir imagen en cliente |
| `InvalidParameterException` | Rostro no detectado | Mostrar guía de cómo tomar foto |
| `AccessDeniedException` | Permisos IAM faltantes | Verificar política IAM |
| `ThrottlingException` | Demasiadas solicitudes | Implementar rate limiting |
| `ProvisionedThroughputExceededException` | Límite de cuota | Solicitar aumento de cuota |

### 10.2 Mensajes de Error Amigables

```python
MENSAJES_ERROR = {
    'no_rostro_id': {
        'titulo': 'No se detectó rostro en la identificación',
        'mensaje': 'Asegúrate de que tu foto de identificación sea clara y muestre tu rostro completo.',
        'accion': 'Intenta de nuevo con mejor iluminación'
    },
    'no_rostro_selfie': {
        'titulo': 'No se detectó rostro en el selfie',
        'mensaje': 'Toma un selfie claro con buena iluminación, mirando de frente a la cámara.',
        'accion': 'Tomar nuevo selfie'
    },
    'baja_similitud': {
        'titulo': 'Las imágenes no coinciden',
        'mensaje': 'Las fotos parecen ser de personas diferentes. Verifica que estés usando tu identificación correcta.',
        'accion': 'Verificar documentos o contactar soporte'
    },
    'calidad_baja': {
        'titulo': 'Calidad de imagen insuficiente',
        'mensaje': 'Las fotos están borrosas o muy oscuras.',
        'accion': 'Tomar nuevas fotos con mejor iluminación'
    },
    'error_servidor': {
        'titulo': 'Error temporal del servidor',
        'mensaje': 'Hubo un problema al procesar tu verificación. Por favor intenta de nuevo.',
        'accion': 'Reintentar en unos minutos'
    }
}
```

### 10.3 Sistema de Fallback

```python
def verificar_con_fallback(usuario, imagen_id, imagen_selfie):
    """
    Sistema de verificación con fallback a revisión manual
    """
    try:
        # Intentar verificación automática
        resultado = rekognition_service.comparar_rostros(...)
        
        if resultado['exito']:
            if resultado['similitud'] >= 90:
                return 'verificado'
            elif resultado['similitud'] >= 80:
                # Zona gris: requiere revisión manual
                marcar_para_revision_manual(usuario)
                return 'revision_manual'
            else:
                return 'rechazado'
        else:
            # Error en Rekognition: fallback a revisión manual
            marcar_para_revision_manual(usuario)
            return 'revision_manual'
            
    except Exception as e:
        logger.error(f"Error crítico: {e}")
        marcar_para_revision_manual(usuario)
        return 'revision_manual'
```

---

## 11. Mantenimiento y Monitoreo

### 11.1 Dashboard de Monitoreo

**Métricas Clave a Rastrear:**

```python
# Crear modelo para métricas
class MetricaVerificacion(models.Model):
    fecha = models.DateField()
    total_intentos = models.IntegerField(default=0)
    verificaciones_exitosas = models.IntegerField(default=0)
    verificaciones_rechazadas = models.IntegerField(default=0)
    errores = models.IntegerField(default=0)
    tasa_exito = models.DecimalField(max_digits=5, decimal_places=2)
    tiempo_promedio_ms = models.IntegerField()  # Milisegundos
    
    class Meta:
        unique_together = ['fecha']
```

**Vista de Dashboard:**
```python
@api_view(['GET'])
def dashboard_verificaciones(request):
    """Estadísticas de verificaciones"""
    hoy = timezone.now().date()
    ultimos_30_dias = hoy - timedelta(days=30)
    
    stats = VerificacionIdentidad.objects.filter(
        fecha_verificacion__gte=ultimos_30_dias
    ).aggregate(
        total=Count('id'),
        verificados=Count('id', filter=Q(estado='verificado')),
        rechazados=Count('id', filter=Q(estado='rechazado')),
        errores=Count('id', filter=Q(estado='error')),
        similitud_promedio=Avg('similitud_facial')
    )
    
    return JsonResponse({
        'periodo': '30 días',
        'total_intentos': stats['total'],
        'verificados': stats['verificados'],
        'rechazados': stats['rechazados'],
        'errores': stats['errores'],
        'tasa_exito': round((stats['verificados'] / stats['total'] * 100), 2) if stats['total'] > 0 else 0,
        'similitud_promedio': round(stats['similitud_promedio'], 2) if stats['similitud_promedio'] else 0
    })
```

### 11.2 Alertas Automáticas

```python
# Configurar alertas por email
from django.core.mail import send_mail

def verificar_salud_sistema():
    """Enviar alerta si hay problemas"""
    hoy = timezone.now().date()
    
    # Calcular tasa de error del día
    stats = VerificacionIdentidad.objects.filter(
        fecha_verificacion__date=hoy
    ).aggregate(
        total=Count('id'),
        errores=Count('id', filter=Q(estado='error'))
    )
    
    if stats['total'] > 10:  # Solo si hay suficiente volumen
        tasa_error = (stats['errores'] / stats['total']) * 100
        
        if tasa_error > 10:  # Más del 10% de errores
            send_mail(
                subject='ALERTA: Alta tasa de errores en verificación facial',
                message=f'Tasa de error: {tasa_error}% ({stats["errores"]}/{stats["total"]})',
                from_email='sistema@fimeride.com',
                recipient_list=['admin@fimeride.com'],
                fail_silently=False
            )
```

### 11.3 Logs y Auditoría

```python
# Configurar logging detallado
import logging

logger = logging.getLogger('verificacion_facial')

def log_verificacion(verificacion, accion, detalles=None):
    """Registrar todas las acciones relacionadas con verificaciones"""
    logger.info(
        f"[{verificacion.usuario.matricula}] {accion} | "
        f"Estado: {verificacion.estado} | "
        f"Similitud: {verificacion.similitud_facial}% | "
        f"Detalles: {detalles}"
    )
```

### 11.4 Tareas Programadas (Celery)

```python
# tasks.py
from celery import shared_task
from datetime import timedelta
from django.utils import timezone

@shared_task
def limpiar_verificaciones_antiguas():
    """
    Ejecutar diariamente: Eliminar imágenes de verificaciones > 90 días
    """
    fecha_limite = timezone.now() - timedelta(days=90)
    verificaciones = VerificacionIdentidad.objects.filter(
        fecha_verificacion__lt=fecha_limite
    ).exclude(
        imagen_identificacion=''
    )
    
    count = 0
    for v in verificaciones:
        try:
            v.imagen_identificacion.delete(save=False)
            v.imagen_selfie.delete(save=False)
            v.save()
            count += 1
        except Exception as e:
            logger.error(f"Error al limpiar verificación {v.id}: {e}")
    
    logger.info(f"Limpieza completada: {count} verificaciones limpiadas")

@shared_task
def generar_reporte_diario():
    """Generar y enviar reporte diario de verificaciones"""
    # Implementar lógica de reporte
    pass
```

**Configurar en Celery Beat:**
```python
# settings.py
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'limpiar-verificaciones': {
        'task': 'usuarios.tasks.limpiar_verificaciones_antiguas',
        'schedule': crontab(hour=2, minute=0),  # 2:00 AM diario
    },
    'reporte-diario': {
        'task': 'usuarios.tasks.generar_reporte_diario',
        'schedule': crontab(hour=8, minute=0),  # 8:00 AM diario
    },
}
```

---

## 12. Checklist de Implementación

### Fase de Configuración

- [ ] Crear política IAM para Rekognition
- [ ] Adjuntar política al usuario AWS
- [ ] Verificar región compatible (us-east-2)
- [ ] Probar conexión a Rekognition
- [ ] Crear carpetas en S3

### Fase de Desarrollo

- [ ] Actualizar requirements.txt
- [ ] Crear modelo `VerificacionIdentidad`
- [ ] Crear servicio `rekognition_service.py`
- [ ] Implementar vista `verificar_identidad_facial`
- [ ] Configurar URLs
- [ ] Actualizar settings.py
- [ ] Ejecutar migraciones

### Fase de Pruebas

- [ ] Probar servicio Rekognition individualmente
- [ ] Probar endpoint con Postman
- [ ] Ejecutar casos de prueba funcionales
- [ ] Validar manejo de errores
- [ ] Probar con imágenes de diferentes calidades
- [ ] Verificar almacenamiento en S3

### Fase de Seguridad

- [ ] Configurar cifrado en S3
- [ ] Implementar consentimiento de usuario
- [ ] Configurar logging y auditoría
- [ ] Implementar límite de intentos
- [ ] Configurar política de retención

### Fase de Producción

- [ ] Configurar HTTPS (SSL)
- [ ] Implementar rate limiting
- [ ] Configurar alertas
- [ ] Configurar tareas programadas
- [ ] Crear dashboard de monitoreo
- [ ] Documentar API para frontend

---

## 13. Recursos Adicionales

### 13.1 Documentación Oficial

- **AWS Rekognition**: https://docs.aws.amazon.com/rekognition/
- **CompareFaces API**: https://docs.aws.amazon.com/rekognition/latest/dg/faces-comparefaces.html
- **Boto3 Rekognition**: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/rekognition.html
- **Django File Uploads**: https://docs.djangoproject.com/en/5.1/topics/http/file-uploads/

### 13.2 Mejores Prácticas

1. **Calidad de Imagen**
   - Resolución mínima: 640x480
   - Formato: JPEG (mejor compresión)
   - Iluminación uniforme
   - Rostro centrado

2. **Umbrales Recomendados**
   - Similitud ≥ 90%: Verificado automáticamente
   - Similitud 80-89%: Revisión manual
   - Similitud < 80%: Rechazado

3. **Experiencia de Usuario**
   - Mostrar guía visual al tomar selfie
   - Feedback en tiempo real
   - Mensajes de error claros
   - Permitir reintentos (máximo 3)

### 13.3 Contactos de Soporte

- **AWS Support**: https://console.aws.amazon.com/support/
- **Foro AWS Rekognition**: https://repost.aws/tags/rekognition
- **Comunidad Django**: https://forum.djangoproject.com/

---

## 14. Glosario de Términos

| **Término** | **Definición** |
|-------------|----------------|
| **CompareFaces** | API de Rekognition que compara dos rostros y retorna similitud |
| **Similarity Score** | Porcentaje de similitud entre dos rostros (0-100) |
| **Confidence** | Nivel de confianza de Rekognition en la detección |
| **BoundingBox** | Coordenadas del rectángulo que contiene el rostro |
| **Source Image** | Imagen de referencia (identificación) |
| **Target Image** | Imagen a comparar (selfie) |
| **Threshold** | Umbral mínimo de similitud para considerar coincidencia |
| **IAM Policy** | Política de permisos de AWS |
| **KYC** | Know Your Customer (Conoce a tu Cliente) |
| **EXIF** | Metadatos de imagen (cámara, fecha, ubicación) |

---

## 15. Próximos Pasos Recomendados

1. **Implementación Básica** (Semana 1-2)
   - Configurar AWS y permisos
   - Implementar modelo y servicio
   - Crear endpoint básico

2. **Mejoras de Seguridad** (Semana 3)
   - Implementar validaciones avanzadas
   - Configurar cifrado
   - Agregar auditoría

3. **Integración Frontend** (Semana 4)
   - Desarrollar UI de captura
   - Implementar guías visuales
   - Conectar con backend

4. **Optimización** (Semana 5-6)
   - Ajustar umbrales según datos reales
   - Implementar caché
   - Optimizar costos

5. **Monitoreo y Mantenimiento** (Continuo)
   - Dashboard de métricas
   - Alertas automáticas
   - Revisiones periódicas

---

## Contacto y Soporte

Para preguntas o asistencia adicional durante la implementación:

- **Email Técnico**: soporte-tecnico@fimeride.com
- **Slack**: #verificacion-facial
- **Issues**: GitHub Issues del proyecto

---

**Documento creado**: 5 de marzo de 2026  
**Versión**: 1.0  
**Autor**: Equipo de Desarrollo FimeRide  
**Última actualización**: 5 de marzo de 2026

---

## Conclusión

Este documento proporciona una guía completa para implementar verificación de identidad facial en FimeRide usando Amazon Rekognition. La solución es:

- **Segura**: Cifrado end-to-end y cumplimiento de privacidad
- **Económica**: ~$44/año para 10,000 usuarios
- **Escalable**: Soporta millones de verificaciones
- **Precisa**: >95% de precisión con Rekognition
- **Fácil de implementar**: Integración con Django en ~2 semanas

**Buena suerte con la implementación!**
