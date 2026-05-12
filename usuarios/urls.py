from xml.etree.ElementInclude import include
from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView

from .views import actualizar_asignacion, crear_asignacion, enviar_mensaje, login_face_match, obtener_asignaciones_conductor, obtener_chat, obtener_estado_conductor, obtener_info_usuario, obtener_mensajes_activos, obtener_token, obtener_viajes_realizados_conductor, obtener_viajes_realizados_pasajero, registrar_usuario, registrar_conductor, login_usuario, registrar_viaje, obtener_viajes, reenviar_correo_verificacion, verificar_correo_universitario, obtener_recordatorios_pasajero
from usuarios import views

urlpatterns = [
    path('login/', login_usuario, name='login_usuario'),
    path('login_face_match/', login_face_match, name='login_face_match'),
    path('registrar/', registrar_usuario, name='registrar_usuario'),
    path('verificar-correo/<str:token>/', verificar_correo_universitario, name='verificar_correo_universitario'),
    path('reenviar-verificacion/', reenviar_correo_verificacion, name='reenviar_correo_verificacion'),
    path('registrar_conductor/', registrar_conductor, name='registrar_conductor'),
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),  # Cambiado
    path('mapbox-token/', obtener_token, name='obtener_token'),
    path('registrar_viaje/', registrar_viaje, name='registrar_viaje'),
    path('conductor_estado/<int:conductor_id>/', obtener_estado_conductor, name='obtener_estado_conductor'),
    path('viajes/', obtener_viajes, name='obtener_viajes'),
    path('asignaciones/', crear_asignacion, name='crear_asignacion'),
    path('asignaciones/conductor/<int:conductor_id>/', obtener_asignaciones_conductor, name='obtener_asignaciones_conductor'),
    path('asignaciones/<int:asignacion_id>/', actualizar_asignacion, name='actualizar_asignacion'),
    path('usuario/<int:usuario_id>/', obtener_info_usuario, name='obtener_info_usuario'),
    path('viajes_realizados/pasajero/<int:pasajero_id>/', obtener_viajes_realizados_pasajero, name='viajes_realizados_pasajero'),
    path('viajes_realizados/conductor/<int:conductor_id>/', obtener_viajes_realizados_conductor, name='viajes_realizados_conductor'),
    path('mensajes/', enviar_mensaje, name='enviar_mensaje'),
    path('mensajes/<int:usuario_id>/<int:otro_usuario_id>/<int:id_viaje>/', obtener_chat, name='obtener_chat'),
    path('mensajes/<int:usuario_id>/', obtener_mensajes_activos, name='obtener_mensajes_activos'),
    path('recordatorios/pasajero/<int:pasajero_id>/', obtener_recordatorios_pasajero, name='obtener_recordatorios_pasajero'),
]