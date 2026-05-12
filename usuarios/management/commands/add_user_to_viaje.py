from django.core.management.base import BaseCommand
from usuarios.models import Usuario, UsuarioPasajero, UsuarioConductor, Viaje, Asignacion


class Command(BaseCommand):
    help = 'Agrega un usuario existente al viaje de prueba'

    def add_arguments(self, parser):
        parser.add_argument('usuario_id', type=int, help='ID del usuario (pasajero) a agregar')
        parser.add_argument('--viaje-id', type=int, default=3, help='ID del viaje (default: 3)')

    def handle(self, *args, **options):
        usuario_id = options['usuario_id']
        viaje_id = options['viaje_id']

        # Obtener usuario
        try:
            usuario = Usuario.objects.get(id=usuario_id)
        except Usuario.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'❌ Usuario con ID {usuario_id} no existe')
            )
            return

        # Obtener pasajero
        try:
            pasajero = UsuarioPasajero.objects.get(usuario=usuario)
        except UsuarioPasajero.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'❌ {usuario.nombre_completo} no es pasajero')
            )
            return

        # Obtener viaje
        try:
            viaje = Viaje.objects.get(id=viaje_id)
        except Viaje.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'❌ Viaje con ID {viaje_id} no existe')
            )
            return

        # Obtener conductor del viaje
        conductor = viaje.conductor

        # Crear asignación
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
                self.style.SUCCESS(f'✅ Asignación creada exitosamente')
            )
            self.stdout.write(f'   Pasajero: {usuario.nombre_completo}')
            self.stdout.write(f'   Matrícula: {usuario.matricula}')
            self.stdout.write(f'   Viaje: {viaje.id}')
            self.stdout.write(f'   Salida: {viaje.hora_salida}')
            self.stdout.write(f'   Destino: {viaje.direccion}')
        else:
            self.stdout.write(
                self.style.WARNING(
                    f'⚠️  {usuario.nombre_completo} ya está asignado a este viaje'
                )
            )
