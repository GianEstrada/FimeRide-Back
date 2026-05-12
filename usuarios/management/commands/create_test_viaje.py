from django.core.management.base import BaseCommand
from django.utils.timezone import now
from datetime import datetime, timedelta
from usuarios.models import Usuario, UsuarioConductor, UsuarioPasajero, Viaje, Asignacion, Solicitud


class Command(BaseCommand):
    help = 'Crea un viaje de prueba para las 3:00 PM de hoy para activar alertas'

    def handle(self, *args, **options):
        # Crear conductor de prueba
        conductor_user, created = Usuario.objects.get_or_create(
            matricula='COND001',
            defaults={
                'nombre_completo': 'Conductor Test',
                'correo_universitario': 'conductor_test@fime.edu.mx',
            }
        )
        if created:
            conductor_user.set_password('password123')
            conductor_user.save()
        
        conductor, _ = UsuarioConductor.objects.get_or_create(
            usuario=conductor_user,
            defaults={
                'activo': True,
            }
        )

        # Crear pasajero de prueba
        pasajero_user, created = Usuario.objects.get_or_create(
            matricula='PASJ001',
            defaults={
                'nombre_completo': 'Pasajero Test',
                'correo_universitario': 'pasajero_test@fime.edu.mx',
            }
        )
        if created:
            pasajero_user.set_password('password123')
            pasajero_user.save()
        
        pasajero, _ = UsuarioPasajero.objects.get_or_create(
            usuario=pasajero_user,
            defaults={
                'activo': True,
            }
        )

        # Crear solicitud de pasajero
        Solicitud.objects.get_or_create(
            usuario=pasajero_user,
            pasajero=pasajero,
            conductor=conductor,
            defaults={
                'solicito_conductor': False,
                'aprobado_pasajero': True,
                'aprobado_conductor': False,
                'fecha_aprobado_pasajero': now(),
            }
        )

        # Obtener la hora de hoy a las 3:00 PM
        today = now().date()
        fecha_viaje = today

        # Crear viaje para el día actual
        viaje, created = Viaje.objects.get_or_create(
            conductor=conductor,
            fecha_viaje=fecha_viaje,
            hora_salida='15:00',
            defaults={
                'direccion': 'Av. Tecnológico 400, Monterrey, NL 64849',
                'es_hacia_fime': True,
                'hora_llegada': '15:30',
                'descripcion': 'Viaje de prueba para activar alertas de viaje próximo',
                'asientos_disponibles': 3,
                'costo': 50.00,
                'activo': True,
                'confirmado_por_conductor': False,
                'iniciado': False,
                'finalizado': False,
                'direccion_destino': 'FIME - Av Tecnologico',
                'direccion_inicio': 'Av. Tecnológico 400',
            }
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Viaje creado exitosamente')
            )
            self.stdout.write(f'   ID Viaje: {viaje.id}')
            self.stdout.write(f'   Conductor: {conductor_user.nombre_completo} ({conductor_user.matricula})')
            self.stdout.write(f'   Fecha: {viaje.fecha_viaje}')
            self.stdout.write(f'   Salida: {viaje.hora_salida}')
            self.stdout.write(f'   Destino: {viaje.direccion}')
        else:
            self.stdout.write(
                self.style.WARNING(f'⚠️ Viaje ya existe: ID {viaje.id}')
            )

        # Crear asignación para alertar al pasajero
        asignacion, created = Asignacion.objects.get_or_create(
            pasajero=pasajero,
            viaje=viaje,
            conductor=conductor,
            defaults={
                'asignado': True,
                'activo': True,
                'abordo_confirmado': False,
                'descenso_confirmado': False,
            }
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Asignación creada')
            )
            self.stdout.write(f'   ID Asignación: {asignacion.id}')
            self.stdout.write(f'   Pasajero: {pasajero_user.nombre_completo} ({pasajero_user.matricula})')
        else:
            self.stdout.write(
                self.style.WARNING(f'⚠️ Asignación ya existe: ID {asignacion.id}')
            )

        self.stdout.write(
            self.style.SUCCESS(
                '\n🚗 Las alertas deben activarse cuando los usuarios abran la app:\n'
                '   - Pasajero verá: "Próximo viaje disponible a las 15:00"\n'
                '   - Cuando pasen las 15:00, verá "Viaje en curso"'
            )
        )
