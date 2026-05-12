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
def reenviar_correo_verificacion(request):
    if request.method == 'GET':
        solicitudes_pendientes = (
            Solicitud.objects.filter(aprobado_pasajero=False)
            .select_related('usuario', 'pasajero')
        )

        enviados = 0
        ya_verificados = 0
        fallidos = 0
        detalles_fallidos = []

        usuarios_procesados = set()
        for solicitud in solicitudes_pendientes:
            usuario = solicitud.usuario

            if usuario.id in usuarios_procesados:
                continue
            usuarios_procesados.add(usuario.id)

            if solicitud.pasajero and solicitud.pasajero.activo:
                ya_verificados += 1
                continue

            try:
                _enviar_correo_verificacion(request, usuario)
                enviados += 1
            except Exception as email_error:
                fallidos += 1
                detalle_error = str(email_error)
                detalles_fallidos.append(
                    {
                        'usuario_id': usuario.id,
                        'correo_universitario': usuario.correo_universitario,
                        'error': detalle_error,
                    }
                )
                print(
                    f"No se pudo reenviar correo de verificacion para usuario {usuario.id}: {detalle_error}"
                )

        return JsonResponse(
            {
                'message': 'Reenvío masivo de verificación ejecutado',
                'total_pendientes': len(usuarios_procesados),
                'enviados': enviados,
                'ya_verificados': ya_verificados,
                'fallidos': fallidos,
                'detalles_fallidos': detalles_fallidos,
            },
            status=200,
        )

    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Formato JSON inválido'}, status=400)

    correo_universitario = (data.get('correo_universitario') or '').strip()
    matricula = (data.get('matricula') or '').strip()

    if not correo_universitario and not matricula:
        return JsonResponse(
            {'error': 'Debes enviar correo_universitario o matricula'},
            status=400,
        )

    filtros = {}
    if correo_universitario:
        filtros['correo_universitario'] = correo_universitario
    if matricula:
        filtros['matricula'] = matricula

    try:
        usuario = Usuario.objects.get(**filtros)
    except Usuario.DoesNotExist:
        return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
    except Usuario.MultipleObjectsReturned:
        return JsonResponse({'error': 'Coincidencia ambigua de usuario'}, status=400)

    pasajero = UsuarioPasajero.objects.filter(usuario=usuario).first()
    if pasajero is None:
        return JsonResponse({'error': 'No existe perfil de pasajero para este usuario'}, status=404)

    if pasajero.activo:
        return JsonResponse({'message': 'El usuario ya tiene correo verificado'}, status=200)

    try:
        _enviar_correo_verificacion(request, usuario)
    except Exception as email_error:
        print(f"No se pudo reenviar correo de verificacion para usuario {usuario.id}: {email_error}")
        return JsonResponse(
            {
                'error': 'No se pudo enviar el correo de verificación en este momento',
                'detalle': str(email_error),
            },
            status=503,
        )

    return JsonResponse(
        {'message': 'Correo de verificación reenviado correctamente'},
        status=200,
    )

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
            pasajero = UsuarioPasajero.objects.create(
                usuario=usuario,
                activo=True,
                fecha_aprobacion=now(),
            )

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
                aprobado_pasajero=True,
                fecha_aprobado_pasajero=now(),
                aprobado_conductor=False,
            )

            correo_verificacion_enviado = True
            try:
                _enviar_correo_verificacion(request, usuario)
            except Exception as email_error:
                correo_verificacion_enviado = False
                print(f"No se pudo enviar correo de verificacion para usuario {usuario.id}: {email_error}")

            mensaje = (
                'Usuario registrado. Revisa tu correo universitario para verificar la cuenta.'
                if correo_verificacion_enviado
                else 'Usuario registrado, pero no se pudo enviar el correo de verificacion en este momento.'
            )

            return JsonResponse(
                {
                    'message': mensaje,
                    'usuario_id': usuario.id,
                    'correo_verificacion_enviado': correo_verificacion_enviado,
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

@csrf_exempt
def _parsear_hora_salida(viaje, referencia):
    """Convierte la hora_salida (HH:MM) del viaje a datetime para comparaciones."""
    try:
        hora_salida_parts = viaje.hora_salida.split(':')
        salida = referencia.replace(
            year=viaje.fecha_viaje.year,
            month=viaje.fecha_viaje.month,
            day=viaje.fecha_viaje.day,
            hour=int(hora_salida_parts[0]),
            minute=int(hora_salida_parts[1]),
            second=0,
            microsecond=0,
        )
        return salida
    except Exception:
        return None


def _viaje_en_curso_por_hora(viaje, referencia):
    """Un viaje cuenta como en curso desde la hora_salida hasta que finaliza."""
    salida = _parsear_hora_salida(viaje, referencia)
    if salida is None:
        return False
    if not viaje.activo or viaje.finalizado:
        return False
    return referencia.date() == viaje.fecha_viaje and referencia >= salida


@csrf_exempt
def obtener_recordatorios_pasajero(request, pasajero_id):
    """Obtiene los recordatorios de viajes próximos para un pasajero"""
    if request.method == 'GET':
        try:
            from datetime import timedelta
            
            # Obtener asignaciones activas del pasajero
            asignaciones = Asignacion.objects.filter(
                pasajero_id=pasajero_id,
                activo=True,
                viaje__activo=True
            ).select_related('viaje', 'viaje__conductor__usuario').prefetch_related('viaje')
            
            recordatorios = []
            ahora = now()
            hoy = ahora.date()
            
            for asignacion in asignaciones:
                viaje = asignacion.viaje
                
                # Solo incluir viajes de hoy o después
                if viaje.fecha_viaje < hoy:
                    continue
                
                hora_salida = _parsear_hora_salida(viaje, ahora)
                if hora_salida is None:
                    continue
                
                # Calcular si mostrar aviso de 5 minutos antes
                tiempo_5_min_antes = hora_salida - timedelta(minutes=5)
                mostrar_aviso_5_min = tiempo_5_min_antes <= ahora < hora_salida
                
                # Calcular si mostrar aviso de preinicio (a la hora de salida)
                tiempo_despues_salida = hora_salida + timedelta(minutes=5)
                mostrar_preinicio = hora_salida <= ahora <= tiempo_despues_salida
                
                # Asegurarse de no duplicar notificaciones innecesariamente
                if not mostrar_aviso_5_min and not mostrar_preinicio:
                    continue
                
                recordatorio = {
                    'viaje_id': viaje.id,
                    'asignacion_id': asignacion.id,
                    'inicio': viaje.direccion_inicio or viaje.direccion,
                    'destino': viaje.direccion_destino or viaje.direccion,
                    'hora_salida': viaje.hora_salida,
                    'hora_llegada': viaje.hora_llegada,
                    'fecha_viaje': viaje.fecha_viaje.strftime('%Y-%m-%d'),
                    'confirmado_por_conductor': viaje.confirmado_por_conductor,
                    'mostrar_aviso_5_min': mostrar_aviso_5_min,
                    'mostrar_preinicio': mostrar_preinicio,
                    'conductor': {
                        'id': viaje.conductor.usuario.id,
                        'nombre': viaje.conductor.usuario.nombre_completo,
                        'foto_perfil': viaje.conductor.usuario.foto_perfil.url if viaje.conductor.usuario.foto_perfil else None,
                    }
                }
                recordatorios.append(recordatorio)
            
            return JsonResponse(recordatorios, safe=False, status=200)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Método no permitido'}, status=405)


@csrf_exempt
def obtener_viajes_pasajero_en_curso(request, pasajero_id):
    """Obtiene los viajes en curso (activos) de un pasajero"""
    if request.method == 'GET':
        try:
            ahora = now()

            asignaciones = Asignacion.objects.filter(
                pasajero_id=pasajero_id,
                activo=True,
                viaje__activo=True,
                viaje__finalizado=False
            ).select_related('viaje', 'viaje__conductor__usuario')

            asignacion_activa = None
            for asignacion in asignaciones:
                viaje = asignacion.viaje
                if viaje.iniciado or _viaje_en_curso_por_hora(viaje, ahora):
                    asignacion_activa = asignacion
                    break

            if asignacion_activa is None:
                return JsonResponse({'hay_viaje': False}, status=200)

            viaje = asignacion_activa.viaje
            viaje_data = {
                'viaje_id': viaje.id,
                'inicio': viaje.direccion_inicio or viaje.direccion,
                'destino': viaje.direccion_destino or viaje.direccion,
                'hora_salida': viaje.hora_salida,
                'hora_llegada': viaje.hora_llegada,
                'confirmado_por_conductor': viaje.confirmado_por_conductor,
                'conductor': {
                    'id': viaje.conductor.usuario.id,
                    'nombre': viaje.conductor.usuario.nombre_completo,
                    'vehiculo': viaje.modelo_vehiculo,
                    'placas': viaje.placas_vehiculo,
                    'foto_perfil': viaje.conductor.usuario.foto_perfil.url if viaje.conductor.usuario.foto_perfil else None,
                },
                'origen': {
                    'lat': viaje.origen_lat,
                    'lng': viaje.origen_lng,
                },
                'destino_final': {
                    'lat': viaje.destino_lat,
                    'lng': viaje.destino_lng,
                },
                'conductor_posicion': {
                    'lat': viaje.conductor_lat_actual,
                    'lng': viaje.conductor_lng_actual,
                } if viaje.confirmado_por_conductor else None,
                'usuario_posicion': {
                    'lat': asignacion_activa.parada_referencia_lat,
                    'lng': asignacion_activa.parada_referencia_lng,
                },
                'tu_asignacion': {
                    'asignacion_id': asignacion_activa.id,
                    'destino': {
                        'lat': asignacion_activa.destino_lat or viaje.destino_lat,
                        'lng': asignacion_activa.destino_lng or viaje.destino_lng,
                    },
                    'parada_solicitada': asignacion_activa.parada_solicitada,
                    'parada': {
                        'lat': asignacion_activa.parada_objetivo_lat,
                        'lng': asignacion_activa.parada_objetivo_lng,
                    } if asignacion_activa.parada_objetivo_lat is not None and asignacion_activa.parada_objetivo_lng is not None else None,
                },
                'pasajeros': [
                    {
                        'nombre': a.pasajero.usuario.nombre_completo,
                        'estado': 'bajo_del_vehiculo' if a.descenso_confirmado else ('en_vehiculo' if a.abordo_confirmado else 'pendiente_abordar'),
                    }
                    for a in viaje.asignaciones.filter(activo=True).select_related('pasajero__usuario')
                ],
                'parada_activa': None,
            }

            return JsonResponse({'hay_viaje': True, 'viaje': viaje_data}, status=200)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Método no permitido'}, status=405)


@csrf_exempt
def obtener_viajes_conductor_en_curso(request, conductor_id):
    """Obtiene los viajes en curso (activos) de un conductor"""
    if request.method == 'GET':
        try:
            ahora = now()

            viajes = Viaje.objects.filter(
                conductor_id=conductor_id,
                activo=True,
                finalizado=False
            ).prefetch_related('asignaciones', 'asignaciones__pasajero__usuario')

            viaje_activo = None
            for viaje in viajes:
                if viaje.iniciado or _viaje_en_curso_por_hora(viaje, ahora):
                    viaje_activo = viaje
                    break

            if viaje_activo is None:
                return JsonResponse({'hay_viaje': False}, status=200)

            pasajeros = []
            for asignacion in viaje_activo.asignaciones.filter(activo=True).select_related('pasajero__usuario'):
                pasajeros.append({
                    'asignacion_id': asignacion.id,
                    'usuario_id': asignacion.pasajero.usuario.id,
                    'nombre': asignacion.pasajero.usuario.nombre_completo,
                    'foto_perfil': asignacion.pasajero.usuario.foto_perfil.url if asignacion.pasajero.usuario.foto_perfil else None,
                    'estado': 'bajo_del_vehiculo' if asignacion.descenso_confirmado else ('en_vehiculo' if asignacion.abordo_confirmado else 'pendiente_abordar'),
                    'destino': {
                        'lat': asignacion.destino_lat or viaje_activo.destino_lat,
                        'lng': asignacion.destino_lng or viaje_activo.destino_lng,
                    },
                    'ubicacion_actual': {
                        'lat': asignacion.parada_referencia_lat,
                        'lng': asignacion.parada_referencia_lng,
                    },
                    'abordo_confirmado': asignacion.abordo_confirmado,
                    'descenso_confirmado': asignacion.descenso_confirmado,
                })

            viaje_data = {
                'viaje_id': viaje_activo.id,
                'inicio': viaje_activo.direccion_inicio or viaje_activo.direccion,
                'destino': viaje_activo.direccion_destino or viaje_activo.direccion,
                'hora_salida': viaje_activo.hora_salida,
                'hora_llegada': viaje_activo.hora_llegada,
                'conductor': {
                    'id': viaje_activo.conductor.usuario.id,
                    'nombre': viaje_activo.conductor.usuario.nombre_completo,
                    'vehiculo': viaje_activo.modelo_vehiculo,
                    'placas': viaje_activo.placas_vehiculo,
                },
                'origen': {
                    'lat': viaje_activo.origen_lat,
                    'lng': viaje_activo.origen_lng,
                },
                'destino_final': {
                    'lat': viaje_activo.destino_lat,
                    'lng': viaje_activo.destino_lng,
                },
                'conductor_posicion': {
                    'lat': viaje_activo.conductor_lat_actual,
                    'lng': viaje_activo.conductor_lng_actual,
                },
                'usuario_posicion': {
                    'lat': viaje_activo.conductor_lat_actual,
                    'lng': viaje_activo.conductor_lng_actual,
                },
                'pasajeros': pasajeros,
                'tu_asignacion': None,
                'parada_activa': None,
            }

            return JsonResponse({'hay_viaje': True, 'viaje': viaje_data}, status=200)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Método no permitido'}, status=405)


@csrf_exempt
def obtener_recordatorios_conductor(request, conductor_id):
    """Obtiene los recordatorios de viajes próximos para un conductor"""
    if request.method == 'GET':
        try:
            from datetime import timedelta

            viajes = Viaje.objects.filter(
                conductor_id=conductor_id,
                activo=True
            ).prefetch_related('asignaciones', 'asignaciones__pasajero__usuario')

            ahora = now()
            hoy = ahora.date()

            for viaje in viajes:
                if viaje.fecha_viaje < hoy:
                    continue

                hora_salida = _parsear_hora_salida(viaje, ahora)
                if hora_salida is None:
                    continue

                tiempo_5_min_antes = hora_salida - timedelta(minutes=5)
                mostrar_aviso_5_min = tiempo_5_min_antes <= ahora < hora_salida

                tiempo_despues_salida = hora_salida + timedelta(minutes=5)
                mostrar_preinicio = hora_salida <= ahora <= tiempo_despues_salida

                if not mostrar_aviso_5_min and not mostrar_preinicio:
                    continue

                pasajeros = []
                for asignacion in viaje.asignaciones.all():
                    if asignacion.activo:
                        pasajeros.append({
                            'usuario_id': asignacion.pasajero.usuario.id,
                            'nombre': asignacion.pasajero.usuario.nombre_completo,
                            'abordo_confirmado': asignacion.abordo_confirmado,
                        })
                
                viaje_popup = {
                    'id': viaje.id,
                    'viaje_id': viaje.id,
                    'inicio': viaje.direccion_inicio or viaje.direccion,
                    'destino': viaje.direccion_destino or viaje.direccion,
                    'hora_salida': viaje.hora_salida,
                    'hora_llegada': viaje.hora_llegada,
                    'fecha_viaje': viaje.fecha_viaje.strftime('%Y-%m-%d'),
                    'confirmado_por_conductor': viaje.confirmado_por_conductor,
                    'mostrar_aviso_5_min': mostrar_aviso_5_min,
                    'total_pasajeros': len(pasajeros),
                    'pasajeros': pasajeros
                }

                preinicio = {
                    'viaje_id': viaje.id,
                    'inicio': viaje.direccion_inicio or viaje.direccion,
                    'destino': viaje.direccion_destino or viaje.direccion,
                    'hora_salida': viaje.hora_salida,
                    'conductor_nombre': viaje.conductor.usuario.nombre_completo,
                    'vehiculo': viaje.modelo_vehiculo,
                    'placas_vehiculo': viaje.placas_vehiculo,
                    'origen_lat': viaje.origen_lat,
                    'origen_lng': viaje.origen_lng,
                    'destino_lat': viaje.destino_lat,
                    'destino_lng': viaje.destino_lng,
                    'pasajeros': pasajeros,
                    'puede_iniciar': True,
                    'puede_esperar_5_mas': True,
                }

                return JsonResponse({
                    'show_popup': mostrar_aviso_5_min,
                    'show_notification': mostrar_aviso_5_min,
                    'viaje': viaje_popup,
                    'preinicio': preinicio if mostrar_preinicio else None,
                }, status=200)

            return JsonResponse({
                'show_popup': False,
                'show_notification': False,
                'viaje': None,
                'preinicio': None,
            }, status=200)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Método no permitido'}, status=405)


@csrf_exempt
def actualizar_ubicacion_conductor(request, viaje_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
        lat = float(data.get('lat'))
        lng = float(data.get('lng'))
    except Exception:
        return JsonResponse({'error': 'Payload inválido. Se requiere lat y lng.'}, status=400)

    try:
        viaje = Viaje.objects.get(id=viaje_id, activo=True)
    except Viaje.DoesNotExist:
        return JsonResponse({'error': 'Viaje no encontrado'}, status=404)

    viaje.conductor_lat_actual = lat
    viaje.conductor_lng_actual = lng
    viaje.conductor_ubicacion_actualizada_en = now()
    viaje.save(update_fields=['conductor_lat_actual', 'conductor_lng_actual', 'conductor_ubicacion_actualizada_en'])

    return JsonResponse({'ok': True, 'viaje_finalizado': bool(viaje.finalizado)}, status=200)


@csrf_exempt
def actualizar_ubicacion_pasajero(request, asignacion_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
        lat = float(data.get('lat'))
        lng = float(data.get('lng'))
    except Exception:
        return JsonResponse({'error': 'Payload inválido. Se requiere lat y lng.'}, status=400)

    try:
        asignacion = Asignacion.objects.select_related('viaje').get(id=asignacion_id, activo=True)
    except Asignacion.DoesNotExist:
        return JsonResponse({'error': 'Asignación no encontrada'}, status=404)

    if not asignacion.viaje.activo or asignacion.viaje.finalizado:
        return JsonResponse({'error': 'El viaje no está activo'}, status=400)

    asignacion.parada_referencia_lat = lat
    asignacion.parada_referencia_lng = lng
    asignacion.save(update_fields=['parada_referencia_lat', 'parada_referencia_lng'])

    return JsonResponse({'ok': True}, status=200)