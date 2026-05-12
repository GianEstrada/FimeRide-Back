"""
Script de diagnóstico para verificar datos del viaje de prueba
"""
import os
import django
from datetime import datetime, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fimeride_backend.settings')
django.setup()

from usuarios.models import Viaje, Asignacion, Usuario, UsuarioPasajero, UsuarioConductor
from django.utils.timezone import now

print("=" * 70)
print("DIAGNÓSTICO DE VIAJE DE PRUEBA")
print("=" * 70)

# Verificar usuario pasajero ID 6
print("\n[1] VERIFICAR USUARIO PASAJERO ID 6")
try:
    pasajero = UsuarioPasajero.objects.get(id=6)
    usuario = pasajero.usuario
    print(f"✅ Encontrado Pasajero ID: {pasajero.id}")
    print(f"   Usuario: {usuario.nombre_completo} ({usuario.matricula})")
    print(f"   Email: {usuario.correo_universitario}")
    print(f"   Activo (pasajero): {pasajero.activo}")
except UsuarioPasajero.DoesNotExist:
    print("❌ Pasajero ID 6 NO existe")
except Exception as e:
    print(f"❌ Error: {e}")

# Verificar asignaciones activas del pasajero
print("\n[2] ASIGNACIONES ACTIVAS DEL PASAJERO 6")
asignaciones = Asignacion.objects.filter(
    pasajero_id=6,
    activo=True
).select_related('viaje', 'viaje__conductor__usuario')

if asignaciones.exists():
    for asignacion in asignaciones:
        viaje = asignacion.viaje
        print(f"\n✅ Asignación ID: {asignacion.id}")
        print(f"   Viaje ID: {viaje.id}")
        print(f"   Fecha viaje: {viaje.fecha_viaje}")
        print(f"   Hora salida: {viaje.hora_salida}")
        print(f"   Viaje activo: {viaje.activo}")
        print(f"   Asignación activa: {asignacion.activo}")
        print(f"   Conductor: {viaje.conductor.usuario.nombre_completo}")
else:
    print("❌ No hay asignaciones activas para pasajero 6")

# Verificar TODOS los viajes (sin filtros)
print("\n[3] TODOS LOS VIAJES EN LA BD")
all_viajes = Viaje.objects.all().select_related('conductor__usuario')
if all_viajes.exists():
    for viaje in all_viajes:
        print(f"\n   Viaje ID: {viaje.id}")
        print(f"   Fecha: {viaje.fecha_viaje}")
        print(f"   Hora salida: {viaje.hora_salida}")
        print(f"   Hora llegada: {viaje.hora_llegada}")
        print(f"   Activo: {viaje.activo}")
        print(f"   Confirmado conductor: {viaje.confirmado_por_conductor}")
        print(f"   Iniciado: {viaje.iniciado}")
        print(f"   Finalizado: {viaje.finalizado}")
        print(f"   Conductor: {viaje.conductor.usuario.nombre_completo}")
else:
    print("❌ No hay viajes en la BD")

# Verificar lógica de recordatorios manualmente
print("\n[4] LÓGICA DE RECORDATORIOS PARA PASAJERO 6")
ahora = now()
hoy = ahora.date()
print(f"   Hora actual del sistema: {ahora.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"   Fecha actual: {hoy}")

asignaciones = Asignacion.objects.filter(
    pasajero_id=6,
    activo=True,
    viaje__activo=True
)

if asignaciones.exists():
    for asignacion in asignaciones:
        viaje = asignacion.viaje
        print(f"\n   Procesando Viaje ID {viaje.id}:")
        
        # Verificar fecha
        if viaje.fecha_viaje < hoy:
            print(f"      ❌ Viaje es de una fecha anterior ({viaje.fecha_viaje})")
            continue
        else:
            print(f"      ✅ Fecha válida: {viaje.fecha_viaje}")
        
        # Parsear hora de salida
        try:
            hora_salida_parts = viaje.hora_salida.split(':')
            hora_salida = ahora.replace(
                hour=int(hora_salida_parts[0]),
                minute=int(hora_salida_parts[1]),
                second=0,
                microsecond=0
            )
            
            # Si es para un día distinto, ajustar la fecha
            if viaje.fecha_viaje > hoy:
                hora_salida = hora_salida.replace(
                    year=viaje.fecha_viaje.year,
                    month=viaje.fecha_viaje.month,
                    day=viaje.fecha_viaje.day
                )
            
            print(f"      ✅ Hora de salida parseada: {hora_salida.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Calcular ventanas
            from datetime import timedelta
            tiempo_5_min_antes = hora_salida - timedelta(minutes=5)
            tiempo_despues_salida = hora_salida + timedelta(minutes=5)
            
            print(f"      Ventana 5min antes: {tiempo_5_min_antes.strftime('%H:%M:%S')} a {hora_salida.strftime('%H:%M:%S')}")
            print(f"      Ventana preinicio: {hora_salida.strftime('%H:%M:%S')} a {tiempo_despues_salida.strftime('%H:%M:%S')}")
            print(f"      Hora actual: {ahora.strftime('%H:%M:%S')}")
            
            mostrar_aviso_5_min = tiempo_5_min_antes <= ahora < hora_salida
            mostrar_preinicio = hora_salida <= ahora <= tiempo_despues_salida
            
            print(f"      ¿Mostrar aviso 5min? {mostrar_aviso_5_min}")
            print(f"      ¿Mostrar preinicio? {mostrar_preinicio}")
            
            if not mostrar_aviso_5_min and not mostrar_preinicio:
                print(f"      ❌ NO está en ninguna ventana de tiempo")
            else:
                print(f"      ✅ SÍ debería mostrar recordatorio")
        
        except Exception as e:
            print(f"      ❌ Error al parsear: {e}")
else:
    print("   ❌ No hay asignaciones activas")

print("\n" + "=" * 70)
