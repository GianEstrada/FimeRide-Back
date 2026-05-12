import os
import django
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fimeride_backend.settings')
django.setup()

from usuarios.models import Viaje, Asignacion, Usuario, UsuarioPasajero, UsuarioConductor
from django.utils.timezone import now

# Borrar todos los viajes
viajes_eliminados = Viaje.objects.count()
Viaje.objects.all().delete()
print(f"✅ {viajes_eliminados} viaje(s) eliminado(s)")

# Obtener conductor de prueba
conductor_user = Usuario.objects.get(matricula='COND001')
conductor = UsuarioConductor.objects.get(usuario=conductor_user)

# Obtener pasajero real
pasajero_user = Usuario.objects.get(matricula='1801149')
pasajero = UsuarioPasajero.objects.get(usuario=pasajero_user)

# Obtener la fecha de hoy
today = now().date()

# Crear nuevo viaje para las 15:30
viaje = Viaje.objects.create(
    conductor=conductor,
    direccion='Av. Tecnológico 400, Monterrey, NL 64849',
    es_hacia_fime=True,
    hora_salida='15:30',
    hora_llegada='16:00',
    descripcion='Viaje de prueba para activar alertas - 15:30',
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
print(f"   Salida: {viaje.hora_salida}")
print(f"   Conductor: {conductor_user.nombre_completo}")

# Crear asignación para el pasajero real
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

print(f"\n🚗 Viaje listo para activar alertas")
print(f"   Hora actual: {now().strftime('%H:%M')}")
print(f"   Hora de salida: {viaje.hora_salida}")
