"""
Verificar que el endpoint recordatorios ahora devuelve datos
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fimeride_backend.settings')
django.setup()

from usuarios.models import Asignacion, Viaje
from django.utils.timezone import now
from datetime import timedelta

print("=" * 70)
print("VERIFICACIÓN DE RECORDATORIOS PASAJERO 6")
print("=" * 70)

ahora = now()
hoy = ahora.date()

print(f"\nHora actual: {ahora.strftime('%H:%M:%S')}")

asignaciones = Asignacion.objects.filter(
    pasajero_id=6,
    activo=True,
    viaje__activo=True
).select_related('viaje', 'viaje__conductor__usuario')

print(f"Asignaciones encontradas: {asignaciones.count()}")

if asignaciones.exists():
    for asignacion in asignaciones:
        viaje = asignacion.viaje
        
        print(f"\n✅ Viaje ID: {viaje.id}")
        print(f"   Fecha: {viaje.fecha_viaje}")
        print(f"   Hora salida: {viaje.hora_salida}")
        
        # Parsear hora de salida
        hora_salida_parts = viaje.hora_salida.split(':')
        hora_salida = ahora.replace(
            hour=int(hora_salida_parts[0]),
            minute=int(hora_salida_parts[1]),
            second=0,
            microsecond=0
        )
        
        if viaje.fecha_viaje > hoy:
            hora_salida = hora_salida.replace(
                year=viaje.fecha_viaje.year,
                month=viaje.fecha_viaje.month,
                day=viaje.fecha_viaje.day
            )
        
        tiempo_5_min_antes = hora_salida - timedelta(minutes=5)
        tiempo_despues_salida = hora_salida + timedelta(minutes=5)
        
        print(f"   Ventana 5min antes: {tiempo_5_min_antes.strftime('%H:%M:%S')} a {hora_salida.strftime('%H:%M:%S')}")
        print(f"   Ventana preinicio: {hora_salida.strftime('%H:%M:%S')} a {tiempo_despues_salida.strftime('%H:%M:%S')}")
        
        mostrar_aviso_5_min = tiempo_5_min_antes <= ahora < hora_salida
        mostrar_preinicio = hora_salida <= ahora <= tiempo_despues_salida
        
        print(f"   ¿Mostrar aviso 5min? {mostrar_aviso_5_min}")
        print(f"   ¿Mostrar preinicio? {mostrar_preinicio}")
        
        if mostrar_aviso_5_min or mostrar_preinicio:
            print(f"\n   ✅ DEBERÍA MOSTRAR RECORDATORIO EN APP")
            print(f"   Conductor: {viaje.conductor.usuario.nombre_completo}")
else:
    print("❌ No hay asignaciones")

print("\n" + "=" * 70)
