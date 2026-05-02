import io
import json
import logging
import math
import os
import uuid
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.http.multipartparser import MultiPartParser
from django.views.decorators.csrf import csrf_exempt
from .models import Asignacion, DocumentacionConductor, DocumentacionPasajero, Mensaje, Reporte, Solicitud, Usuario, UsuarioConductor, UsuarioPasajero
from django.db import transaction
from django.conf import settings
from django.utils.timezone import now, localtime, make_aware, is_naive
from django.contrib.auth import authenticate
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from rest_framework_simplejwt.authentication import JWTAuthentication
from PIL import Image
from .models import Viaje
from usuarios import models
from django.db.models import Q
from .rekognition_service import (
    RekognitionError,
    compare_faces_bytes,
    compare_faces_s3,
    verify_face_present,
)
from .barcode_service import extract_matricula_from_pdf


logger = logging.getLogger(__name__)


def _get_similarity_threshold():
    raw_value = os.getenv("FACE_SIMILARITY_THRESHOLD", "80")
    try:
        return float(raw_value)
    except ValueError:
        return 80.0


def _authenticate_jwt(request):
    authenticator = JWTAuthentication()
    try:
        result = authenticator.authenticate(request)
    except Exception:
        return None, JsonResponse({"error": "Token invalido"}, status=401)
    if result is None:
        return None, JsonResponse({"error": "Token requerido"}, status=401)
    user, _ = result
    return user, None


def _read_file_bytes(file_obj):
    data = file_obj.read()
    file_obj.seek(0)
    return data


def _normalize_profile_image(image_bytes):
    try:
        image = Image.open(io.BytesIO(image_bytes))
        if image.mode != "RGB":
            image = image.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()
    except Exception as exc:
        raise ValueError("Imagen invalida") from exc


def _truncate_text(value, limit=200):
    if not value:
        return ""
    return value[:limit]


def _inicio_y_destino(viaje):
    if viaje.direccion_inicio and viaje.direccion_destino:
        return viaje.direccion_inicio, viaje.direccion_destino
    if viaje.es_hacia_fime:
        return viaje.direccion, 'FIME'
    return 'FIME', viaje.direccion


def _datetime_salida(viaje):
    # Espera formato HH:mm en hora_salida, con fallback HH:mm:ss.
    raw_hora = viaje.hora_salida.strip()
    try:
        hora = datetime.strptime(raw_hora, '%H:%M').time()
    except ValueError:
        hora = datetime.strptime(raw_hora, '%H:%M:%S').time()
    dt = datetime.combine(viaje.fecha_viaje, hora)
    if is_naive(dt):
        dt = make_aware(dt)
    return dt


def _haversine_metros(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return None

    radio = 6371000
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radio * c


def _punto_antes_de_objetivo(origen_lat, origen_lng, destino_lat, destino_lng, metros_antes=200):
    distancia_total = _haversine_metros(origen_lat, origen_lng, destino_lat, destino_lng)
    if distancia_total is None:
        return destino_lat, destino_lng
    if distancia_total <= metros_antes:
        return origen_lat, origen_lng

    ratio = max((distancia_total - metros_antes) / distancia_total, 0)
    lat = origen_lat + (destino_lat - origen_lat) * ratio
    lng = origen_lng + (destino_lng - origen_lng) * ratio
    return lat, lng


def _estado_pasajero(asignacion):
    if asignacion.descenso_confirmado:
        return 'bajo_del_vehiculo'
    if asignacion.abordo_confirmado:
        return 'en_vehiculo'
    return 'pendiente_abordar'


def _cerrar_viaje(viaje):
    if viaje.finalizado and not viaje.activo:
        return

    viaje.activo = False
    viaje.finalizado = True
    viaje.finalizado_en = now()
    viaje.save(update_fields=['activo', 'finalizado', 'finalizado_en'])
    Asignacion.objects.filter(viaje=viaje, activo=True).update(activo=False)


def _cerrar_viaje_si_corresponde(viaje):
    hay_asignaciones_activas = Asignacion.objects.filter(
        viaje=viaje,
        asignado=True,
        activo=True,
    ).exists()

    # Si el viaje no tiene pasajeros asignados, no se autocierra.
    if not hay_asignaciones_activas:
        return False

    pasajeros_en_vehiculo = Asignacion.objects.filter(
        viaje=viaje,
        asignado=True,
        activo=True,
        abordo_confirmado=True,
        descenso_confirmado=False,
    ).exists()

    if not pasajeros_en_vehiculo:
        _cerrar_viaje(viaje)
        return True

    distancia_a_destino = _haversine_metros(
        viaje.conductor_lat_actual,
        viaje.conductor_lng_actual,
        viaje.destino_lat,
        viaje.destino_lng,
    )
    if distancia_a_destino is not None and distancia_a_destino <= 40:
        _cerrar_viaje(viaje)
        return True

    return False


def _serialize_pasajero_en_curso(asignacion):
    usuario = asignacion.pasajero.usuario
    parada_activa = asignacion.parada_solicitada and not asignacion.descenso_confirmado
    return {
        'asignacion_id': asignacion.id,
        'nombre': usuario.nombre_completo,
        'foto_perfil': usuario.foto_perfil.url if usuario.foto_perfil else None,
        'estado': _estado_pasajero(asignacion),
        'destino': {
            'lat': asignacion.destino_lat,
            'lng': asignacion.destino_lng,
            'descripcion': asignacion.destino_descripcion,
        },
        'parada_solicitada': parada_activa,
        'parada': {
            'objetivo_lat': asignacion.parada_objetivo_lat,
            'objetivo_lng': asignacion.parada_objetivo_lng,
            'referencia_lat': asignacion.parada_referencia_lat,
            'referencia_lng': asignacion.parada_referencia_lng,
            'solicitada_en': localtime(asignacion.parada_solicitada_en).isoformat() if asignacion.parada_solicitada_en else None,
        } if parada_activa else None,
    }


def _serializar_viaje_en_curso(viaje, asignacion_pasajero=None):
    inicio, destino = _inicio_y_destino(viaje)
    asignaciones = Asignacion.objects.filter(viaje=viaje, asignado=True).select_related('pasajero__usuario')
    pasajeros = [_serialize_pasajero_en_curso(asignacion) for asignacion in asignaciones]
    parada_activa = next((p for p in pasajeros if p['parada_solicitada']), None)

    data = {
        'viaje_id': viaje.id,
        'inicio': inicio,
        'destino': destino,
        'hora_salida': viaje.hora_salida,
        'hora_llegada': viaje.hora_llegada,
        'conductor': {
            'nombre': viaje.conductor.usuario.nombre_completo,
            'vehiculo': viaje.modelo_vehiculo or viaje.descripcion,
            'placas': viaje.placas_vehiculo,
        },
        'origen': {
            'lat': viaje.origen_lat,
            'lng': viaje.origen_lng,
            'descripcion': inicio,
        },
        'destino_final': {
            'lat': viaje.destino_lat,
            'lng': viaje.destino_lng,
            'descripcion': destino,
        },
        'conductor_posicion': {
            'lat': viaje.conductor_lat_actual,
            'lng': viaje.conductor_lng_actual,
            'actualizada_en': localtime(viaje.conductor_ubicacion_actualizada_en).isoformat() if viaje.conductor_ubicacion_actualizada_en else None,
        },
        'parada_activa': parada_activa,
        'pasajeros': pasajeros,
    }

    if asignacion_pasajero is not None:
        destino_lat = asignacion_pasajero.destino_lat or viaje.destino_lat
        destino_lng = asignacion_pasajero.destino_lng or viaje.destino_lng
        distancia_parada = _haversine_metros(
            viaje.conductor_lat_actual,
            viaje.conductor_lng_actual,
            destino_lat,
            destino_lng,
        )
        data['tu_asignacion'] = {
            'asignacion_id': asignacion_pasajero.id,
            'estado': _estado_pasajero(asignacion_pasajero),
            'destino': {
                'lat': destino_lat,
                'lng': destino_lng,
                'descripcion': asignacion_pasajero.destino_descripcion or destino,
            },
            'distancia_a_tu_parada_metros': int(distancia_parada) if distancia_parada is not None else None,
            'puede_solicitar_parada': (
                distancia_parada is not None
                and distancia_parada <= 200
                and asignacion_pasajero.abordo_confirmado
                and not asignacion_pasajero.descenso_confirmado
                and not asignacion_pasajero.parada_solicitada
            ),
            'parada_solicitada': asignacion_pasajero.parada_solicitada,
            'parada': {
                'objetivo_lat': asignacion_pasajero.parada_objetivo_lat,
                'objetivo_lng': asignacion_pasajero.parada_objetivo_lng,
                'referencia_lat': asignacion_pasajero.parada_referencia_lat,
                'referencia_lng': asignacion_pasajero.parada_referencia_lng,
            } if asignacion_pasajero.parada_solicitada else None,
        }

    return data


def _forzar_viaje_en_curso(viaje, asignacion_prioritaria=None):
    viaje.activo = True
    viaje.finalizado = False
    viaje.finalizado_en = None
    viaje.confirmado_por_conductor = True
    if viaje.confirmado_en is None:
        viaje.confirmado_en = now()
    viaje.iniciado = True
    if viaje.inicio_real is None:
        viaje.inicio_real = now()

    if viaje.conductor_lat_actual is None and viaje.origen_lat is not None:
        viaje.conductor_lat_actual = viaje.origen_lat
    if viaje.conductor_lng_actual is None and viaje.origen_lng is not None:
        viaje.conductor_lng_actual = viaje.origen_lng
    viaje.conductor_ubicacion_actualizada_en = now()
    viaje.save(
        update_fields=[
            'activo',
            'finalizado',
            'finalizado_en',
            'confirmado_por_conductor',
            'confirmado_en',
            'iniciado',
            'inicio_real',
            'conductor_lat_actual',
            'conductor_lng_actual',
            'conductor_ubicacion_actualizada_en',
        ]
    )

    asignaciones = Asignacion.objects.filter(viaje=viaje, asignado=True, activo=True).order_by('id')
    objetivo = asignacion_prioritaria or asignaciones.first()
    if objetivo and not objetivo.descenso_confirmado and not objetivo.abordo_confirmado:
        objetivo.abordo_confirmado = True
        objetivo.abordo_confirmado_en = now()
        objetivo.save(update_fields=['abordo_confirmado', 'abordo_confirmado_en'])

    return viaje


def _construir_preinicio(viaje):
    asignaciones = Asignacion.objects.filter(viaje=viaje, asignado=True).select_related('pasajero__usuario')
    pasajeros = [
        {
            'asignacion_id': asignacion.id,
            'nombre': asignacion.pasajero.usuario.nombre_completo,
            'foto_perfil': asignacion.pasajero.usuario.foto_perfil.url if asignacion.pasajero.usuario.foto_perfil else None,
            'abordo_confirmado': asignacion.abordo_confirmado,
        }
        for asignacion in asignaciones
    ]

    todos_abordo = len(pasajeros) > 0 and all(p['abordo_confirmado'] for p in pasajeros)
    salida_dt = _datetime_salida(viaje)
    ahora = localtime(now())
    habilitado_por_tiempo = ahora >= salida_dt + timedelta(minutes=5)
    if viaje.gracia_adicional_hasta:
        habilitado_por_tiempo = habilitado_por_tiempo or ahora >= localtime(viaje.gracia_adicional_hasta)

    inicio, destino = _inicio_y_destino(viaje)
    return {
        'viaje_id': viaje.id,
        'inicio': inicio,
        'destino': destino,
        'hora_salida': viaje.hora_salida,
        'conductor_nombre': viaje.conductor.usuario.nombre_completo,
        'vehiculo': viaje.modelo_vehiculo or viaje.descripcion,
        'placas_vehiculo': viaje.placas_vehiculo,
        'origen_lat': viaje.origen_lat,
        'origen_lng': viaje.origen_lng,
        'destino_lat': viaje.destino_lat,
        'destino_lng': viaje.destino_lng,
        'pasajeros': pasajeros,
        'todos_abordo': todos_abordo,
        'puede_iniciar': todos_abordo or habilitado_por_tiempo,
        'puede_esperar_5_mas': ahora >= salida_dt + timedelta(minutes=5),
    }

@api_view(['GET'])
def obtener_token(request):
    token = os.getenv('TOKEN_MAPBOX', 'token_no_configurado')
    print(f"Token Mapbox: {token}")  # Para depuración
    return JsonResponse({'token': token})

@csrf_exempt
def obtener_estado_conductor(request, conductor_id):
    try:
        conductor = UsuarioConductor.objects.get(id=conductor_id)
        return JsonResponse({'activo': conductor.activo}, status=200)
    except UsuarioConductor.DoesNotExist:
        return JsonResponse({'error': 'Conductor no encontrado'}, status=404)
    
@csrf_exempt
def obtener_viajes(request):
    if request.method == 'GET':
        conductor_id = request.GET.get('conductor_id')  # Obtener el ID del conductor logueado desde los parámetros de la solicitud
        viajes = Viaje.objects.filter(activo=True).exclude(conductor_id=conductor_id).select_related('conductor__usuario')
        data = []

        for viaje in viajes:
            conductor = viaje.conductor.usuario
            data.append({
                'id': viaje.id,
                'direccion': viaje.direccion,
                'direccion_inicio': viaje.direccion_inicio,
                'direccion_destino': viaje.direccion_destino,
                'origen_lat': viaje.origen_lat,
                'origen_lng': viaje.origen_lng,
                'destino_lat': viaje.destino_lat,
                'destino_lng': viaje.destino_lng,
                'es_hacia_fime': viaje.es_hacia_fime,
                'hora_salida': viaje.hora_salida,
                'hora_llegada': viaje.hora_llegada,
                'descripcion': viaje.descripcion,
                'modelo_vehiculo': viaje.modelo_vehiculo,
                'placas_vehiculo': viaje.placas_vehiculo,
                'asientos_disponibles': viaje.asientos_disponibles,
                'costo': str(viaje.costo),
                'fecha_viaje': viaje.fecha_viaje.strftime('%Y-%m-%d'),
                'conductor': {
                    'id': viaje.conductor.id,  # Agregar el ID del conductor
                    'nombre': conductor.nombre_completo,
                    'foto_perfil': conductor.foto_perfil.url if conductor.foto_perfil else None,
                },
            })

        return JsonResponse(data, safe=False)
    return JsonResponse({'error': 'Método no permitido'}, status=405)



@csrf_exempt
def registrar_viaje(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            # Validar campos requeridos
            required_fields = [
                'direccion', 'es_hacia_fime', 'hora_salida', 'hora_llegada',
                'descripcion', 'asientos_disponibles', 'costo', 'fecha_viaje', 'conductor_id'
            ]
            missing_fields = [field for field in required_fields if field not in data]
            if missing_fields:
                return JsonResponse({'error': f'Faltan los siguientes campos: {", ".join(missing_fields)}'}, status=400)

            # Validar que el conductor exista
            try:
                conductor = UsuarioConductor.objects.get(id=data['conductor_id'])
            except UsuarioConductor.DoesNotExist:
                return JsonResponse({'error': 'Conductor no encontrado'}, status=404)

            # Crear el viaje
            viaje = Viaje.objects.create(
                direccion=data['direccion'],
                es_hacia_fime=data['es_hacia_fime'],
                hora_salida=data['hora_salida'],
                hora_llegada=data['hora_llegada'],
                descripcion=data['descripcion'],
                direccion_inicio=data.get('direccion_inicio', ''),
                direccion_destino=data.get('direccion_destino', ''),
                origen_lat=data.get('origen_lat'),
                origen_lng=data.get('origen_lng'),
                destino_lat=data.get('destino_lat'),
                destino_lng=data.get('destino_lng'),
                modelo_vehiculo=data.get('modelo_vehiculo', ''),
                placas_vehiculo=data.get('placas_vehiculo', ''),
                asientos_disponibles=data['asientos_disponibles'],
                costo=data['costo'],
                fecha_viaje=data['fecha_viaje'],
                conductor=conductor,
            )

            return JsonResponse({'message': 'Viaje registrado exitosamente', 'viaje_id': viaje.id}, status=201)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Formato JSON inválido'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Método no permitido'}, status=405)


@csrf_exempt
def login_usuario(request):
    if request.method == 'POST':
        try:
            if request.content_type and 'application/json' in request.content_type:
                data = json.loads(request.body or '{}')
            else:
                data = request.POST

            matricula = data.get('username')
            password = data.get('password')

            if not matricula or not password:
                return JsonResponse({'error': 'Faltan credenciales'}, status=400)

            # Autenticar al usuario
            user = authenticate(request, username=matricula, password=password)

            if user is not None:
                # Inicializar valores de conductor_id y pasajero_id
                conductor_id = None
                pasajero_id = None

                # Verificar si el usuario tiene un registro en UsuarioConductor
                try:
                    conductor = UsuarioConductor.objects.get(usuario_id=user.id)
                    conductor_id = conductor.id
                except UsuarioConductor.DoesNotExist:
                    pass

                # Verificar si el usuario tiene un registro en UsuarioPasajero
                try:
                    pasajero = UsuarioPasajero.objects.get(usuario_id=user.id)
                    if pasajero.activo:
                        pasajero_id = pasajero.id
                    else:
                        return JsonResponse({
                            'error': 'No se le ha aprobado la solicitud. '
                                     'Si ya envió su solicitud, favor de estar atento al correo universitario para información de la aprobación.'
                        }, status=403)
                except UsuarioPasajero.DoesNotExist:
                    pass

                foto_live = request.FILES.get('foto_live')
                if foto_live:
                    if foto_live.content_type not in ('image/jpeg', 'image/png'):
                        return JsonResponse({'error': 'Formato de imagen invalido'}, status=400)
                    if foto_live.size and foto_live.size > 5 * 1024 * 1024:
                        return JsonResponse({'error': 'La imagen excede 5MB'}, status=400)

                    foto_live_bytes = _read_file_bytes(foto_live)

                    try:
                        face_present, reason = verify_face_present(foto_live_bytes)
                    except RekognitionError:
                        logger.warning(
                            'Rekognition verify_face_present failed usuario_id=%s',
                            user.id,
                        )
                        face_present = None
                        reason = None

                    if face_present is False:
                        return JsonResponse({'error': reason}, status=400)

                    if face_present and not user.foto_perfil:
                        return JsonResponse({'error': 'Foto de perfil no registrada'}, status=400)

                    if face_present and user.foto_perfil:
                        try:
                            match, similarity = compare_faces_s3(
                                user.foto_perfil.name,
                                foto_live_bytes,
                            )
                            logger.info(
                                'login_face_compare usuario_id=%s similarity=%s success=%s',
                                user.id,
                                similarity,
                                match,
                            )
                        except RekognitionError:
                            logger.warning(
                                'Rekognition compare_faces_s3 failed usuario_id=%s',
                                user.id,
                            )
                            match = True
                        if not match:
                            return JsonResponse(
                                {'error': 'Rostro no coincide', 'similarity': similarity},
                                status=403,
                            )

                # Devolver los IDs y el nombre completo en la respuesta
                return JsonResponse({
                    'message': 'Inicio de sesión exitoso',
                    'usuario_id': user.id,
                    'conductor_id': conductor_id,
                    'pasajero_id': pasajero_id,
                    'nombre': user.nombre_completo  # Incluye el nombre completo
                }, status=200)
            else:
                return JsonResponse({'error': 'Credenciales incorrectas'}, status=401)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Formato JSON inválido'}, status=400)
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
@transaction.atomic
def registrar_usuario(request):
    if request.method == 'POST':
        data = request.POST
        try:
            # Validar campos requeridos
            required_fields = ['nombre_completo', 'correo_universitario', 'matricula', 'contraseña']
            missing_fields = [field for field in required_fields if not data.get(field)]
            if missing_fields:
                return JsonResponse({'error': f'Faltan los siguientes campos: {", ".join(missing_fields)}'}, status=400)

            # Crear usuario general
            usuario = Usuario(
                nombre_completo=data['nombre_completo'],
                correo_universitario=data['correo_universitario'],
                matricula=data['matricula'],
            )
            usuario.set_password(data['contraseña'])  # Encripta la contraseña

            # Guardar foto de perfil si está presente
            foto_perfil_bytes = None
            if 'foto_perfil' in request.FILES:
                foto_perfil_file = request.FILES['foto_perfil']
                foto_perfil_bytes = _read_file_bytes(foto_perfil_file)
                usuario.foto_perfil = foto_perfil_file

            usuario.save()
            # Crear usuario pasajero
            pasajero = UsuarioPasajero.objects.create(usuario=usuario)

            # Guardar documentos de pasajero
            if 'credencial_frontal' not in request.FILES or 'credencial_trasera' not in request.FILES:
                return JsonResponse({'error': 'Ambas imágenes de la credencial son obligatorias'}, status=400)

            credencial_frontal = request.FILES['credencial_frontal']
            credencial_trasera = request.FILES['credencial_trasera']
            credencial_frontal_bytes = _read_file_bytes(credencial_frontal)
            credencial_frontal_doc = DocumentacionPasajero.objects.create(
                pasajero=pasajero,
                tipo_documento='credencial_universitaria',
                documento=credencial_frontal,
                necesita_autorizacion=True,
            )
            DocumentacionPasajero.objects.create(
                pasajero=pasajero,
                tipo_documento='credencial_universitaria',
                documento=credencial_trasera,
                necesita_autorizacion=True,
            )

            if 'boleta_rectoria' not in request.FILES:
                return JsonResponse({'error': 'El archivo boleta_rectoria es obligatorio'}, status=400)

            boleta_rectoria = request.FILES['boleta_rectoria']
            boleta_bytes = _read_file_bytes(boleta_rectoria)
            boleta_doc = DocumentacionPasajero.objects.create(
                pasajero=pasajero,
                tipo_documento='boleta_rectoria',
                documento=boleta_rectoria,
                necesita_autorizacion=False,
                autorizado=True,
            )

            # Crear usuario conductor (inactivo por defecto)
            conductor = UsuarioConductor.objects.create(usuario=usuario)

            # Crear solicitud
            solicito_conductor = data.get('solicito_conductor', 'false').lower() == 'true'
            Solicitud.objects.create(
                usuario=usuario,
                pasajero=pasajero,
                conductor=conductor,
                solicito_conductor=solicito_conductor,
                aprobado_pasajero=False,
                aprobado_conductor=False,
            )

            if foto_perfil_bytes:
                try:
                    face_present, _reason = verify_face_present(foto_perfil_bytes)
                    usuario.ai_face_present = face_present
                    usuario.save(update_fields=['ai_face_present'])
                    logger.info(
                        'register_face_present usuario_id=%s success=%s',
                        usuario.id,
                        face_present,
                    )
                except RekognitionError:
                    logger.warning(
                        'Rekognition verify_face_present failed usuario_id=%s',
                        usuario.id,
                    )
                except Exception:
                    logger.warning('Face presence check failed usuario_id=%s', usuario.id)

            if foto_perfil_bytes and credencial_frontal_bytes:
                try:
                    match, similarity = compare_faces_bytes(
                        foto_perfil_bytes,
                        credencial_frontal_bytes,
                    )
                    credencial_frontal_doc.ai_face_similarity = similarity
                    credencial_frontal_doc.save(update_fields=['ai_face_similarity'])
                    logger.info(
                        'register_face_compare usuario_id=%s similarity=%s success=%s',
                        usuario.id,
                        similarity,
                        match,
                    )
                except RekognitionError:
                    logger.warning(
                        'Rekognition compare_faces_bytes failed usuario_id=%s',
                        usuario.id,
                    )
                except Exception:
                    logger.warning('Face compare failed usuario_id=%s', usuario.id)

            if boleta_bytes:
                try:
                    boleta_valid, _detected_text, method = extract_matricula_from_pdf(
                        boleta_bytes,
                        usuario.matricula,
                    )
                    boleta_doc.ai_boleta_valid = boleta_valid
                    boleta_doc.save(update_fields=['ai_boleta_valid'])
                    logger.info(
                        'register_boleta_check usuario_id=%s success=%s method=%s',
                        usuario.id,
                        boleta_valid,
                        method,
                    )
                except RekognitionError:
                    logger.warning(
                        'Rekognition detect_text failed usuario_id=%s',
                        usuario.id,
                    )
                except Exception:
                    logger.warning('Boleta validation failed usuario_id=%s', usuario.id)

            return JsonResponse({'message': 'Usuario registrado exitosamente', 'usuario_id': usuario.id}, status=201)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
        
        
@csrf_exempt
@transaction.atomic
def registrar_conductor(request):
    if request.method == 'POST':
        data = request.POST
        try:
            # Validar campos requeridos
            if not data.get('usuario_id'):
                return JsonResponse({'error': 'El campo usuario_id es obligatorio'}, status=400)

            if 'licencia_frontal' not in request.FILES or 'licencia_trasera' not in request.FILES:
                return JsonResponse({'error': 'Ambas imágenes de la licencia son obligatorias'}, status=400)

            if 'identificacion_frontal' not in request.FILES or 'identificacion_trasera' not in request.FILES:
                return JsonResponse({'error': 'Ambas imágenes de la identificación oficial son obligatorias'}, status=400)

            if 'poliza_seguro' not in request.FILES:
                return JsonResponse({'error': 'El archivo poliza_seguro es obligatorio'}, status=400)

            # Busca el usuario por su ID
            usuario = Usuario.objects.get(id=data['usuario_id'])
            conductor = UsuarioConductor.objects.get(usuario=usuario)

            # Guardar documentos del conductor
            licencia_frontal = request.FILES['licencia_frontal']
            licencia_trasera = request.FILES['licencia_trasera']
            identificacion_frontal = request.FILES['identificacion_frontal']
            identificacion_trasera = request.FILES['identificacion_trasera']
            poliza_seguro = request.FILES['poliza_seguro']

            DocumentacionConductor.objects.create(
                conductor=conductor,
                tipo_documento='licencia_conducir',
                documento=licencia_frontal,
            )
            DocumentacionConductor.objects.create(
                conductor=conductor,
                tipo_documento='licencia_conducir',
                documento=licencia_trasera,
            )
            DocumentacionConductor.objects.create(
                conductor=conductor,
                tipo_documento='identificacion_oficial',
                documento=identificacion_frontal,
            )
            DocumentacionConductor.objects.create(
                conductor=conductor,
                tipo_documento='identificacion_oficial',
                documento=identificacion_trasera,
            )
            DocumentacionConductor.objects.create(
                conductor=conductor,
                tipo_documento='poliza_seguro',
                documento=poliza_seguro,
            )

            return JsonResponse({'message': 'Conductor registrado exitosamente'}, status=201)
        except Usuario.DoesNotExist:
            return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
def crear_asignacion(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            pasajero_id = data.get('pasajero_id')
            viaje_id = data.get('viaje_id')

            # Verificar si ya existe una asignación para el mismo pasajero y viaje
            if Asignacion.objects.filter(pasajero_id=pasajero_id, viaje_id=viaje_id).exists():
                return JsonResponse({'error': 'Ya has solicitado este viaje'}, status=400)

            pasajero = UsuarioPasajero.objects.get(id=pasajero_id)
            viaje = Viaje.objects.get(id=viaje_id)
            conductor = viaje.conductor

            asignacion = Asignacion.objects.create(
                pasajero=pasajero,
                viaje=viaje,
                conductor=conductor,
                destino_lat=viaje.destino_lat,
                destino_lng=viaje.destino_lng,
                destino_descripcion=viaje.direccion_destino or viaje.direccion,
            )
            return JsonResponse({'message': 'Asignación creada exitosamente', 'asignacion_id': asignacion.id}, status=201)
        except UsuarioPasajero.DoesNotExist:
            return JsonResponse({'error': 'Pasajero no encontrado'}, status=404)
        except Viaje.DoesNotExist:
            return JsonResponse({'error': 'Viaje no encontrado'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def obtener_asignaciones_conductor(request, conductor_id):
    if request.method == 'GET':
        asignaciones = Asignacion.objects.filter(conductor_id=conductor_id, activo=True).select_related('pasajero__usuario', 'viaje')
        data = [
            {
                'id': asignacion.id,
                'asignado': asignacion.asignado,
                'abordo_confirmado': asignacion.abordo_confirmado,
                'pasajero': {
                    'nombre': asignacion.pasajero.usuario.nombre_completo,
                    'foto_perfil': asignacion.pasajero.usuario.foto_perfil.url if asignacion.pasajero.usuario.foto_perfil else None,
                },
                'viaje': {
                    'id': asignacion.viaje.id,
                    'direccion': asignacion.viaje.direccion,
                    'hora_salida': asignacion.viaje.hora_salida,
                    'hora_llegada': asignacion.viaje.hora_llegada,
                    'descripcion': asignacion.viaje.descripcion,
                    'fecha_viaje': asignacion.viaje.fecha_viaje.strftime('%Y-%m-%d'),
                },
            }
            for asignacion in asignaciones
        ]
        return JsonResponse(data, safe=False)
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def actualizar_asignacion(request, asignacion_id):
    if request.method == 'PATCH':
        try:
            data = json.loads(request.body)
            asignado = data.get('asignado')

            asignacion = Asignacion.objects.get(id=asignacion_id)
            asignacion.asignado = asignado
            asignacion.activo = asignado  # Si se asigna, sigue activa; si no, se desactiva
            asignacion.save()
            return JsonResponse({'message': 'Asignación actualizada exitosamente'})
        except Asignacion.DoesNotExist:
            return JsonResponse({'error': 'Asignación no encontrada'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def obtener_info_usuario(request, usuario_id):
    try:
        usuario = Usuario.objects.get(id=usuario_id)
        pasajero = UsuarioPasajero.objects.filter(usuario_id=usuario_id).first()
        conductor = UsuarioConductor.objects.filter(usuario_id=usuario_id).first()

        data = {
            'nombre_completo': usuario.nombre_completo,
            'matricula': usuario.matricula,
            'correo_universitario': usuario.correo_universitario,
            'foto_perfil': usuario.foto_perfil.url if usuario.foto_perfil else None,
            'periodo_activo': 'Enero-Junio 2025',  # Por ahora estático
            'estado_pasajero': pasajero.activo if pasajero else False,
            'estado_conductor': conductor.activo if conductor else False,
        }

        return JsonResponse(data, status=200)
    except Usuario.DoesNotExist:
        return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
    
@csrf_exempt
def obtener_viajes_realizados_pasajero(request, pasajero_id):
    if request.method == 'GET':
        try:
            # Obtener asignaciones del pasajero donde asignado = True
            asignaciones = Asignacion.objects.filter(
                pasajero_id=pasajero_id, asignado=True
            ).select_related('viaje', 'viaje__conductor__usuario')

            # Filtrar viajes que ya pasaron
            viajes_realizados = [
                {
                    'id': asignacion.viaje.id,
                    'direccion': asignacion.viaje.direccion,
                    'es_hacia_fime': asignacion.viaje.es_hacia_fime,
                    'hora_salida': asignacion.viaje.hora_salida,
                    'hora_llegada': asignacion.viaje.hora_llegada,
                    'descripcion': asignacion.viaje.descripcion,
                    'fecha_viaje': asignacion.viaje.fecha_viaje.strftime('%Y-%m-%d'),
                    'conductor': {
                        'nombre': asignacion.viaje.conductor.usuario.nombre_completo,
                        'foto_perfil': asignacion.viaje.conductor.usuario.foto_perfil.url if asignacion.viaje.conductor.usuario.foto_perfil else None,
                    },
                }
                for asignacion in asignaciones
                if asignacion.viaje.fecha_viaje < now().date()
            ]

            return JsonResponse(viajes_realizados, safe=False, status=200)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def obtener_viajes_realizados_conductor(request, conductor_id):
    if request.method == 'GET':
        try:
            # Obtener viajes del conductor que ya pasaron
            viajes = Viaje.objects.filter(
                conductor_id=conductor_id, fecha_viaje__lt=now().date()
            ).prefetch_related('asignaciones__pasajero__usuario')

            viajes_realizados = []
            for viaje in viajes:
                pasajeros = [
                    {
                        'id': asignacion.pasajero.usuario.id,
                        'nombre': asignacion.pasajero.usuario.nombre_completo,
                        'foto_perfil': asignacion.pasajero.usuario.foto_perfil.url if asignacion.pasajero.usuario.foto_perfil else None,
                    }
                    for asignacion in viaje.asignaciones.filter(asignado=True)
                ]

                viajes_realizados.append({
                    'id': viaje.id,
                    'direccion': viaje.direccion,
                    'es_hacia_fime': viaje.es_hacia_fime,
                    'hora_salida': viaje.hora_salida,
                    'hora_llegada': viaje.hora_llegada,
                    'descripcion': viaje.descripcion,
                    'fecha_viaje': viaje.fecha_viaje.strftime('%Y-%m-%d'),
                    'pasajeros': pasajeros,
                })

            return JsonResponse(viajes_realizados, safe=False, status=200)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def enviar_mensaje(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            enviado_por_id = data['enviado_por']
            recibido_por_id = data['recibido_por']
            id_viaje = data['id_viaje']
            mensaje = data['mensaje']

            Mensaje.objects.create(
                enviado_por_id=enviado_por_id,
                recibido_por_id=recibido_por_id,
                id_viaje_id=id_viaje,
                mensaje=mensaje,
                fecha_envio=now()
            )
            return JsonResponse({'message': 'Mensaje enviado exitosamente'}, status=201)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Método no permitido'}, status=405)

from django.db.models import Q

@csrf_exempt
def obtener_mensajes_activos(request, usuario_id):
    if request.method == 'GET':
        try:
            mensajes = Mensaje.objects.filter(
                Q(enviado_por_id=usuario_id) | Q(recibido_por_id=usuario_id),
                activo=True
            ).order_by('-fecha_envio')

            chats = {}
            for mensaje in mensajes:
                otro_usuario = mensaje.recibido_por if mensaje.enviado_por and mensaje.enviado_por.id == usuario_id else mensaje.enviado_por
                if otro_usuario and otro_usuario.id not in chats:
                    chats[otro_usuario.id] = mensaje

            data = [
                {
                    'otro_usuario': {
                        'id': mensaje.recibido_por.id if mensaje.enviado_por and mensaje.enviado_por.id == usuario_id else mensaje.enviado_por.id,
                        'nombre': mensaje.recibido_por.nombre_completo if mensaje.enviado_por and mensaje.enviado_por.id == usuario_id else mensaje.enviado_por.nombre_completo,
                        'foto_perfil': mensaje.recibido_por.foto_perfil.url if mensaje.enviado_por and mensaje.enviado_por.id == usuario_id and mensaje.recibido_por.foto_perfil else None,
                    },
                    'mensaje': mensaje.mensaje,
                    'id_viaje': mensaje.id_viaje.id,
                    'fecha_envio': mensaje.fecha_envio.strftime('%Y-%m-%d %H:%M:%S'),
                    'es_enviado_por_usuario': mensaje.enviado_por and mensaje.enviado_por.id == usuario_id,
                }
                for mensaje in chats.values()
            ]
            return JsonResponse(data, safe=False)
        except Exception as e:
            print(f"Error en obtener_mensajes_activos: {e}")
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def obtener_chat(request, usuario_id, otro_usuario_id, id_viaje):
    if request.method == 'GET':
        try:
            mensajes = Mensaje.objects.filter(
                Q(enviado_por_id=usuario_id, recibido_por_id=otro_usuario_id) |
                Q(enviado_por_id=otro_usuario_id, recibido_por_id=usuario_id),
                id_viaje_id=id_viaje
            ).order_by('-fecha_envio')[:100]

            data = [
                {
                    'mensaje': mensaje.mensaje,
                    'fecha_envio': mensaje.fecha_envio.strftime('%Y-%m-%d %H:%M:%S'),
                    'es_enviado_por_usuario': mensaje.enviado_por_id == usuario_id,
                }
                for mensaje in mensajes
            ]
            return JsonResponse(data, safe=False)
        except Exception as e:
            print(f"Error en obtener_chat: {e}")
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Método no permitido'}, status=405)


@csrf_exempt
def verificar_credencial(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    auth_user, auth_error = _authenticate_jwt(request)
    if auth_error:
        return auth_error

    usuario_id = request.POST.get('usuario_id')
    credencial_frontal = request.FILES.get('credencial_frontal')

    if not usuario_id or not credencial_frontal:
        return JsonResponse({'error': 'usuario_id y credencial_frontal son obligatorios'}, status=400)

    try:
        usuario_id_int = int(usuario_id)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'usuario_id invalido'}, status=400)

    if not (auth_user.is_staff or auth_user.is_superuser) and auth_user.id != usuario_id_int:
        return JsonResponse({'error': 'No autorizado'}, status=403)

    if credencial_frontal.content_type not in ('image/jpeg', 'image/png'):
        return JsonResponse({'error': 'Formato de imagen invalido'}, status=400)

    try:
        usuario = Usuario.objects.get(id=usuario_id_int)
        pasajero = UsuarioPasajero.objects.filter(usuario=usuario).first()
        if not pasajero:
            return JsonResponse({'error': 'Pasajero no encontrado'}, status=404)

        if not usuario.foto_perfil:
            return JsonResponse({'error': 'Foto de perfil no registrada'}, status=400)

        credencial_bytes = _read_file_bytes(credencial_frontal)
        match, similarity = compare_faces_s3(usuario.foto_perfil.name, credencial_bytes)

        doc = DocumentacionPasajero.objects.create(
            pasajero=pasajero,
            tipo_documento='credencial_universitaria',
            documento=credencial_frontal,
            necesita_autorizacion=True,
            autorizado=match,
            ai_face_similarity=similarity,
        )

        logger.info(
            'verificar_credencial usuario_id=%s similarity=%s success=%s',
            usuario.id,
            similarity,
            match,
        )

        return JsonResponse(
            {
                'match': match,
                'similarity': similarity,
                'message': 'Coincidencia encontrada' if match else 'No coincide',
                'documento_id': doc.id,
            },
            status=200,
        )
    except RekognitionError:
        logger.warning('Rekognition compare_faces_s3 failed usuario_id=%s', usuario_id_int)
        return JsonResponse({'error': 'Verificacion no disponible'}, status=503)
    except Usuario.DoesNotExist:
        return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
    except Exception:
        logger.exception('verificar_credencial error usuario_id=%s', usuario_id_int)
        return JsonResponse({'error': 'Error interno'}, status=500)


@csrf_exempt
def verificar_boleta(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    auth_user, auth_error = _authenticate_jwt(request)
    if auth_error:
        return auth_error

    usuario_id = request.POST.get('usuario_id')
    boleta_pdf = request.FILES.get('boleta_pdf')

    if not usuario_id or not boleta_pdf:
        return JsonResponse({'error': 'usuario_id y boleta_pdf son obligatorios'}, status=400)

    try:
        usuario_id_int = int(usuario_id)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'usuario_id invalido'}, status=400)

    if not (auth_user.is_staff or auth_user.is_superuser) and auth_user.id != usuario_id_int:
        return JsonResponse({'error': 'No autorizado'}, status=403)

    try:
        usuario = Usuario.objects.get(id=usuario_id_int)
        pasajero = UsuarioPasajero.objects.filter(usuario=usuario).first()
        if not pasajero:
            return JsonResponse({'error': 'Pasajero no encontrado'}, status=404)

        boleta_bytes = _read_file_bytes(boleta_pdf)
        valid, detected_text, method = extract_matricula_from_pdf(
            boleta_bytes,
            usuario.matricula,
        )

        doc = DocumentacionPasajero.objects.create(
            pasajero=pasajero,
            tipo_documento='boleta_rectoria',
            documento=boleta_pdf,
            necesita_autorizacion=False,
            autorizado=valid,
            ai_boleta_valid=valid,
        )

        logger.info(
            'verificar_boleta usuario_id=%s success=%s method=%s',
            usuario.id,
            valid,
            method,
        )

        return JsonResponse(
            {
                'valid': valid,
                'detected_text': _truncate_text(detected_text),
                'method': method,
                'documento_id': doc.id,
            },
            status=200,
        )
    except RekognitionError:
        logger.warning('Rekognition detect_text failed usuario_id=%s', usuario_id_int)
        return JsonResponse({'error': 'Verificacion no disponible'}, status=503)
    except Usuario.DoesNotExist:
        return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
    except Exception:
        logger.exception('verificar_boleta error usuario_id=%s', usuario_id_int)
        return JsonResponse({'error': 'Error interno'}, status=500)


@csrf_exempt
def update_profile_photo(request, uid):
    if request.method != 'PATCH':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    user, auth_error = _authenticate_jwt(request)
    if auth_error:
        return auth_error

    if user.id != uid:
        return JsonResponse({'error': 'No autorizado'}, status=403)

    files = request.FILES
    if not files and request.content_type and 'multipart/form-data' in request.content_type:
        try:
            _, files = MultiPartParser(request.META, request, request.upload_handlers).parse()
        except Exception:
            return JsonResponse({'error': 'Carga de archivo invalida'}, status=400)

    foto_perfil = files.get('foto_perfil')
    if not foto_perfil:
        return JsonResponse({'error': 'foto_perfil es obligatoria'}, status=400)

    if foto_perfil.content_type not in ('image/jpeg', 'image/png'):
        return JsonResponse({'error': 'Formato de imagen invalido'}, status=400)

    if foto_perfil.size and foto_perfil.size > 5 * 1024 * 1024:
        return JsonResponse({'error': 'La imagen excede 5MB'}, status=400)

    try:
        usuario = Usuario.objects.get(id=uid)
    except Usuario.DoesNotExist:
        return JsonResponse({'error': 'Usuario no encontrado'}, status=404)

    foto_bytes = _read_file_bytes(foto_perfil)
    try:
        face_present, reason = verify_face_present(foto_bytes)
    except RekognitionError:
        logger.warning('Rekognition verify_face_present failed usuario_id=%s', uid)
        return JsonResponse({'error': 'Verificacion no disponible'}, status=503)

    if not face_present:
        return JsonResponse({'error': reason}, status=400)

    try:
        normalized_bytes = _normalize_profile_image(foto_bytes)
    except ValueError:
        return JsonResponse({'error': 'Imagen invalida'}, status=400)

    old_key = usuario.foto_perfil.name if usuario.foto_perfil else None
    if old_key:
        try:
            s3 = boto3.client('s3', region_name=settings.AWS_S3_REGION_NAME)
            s3.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=old_key)
        except (ClientError, BotoCoreError):
            logger.warning('S3 delete failed usuario_id=%s', uid)

    new_key = f"fotos_perfil/{uuid.uuid4()}.jpg"
    content_file = ContentFile(normalized_bytes)
    content_file.content_type = "image/jpeg"
    storage_path = default_storage.save(new_key, content_file)

    usuario.foto_perfil = storage_path
    usuario.ai_face_present = True
    usuario.save(update_fields=['foto_perfil', 'ai_face_present'])

    foto_url = usuario.foto_perfil.url if usuario.foto_perfil else None
    return JsonResponse({'foto_url': foto_url}, status=200)


@csrf_exempt
def get_ai_status(request, uid):
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    auth_user, auth_error = _authenticate_jwt(request)
    if auth_error:
        return auth_error

    if not (auth_user.is_staff or auth_user.is_superuser) and auth_user.id != uid:
        return JsonResponse({'error': 'No autorizado'}, status=403)

    try:
        usuario = Usuario.objects.get(id=uid)
        pasajero = UsuarioPasajero.objects.filter(usuario=usuario).first()
        face_similarity = None
        credential_match = None
        boleta_valid = None

        if pasajero:
            cred_doc = (
                DocumentacionPasajero.objects.filter(
                    pasajero=pasajero,
                    tipo_documento='credencial_universitaria',
                )
                .exclude(ai_face_similarity__isnull=True)
                .order_by('-id')
                .first()
            )
            if cred_doc:
                face_similarity = cred_doc.ai_face_similarity
                if face_similarity is not None:
                    credential_match = face_similarity >= _get_similarity_threshold()

            boleta_doc = (
                DocumentacionPasajero.objects.filter(
                    pasajero=pasajero,
                    tipo_documento='boleta_rectoria',
                )
                .exclude(ai_boleta_valid__isnull=True)
                .order_by('-id')
                .first()
            )
            if boleta_doc:
                boleta_valid = boleta_doc.ai_boleta_valid

        return JsonResponse(
            {
                'face_present': usuario.ai_face_present,
                'credential_match': credential_match,
                'similarity': face_similarity,
                'boleta_valid': boleta_valid,
                'profile_photo_url': usuario.foto_perfil.url if usuario.foto_perfil else None,
            },
            status=200,
        )
    except Usuario.DoesNotExist:
        return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
    except Exception:
        logger.exception('get_ai_status error usuario_id=%s', uid)
        return JsonResponse({'error': 'Error interno'}, status=500)

def obtener_recordatorio_conductor(request, conductor_id):
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    viaje = Viaje.objects.filter(
        conductor_id=conductor_id,
        activo=True,
        iniciado=False,
        fecha_viaje=now().date(),
    ).order_by('hora_salida').first()

    if not viaje:
        return JsonResponse({'show_popup': False, 'show_notification': False, 'preinicio': None}, status=200)

    salida_dt = _datetime_salida(viaje)
    ahora = localtime(now())
    minutos_para_salida = int((salida_dt - ahora).total_seconds() // 60)
    inicio, destino = _inicio_y_destino(viaje)

    # Si el conductor no confirma antes de la salida, se cancela automaticamente.
    if not viaje.confirmado_por_conductor and ahora > salida_dt:
        viaje.activo = False
        viaje.save(update_fields=['activo'])
        Asignacion.objects.filter(viaje=viaje).update(activo=False)
        return JsonResponse({'show_popup': False, 'show_notification': False, 'preinicio': None}, status=200)

    preinicio = None
    if viaje.confirmado_por_conductor and ahora >= salida_dt:
        preinicio = _construir_preinicio(viaje)

    return JsonResponse(
        {
            'show_popup': minutos_para_salida <= 15 and not viaje.confirmado_por_conductor and minutos_para_salida >= 0,
            'show_notification': minutos_para_salida <= 15 and not viaje.confirmado_por_conductor and minutos_para_salida >= 0,
            'minutos_para_salida': minutos_para_salida,
            'viaje': {
                'id': viaje.id,
                'inicio': inicio,
                'destino': destino,
                'hora_salida': viaje.hora_salida,
                'confirmado_por_conductor': viaje.confirmado_por_conductor,
                'placas_vehiculo': viaje.placas_vehiculo,
            },
            'preinicio': preinicio,
        },
        status=200,
    )


@csrf_exempt
def accion_viaje_conductor(request, viaje_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
        accion = data.get('accion')

        viaje = Viaje.objects.get(id=viaje_id, activo=True)
        salida_dt = _datetime_salida(viaje)
        ahora = localtime(now())

        if accion == 'confirmar':
            viaje.confirmado_por_conductor = True
            viaje.confirmado_en = now()
            viaje.save(update_fields=['confirmado_por_conductor', 'confirmado_en'])
            return JsonResponse({'message': 'Viaje confirmado por conductor'}, status=200)

        if accion == 'cancelar':
            viaje.activo = False
            viaje.save(update_fields=['activo'])
            Asignacion.objects.filter(viaje=viaje).update(activo=False)
            return JsonResponse({'message': 'Viaje cancelado'}, status=200)

        if accion == 'esperar_5_mas':
            viaje.gracia_adicional_hasta = now() + timedelta(minutes=5)
            viaje.save(update_fields=['gracia_adicional_hasta'])
            return JsonResponse({'message': 'Se agregaron 5 minutos extra de espera'}, status=200)

        if accion == 'iniciar':
            preinicio = _construir_preinicio(viaje)
            if not preinicio['puede_iniciar']:
                return JsonResponse({'error': 'Aun no se cumplen las condiciones para iniciar'}, status=400)

            viaje.iniciado = True
            viaje.inicio_real = now()
            viaje.save(update_fields=['iniciado', 'inicio_real'])
            return JsonResponse({'message': 'Viaje iniciado'}, status=200)

        return JsonResponse({'error': 'Accion no valida'}, status=400)
    except Viaje.DoesNotExist:
        return JsonResponse({'error': 'Viaje no encontrado'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def obtener_recordatorio_pasajero(request, pasajero_id):
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    asignaciones = Asignacion.objects.filter(
        pasajero_id=pasajero_id,
        asignado=True,
        activo=True,
        viaje__activo=True,
        viaje__fecha_viaje=now().date(),
    ).select_related('viaje', 'viaje__conductor__usuario')

    data = []
    for asignacion in asignaciones:
        viaje = asignacion.viaje
        salida_dt = _datetime_salida(viaje)
        ahora = localtime(now())
        minutos_para_salida = int((salida_dt - ahora).total_seconds() // 60)
        inicio, destino = _inicio_y_destino(viaje)

        data.append(
            {
                'asignacion_id': asignacion.id,
                'viaje_id': viaje.id,
                'inicio': inicio,
                'destino': destino,
                'hora_salida': viaje.hora_salida,
                'confirmado_por_conductor': viaje.confirmado_por_conductor,
                'abordo_confirmado': asignacion.abordo_confirmado,
                'origen_lat': viaje.origen_lat,
                'origen_lng': viaje.origen_lng,
                'destino_lat': viaje.destino_lat,
                'destino_lng': viaje.destino_lng,
                'placas_vehiculo': viaje.placas_vehiculo,
                'mostrar_aviso_5_min': viaje.confirmado_por_conductor and minutos_para_salida <= 5 and minutos_para_salida > 0,
                'mostrar_preinicio': viaje.confirmado_por_conductor and minutos_para_salida <= 0 and not asignacion.abordo_confirmado,
                'minutos_para_salida': minutos_para_salida,
            }
        )

    return JsonResponse(data, safe=False, status=200)


@csrf_exempt
def confirmar_abordo_pasajero(request, asignacion_id):
    if request.method != 'PATCH':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    try:
        asignacion = Asignacion.objects.get(id=asignacion_id, activo=True, asignado=True)
        asignacion.abordo_confirmado = True
        asignacion.abordo_confirmado_en = now()
        asignacion.save(update_fields=['abordo_confirmado', 'abordo_confirmado_en'])
        return JsonResponse({'message': 'Abordaje confirmado'}, status=200)
    except Asignacion.DoesNotExist:
        return JsonResponse({'error': 'Asignación no encontrada'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def obtener_viaje_en_curso_conductor(request, conductor_id):
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    viaje = Viaje.objects.filter(
        conductor_id=conductor_id,
        activo=True,
        iniciado=True,
        finalizado=False,
    ).select_related('conductor__usuario').order_by('-inicio_real').first()

    if not viaje:
        return JsonResponse({'hay_viaje': False}, status=200)

    if _cerrar_viaje_si_corresponde(viaje):
        return JsonResponse({'hay_viaje': False, 'viaje_finalizado': True}, status=200)

    return JsonResponse({'hay_viaje': True, 'viaje': _serializar_viaje_en_curso(viaje)}, status=200)


@csrf_exempt
def obtener_viaje_en_curso_pasajero(request, pasajero_id):
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    asignacion = Asignacion.objects.filter(
        pasajero_id=pasajero_id,
        asignado=True,
        activo=True,
        viaje__activo=True,
        viaje__iniciado=True,
        viaje__finalizado=False,
        descenso_confirmado=False,
    ).select_related('viaje', 'viaje__conductor__usuario').order_by('-viaje__inicio_real').first()

    if not asignacion:
        return JsonResponse({'hay_viaje': False}, status=200)

    viaje = asignacion.viaje
    if _cerrar_viaje_si_corresponde(viaje):
        return JsonResponse({'hay_viaje': False, 'viaje_finalizado': True}, status=200)

    return JsonResponse(
        {'hay_viaje': True, 'viaje': _serializar_viaje_en_curso(viaje, asignacion_pasajero=asignacion)},
        status=200,
    )


@csrf_exempt
def actualizar_ubicacion_conductor(request, viaje_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
        lat = data.get('lat')
        lng = data.get('lng')
        if lat is None or lng is None:
            return JsonResponse({'error': 'lat y lng son obligatorios'}, status=400)

        viaje = Viaje.objects.get(id=viaje_id, activo=True, iniciado=True, finalizado=False)
        viaje.conductor_lat_actual = lat
        viaje.conductor_lng_actual = lng
        viaje.conductor_ubicacion_actualizada_en = now()
        viaje.save(
            update_fields=[
                'conductor_lat_actual',
                'conductor_lng_actual',
                'conductor_ubicacion_actualizada_en',
            ]
        )

        cerrado = _cerrar_viaje_si_corresponde(viaje)
        return JsonResponse({'message': 'Ubicación actualizada', 'viaje_finalizado': cerrado}, status=200)
    except Viaje.DoesNotExist:
        return JsonResponse({'error': 'Viaje no encontrado'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def solicitar_parada_pasajero(request, asignacion_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        asignacion = Asignacion.objects.select_related('viaje').get(
            id=asignacion_id,
            activo=True,
            asignado=True,
            abordo_confirmado=True,
            descenso_confirmado=False,
        )
        viaje = asignacion.viaje
        if not viaje.iniciado or not viaje.activo or viaje.finalizado:
            return JsonResponse({'error': 'El viaje no está en curso'}, status=400)

        objetivo_lat = data.get('lat', asignacion.destino_lat or viaje.destino_lat)
        objetivo_lng = data.get('lng', asignacion.destino_lng or viaje.destino_lng)
        if objetivo_lat is None or objetivo_lng is None:
            return JsonResponse({'error': 'No hay coordenadas de parada disponibles'}, status=400)

        origen_lat = viaje.conductor_lat_actual or viaje.origen_lat
        origen_lng = viaje.conductor_lng_actual or viaje.origen_lng
        referencia_lat, referencia_lng = _punto_antes_de_objetivo(
            origen_lat,
            origen_lng,
            objetivo_lat,
            objetivo_lng,
            metros_antes=200,
        )

        asignacion.parada_solicitada = True
        asignacion.parada_solicitada_en = now()
        asignacion.parada_objetivo_lat = objetivo_lat
        asignacion.parada_objetivo_lng = objetivo_lng
        asignacion.parada_referencia_lat = referencia_lat
        asignacion.parada_referencia_lng = referencia_lng
        asignacion.save(
            update_fields=[
                'parada_solicitada',
                'parada_solicitada_en',
                'parada_objetivo_lat',
                'parada_objetivo_lng',
                'parada_referencia_lat',
                'parada_referencia_lng',
            ]
        )

        return JsonResponse({'message': 'Parada solicitada'}, status=200)
    except Asignacion.DoesNotExist:
        return JsonResponse({'error': 'Asignación no encontrada'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def actualizar_estado_parada(request, asignacion_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
        accion = data.get('accion')
        asignacion = Asignacion.objects.select_related('viaje').get(id=asignacion_id, asignado=True)

        if accion == 'baje_del_vehiculo':
            asignacion.descenso_confirmado = True
            asignacion.descenso_confirmado_en = now()
            asignacion.parada_solicitada = False
            asignacion.parada_solicitada_en = None
            asignacion.parada_objetivo_lat = None
            asignacion.parada_objetivo_lng = None
            asignacion.parada_referencia_lat = None
            asignacion.parada_referencia_lng = None
            asignacion.save(
                update_fields=[
                    'descenso_confirmado',
                    'descenso_confirmado_en',
                    'parada_solicitada',
                    'parada_solicitada_en',
                    'parada_objetivo_lat',
                    'parada_objetivo_lng',
                    'parada_referencia_lat',
                    'parada_referencia_lng',
                ]
            )
            cerrado = _cerrar_viaje_si_corresponde(asignacion.viaje)
            return JsonResponse({'message': 'Descenso confirmado', 'viaje_finalizado': cerrado}, status=200)

        if accion == 'no_realizo_parada':
            asignacion.parada_solicitada = False
            asignacion.parada_solicitada_en = None
            asignacion.parada_objetivo_lat = None
            asignacion.parada_objetivo_lng = None
            asignacion.parada_referencia_lat = None
            asignacion.parada_referencia_lng = None
            asignacion.save(
                update_fields=[
                    'parada_solicitada',
                    'parada_solicitada_en',
                    'parada_objetivo_lat',
                    'parada_objetivo_lng',
                    'parada_referencia_lat',
                    'parada_referencia_lng',
                ]
            )
            return JsonResponse({'message': 'Parada cancelada'}, status=200)

        return JsonResponse({'error': 'Acción no válida'}, status=400)
    except Asignacion.DoesNotExist:
        return JsonResponse({'error': 'Asignación no encontrada'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def crear_reporte(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
        usuario_id = data.get('usuario_id')
        viaje_id = data.get('viaje_id')
        descripcion = (data.get('descripcion') or '').strip()
        rol_reportante = (data.get('rol_reportante') or 'pasajero').strip()
        categoria = (data.get('categoria') or 'viaje_en_curso').strip()
        canal_preferido = (data.get('canal_preferido') or 'correo').strip()

        if not usuario_id or not viaje_id or not descripcion:
            return JsonResponse(
                {'error': 'usuario_id, viaje_id y descripcion son obligatorios'},
                status=400,
            )

        usuario = Usuario.objects.get(id=usuario_id)
        viaje = Viaje.objects.get(id=viaje_id)

        reporte = Reporte.objects.create(
            usuario=usuario,
            viaje=viaje,
            rol_reportante=rol_reportante,
            categoria=categoria,
            descripcion=descripcion,
            canal_preferido=canal_preferido,
        )

        return JsonResponse(
            {
                'message': 'Reporte enviado correctamente',
                'reporte_id': reporte.id,
            },
            status=201,
        )
    except Usuario.DoesNotExist:
        return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
    except Viaje.DoesNotExist:
        return JsonResponse({'error': 'Viaje no encontrado'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def forzar_viaje_en_curso_conductor(request, conductor_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        viaje = (
            Viaje.objects.filter(
                conductor_id=conductor_id,
                activo=True,
                finalizado=False,
            )
            .order_by('-fecha_viaje', '-id')
            .first()
        )

        if not viaje:
            return JsonResponse({'error': 'No hay viajes activos para este conductor'}, status=404)

        asignacion = (
            Asignacion.objects.filter(viaje=viaje, asignado=True, activo=True)
            .order_by('id')
            .first()
        )
        viaje = _forzar_viaje_en_curso(viaje, asignacion_prioritaria=asignacion)
        return JsonResponse({'message': 'Viaje temporal forzado', 'viaje_id': viaje.id}, status=200)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def forzar_viaje_en_curso_pasajero(request, pasajero_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        asignacion = (
            Asignacion.objects.filter(
                pasajero_id=pasajero_id,
                asignado=True,
                activo=True,
                viaje__activo=True,
                viaje__finalizado=False,
            )
            .select_related('viaje')
            .order_by('-viaje__fecha_viaje', '-viaje__id')
            .first()
        )

        if not asignacion:
            return JsonResponse({'error': 'No hay asignaciones activas para este pasajero'}, status=404)

        viaje = _forzar_viaje_en_curso(asignacion.viaje, asignacion_prioritaria=asignacion)
        return JsonResponse({'message': 'Viaje temporal forzado', 'viaje_id': viaje.id}, status=200)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
