"""
Script para crear viaje a hora futura del servidor (21:40)
Para probar popup de alertas ahora mismo
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fimeride_backend.settings')
django.setup()

from usuarios.models import Viaje, Asignacion, Usuario, UsuarioPasajero, UsuarioConductor
from django.utils.timezone import now

# Borrar viajes anteriores
viajes_eliminados = Viaje.objects.count()
Viaje.objects.all().delete()
print(f"✅ {viajes_eliminados} viaje(s) eliminado(s)")

# Obtener conductor de prueba
conductor_user = Usuario.objects.get(matricula='COND001')
conductor = UsuarioConductor.objects.get(usuario=conductor_user)

# Obtener pasajero real ID 6
pasajero = UsuarioPasajero.objects.get(id=6)
pasajero_user = pasajero.usuario

# Obtener la fecha de hoy (según servidor)
today = now().date()

# Crear viaje para las 15:40 (en ~12 minutos)
viaje = Viaje.objects.create(
    conductor=conductor,
    direccion='Av. Tecnológico 400, Monterrey, NL 64849',
    es_hacia_fime=True,
    hora_salida='15:40',
    hora_llegada='16:10',
    descripcion='Viaje de prueba para ALERTAS - 15:40',
    asientos_disponibles=3,
    costo=50.00,
    fecha_viaje=today,
    activo=True,
    confirmado_por_conductor=False,
    iniciado=False,
    finalizado=False,
    direccion_destino='FIME - Av Tecnologico',
    direccion_inicio='Av. Tecnológico 400',
)

print(f"\n✅ Viaje creado exitosamente")
print(f"   ID: {viaje.id}")
print(f"   Hora salida: {viaje.hora_salida}")
print(f"   Conductor: {conductor_user.nombre_completo}")

# Crear asignación para pasajero ID 6
asignacion = Asignacion.objects.create(
    pasajero=pasajero,
    viaje=viaje,
    conductor=conductor,
    asignado=True,
    activo=True,
    abordo_confirmado=False,
    descenso_confirmado=False,
)

print(f"\n✅ Asignación creada")
print(f"   ID: {asignacion.id}")
print(f"   Pasajero: {pasajero_user.nombre_completo}")
print(f"   Matrícula: {pasajero_user.matricula}")

print(f"\n🚗 Viaje listo para probar alertas")
print(f"   Hora actual servidor: {now().strftime('%H:%M')}")
print(f"   Hora salida: {viaje.hora_salida}")
print(f"   En ~14 minutos debe aparecer el popup")
