import json
import os
import math
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Asignacion, DocumentacionConductor, DocumentacionPasajero, Mensaje, Reporte, Solicitud, Usuario, UsuarioConductor, UsuarioPasajero
from django.db import transaction
from django.conf import settings
from django.utils.timezone import now, localtime, make_aware, is_naive
from django.contrib.auth import authenticate
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
import boto3
from .models import Viaje
from usuarios import models
from django.db.models import Q


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
            data = json.loads(request.body)
            matricula = data.get('username')
            password = data.get('password')

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
            if 'foto_perfil' in request.FILES:
                usuario.foto_perfil = request.FILES['foto_perfil']
                print(usuario.foto_perfil.url)  # Nuevo campo
                print("AWS_ACCESS_KEY_ID:", os.getenv('AWS_ACCESS_KEY_ID'))
            print("AWS_SECRET_ACCESS_KEY:", os.getenv('AWS_SECRET_ACCESS_KEY'))

# Verificar conexión a S3
            s3 = boto3.client('s3')
            response = s3.list_buckets()
            print("Buckets disponibles:", response['Buckets'])
            print("AWS_ACCESS_KEY_ID:", os.getenv('AWS_ACCESS_KEY_ID'))
            print("AWS_SECRET_ACCESS_KEY:", os.getenv('AWS_SECRET_ACCESS_KEY'))

            usuario.save()
            print("Archivo guardado en:", usuario.foto_perfil.url)
            # Crear usuario pasajero
            pasajero = UsuarioPasajero.objects.create(usuario=usuario)

            # Guardar documentos de pasajero
            if 'credencial_frontal' not in request.FILES or 'credencial_trasera' not in request.FILES:
                return JsonResponse({'error': 'Ambas imágenes de la credencial son obligatorias'}, status=400)

            credencial_frontal = request.FILES['credencial_frontal']
            credencial_trasera = request.FILES['credencial_trasera']
            DocumentacionPasajero.objects.create(
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
            DocumentacionPasajero.objects.create(
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