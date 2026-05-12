import json
import os
from decimal import Decimal
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Asignacion, DocumentacionConductor, DocumentacionPasajero, Mensaje, Solicitud, Usuario, UsuarioConductor, UsuarioPasajero, VerificacionIdentidad
from django.db import transaction
from django.conf import settings
from django.utils.timezone import now
from django.contrib.auth import authenticate
from django.core.mail import send_mail
from django.core import signing
from django.urls import reverse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from .models import Viaje
from django.db.models import Q


def _crear_token_verificacion(usuario):
    signer = signing.TimestampSigner(salt=settings.EMAIL_VERIFICATION_SALT)
    payload = f"{usuario.id}:{usuario.correo_universitario}"
    return signer.sign(payload)


def _construir_url_verificacion(request, token):
    path = reverse('verificar_correo_universitario', args=[token])
    if settings.EMAIL_VERIFICATION_BASE_URL:
        return f"{settings.EMAIL_VERIFICATION_BASE_URL.rstrip('/')}{path}"
    return request.build_absolute_uri(path)


def _enviar_correo_verificacion(request, usuario):
    token = _crear_token_verificacion(usuario)
    url_verificacion = _construir_url_verificacion(request, token)
    asunto = "Verifica tu correo universitario - FimeHub"
    mensaje = (
        f"Hola {usuario.nombre_completo},\n\n"
        "Para activar tu acceso básico a FimeHub y tu cuenta como pasajero de FimeRide, "
        "verifica tu correo universitario entrando al siguiente enlace:\n\n"
        f"{url_verificacion}\n\n"
        "Este enlace expira en 24 horas.\n\n"
        "Si no solicitaste esta cuenta, ignora este correo."
    )
    enviados = send_mail(
        subject=asunto,
        message=mensaje,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[usuario.correo_universitario],
        fail_silently=False,
    )
    if enviados < 1:
        raise RuntimeError("No se pudo enviar el correo de verificación")

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
                'es_hacia_fime': viaje.es_hacia_fime,
                'hora_salida': viaje.hora_salida,
                'hora_llegada': viaje.hora_llegada,
                'descripcion': viaje.descripcion,
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
def login_face_match(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    return JsonResponse(
        {
            'ok': True,
            'message': 'Validación facial aprobada temporalmente.',
            'similarity': 100.0,
        },
        status=200,
    )


@csrf_exempt
def verificar_correo_universitario(request, token):
    signer = signing.TimestampSigner(salt=settings.EMAIL_VERIFICATION_SALT)

    try:
        payload = signer.unsign(token, max_age=settings.EMAIL_VERIFICATION_MAX_AGE_SECONDS)
        usuario_id, correo = payload.split(':', 1)
    except signing.SignatureExpired:
        return HttpResponse(
            "Enlace expirado. Regístrate de nuevo para generar una nueva verificación.",
            status=400,
        )
    except (signing.BadSignature, ValueError):
        return HttpResponse("Enlace de verificación inválido.", status=400)

    try:
        usuario = Usuario.objects.get(id=int(usuario_id), correo_universitario=correo)
    except Usuario.DoesNotExist:
        return HttpResponse("Usuario no encontrado para este enlace.", status=404)

    pasajero = UsuarioPasajero.objects.filter(usuario=usuario).first()
    if pasajero is None:
        return HttpResponse("No existe perfil de pasajero para este usuario.", status=404)

    if pasajero.activo:
        return HttpResponse("Tu correo ya estaba verificado. Ya puedes iniciar sesión.", status=200)

    pasajero.activo = True
    pasajero.fecha_aprobacion = now()
    pasajero.save(update_fields=['activo', 'fecha_aprobacion'])

    Solicitud.objects.filter(usuario=usuario, pasajero=pasajero).update(
        aprobado_pasajero=True,
        fecha_aprobado_pasajero=now(),
    )

    return HttpResponse("Correo verificado correctamente. Ya puedes iniciar sesión en FimeHub.", status=200)

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

            if 'foto_perfil' not in request.FILES:
                return JsonResponse({'error': 'La foto de perfil es obligatoria'}, status=400)

            credencial_frontal = request.FILES.get('credencial_frontal')
            credencial_digital_pdf = request.FILES.get('credencial_digital_pdf')

            if not credencial_frontal and not credencial_digital_pdf:
                return JsonResponse({'error': 'Debes subir foto frontal o credencial digital en PDF'}, status=400)

            if 'boleta_rectoria' not in request.FILES:
                return JsonResponse({'error': 'El archivo boleta_rectoria es obligatorio'}, status=400)

            foto_perfil = request.FILES['foto_perfil']
            boleta_rectoria = request.FILES['boleta_rectoria']

            verificacion_resultado = {
                'aprobado': True,
                'boleta_pagada': True,
                'matricula_en_boleta': True,
                'matricula_en_credencial': True,
                'matricula_coincide': True,
                'face_match': True,
                'face_similarity': Decimal('100'),
                'motivo': 'Verificación documental y facial aprobada temporalmente.',
                'raw': {'contingencia': True},
            }

            # Crear usuario general
            usuario = Usuario(
                nombre_completo=data['nombre_completo'],
                correo_universitario=data['correo_universitario'],
                matricula=data['matricula'],
            )
            usuario.set_password(data['contraseña'])
            usuario.foto_perfil = foto_perfil
            usuario.save()

            # Crear usuario pasajero
            pasajero = UsuarioPasajero.objects.create(usuario=usuario)

            VerificacionIdentidad.objects.update_or_create(
                usuario=usuario,
                defaults={
                    'boleta_pagada': verificacion_resultado['boleta_pagada'],
                    'matricula_en_boleta': verificacion_resultado['matricula_en_boleta'],
                    'matricula_en_credencial': verificacion_resultado['matricula_en_credencial'],
                    'matricula_coincide': verificacion_resultado['matricula_coincide'],
                    'face_match_registro': verificacion_resultado['face_match'],
                    'similitud_face_registro': verificacion_resultado['face_similarity'],
                    'registro_aprobado': verificacion_resultado['aprobado'],
                    'motivo_rechazo': verificacion_resultado['motivo'],
                    'detalle_respuesta': verificacion_resultado['raw'],
                },
            )

            if credencial_frontal:
                DocumentacionPasajero.objects.create(
                    pasajero=pasajero,
                    tipo_documento='credencial_universitaria',
                    documento=credencial_frontal,
                    necesita_autorizacion=True,
                    autorizado=verificacion_resultado['matricula_en_credencial'],
                )

            if credencial_digital_pdf:
                DocumentacionPasajero.objects.create(
                    pasajero=pasajero,
                    tipo_documento='credencial_universitaria',
                    documento=credencial_digital_pdf,
                    necesita_autorizacion=True,
                    autorizado=verificacion_resultado['matricula_en_credencial'],
                )

            DocumentacionPasajero.objects.create(
                pasajero=pasajero,
                tipo_documento='boleta_rectoria',
                documento=boleta_rectoria,
                necesita_autorizacion=False,
                autorizado=verificacion_resultado['boleta_pagada'] and verificacion_resultado['matricula_en_boleta'],
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

            _enviar_correo_verificacion(request, usuario)

            return JsonResponse(
                {
                    'message': 'Usuario registrado. Revisa tu correo universitario para verificar la cuenta.',
                    'usuario_id': usuario.id,
                },
                status=201,
            )
        except Exception as e:
            transaction.set_rollback(True)
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
                'pasajero': {
                    'nombre': asignacion.pasajero.usuario.nombre_completo,
                    'foto_perfil': asignacion.pasajero.usuario.foto_perfil.url if asignacion.pasajero.usuario.foto_perfil else None,
                },
                'viaje': {
                    'direccion': asignacion.viaje.direccion,
                    'hora_salida': asignacion.viaje.hora_salida,
                    'hora_llegada': asignacion.viaje.hora_llegada,
                    'descripcion': asignacion.viaje.descripcion,
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