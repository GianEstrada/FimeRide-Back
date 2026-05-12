import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fimeride_backend.settings')
django.setup()

from usuarios.models import Usuario, UsuarioPasajero, UsuarioConductor

usuarios = Usuario.objects.all()
print(f"\n{'ID':<5} {'Matrícula':<15} {'Nombre':<25} {'Pasajero':<10} {'Conductor':<10}")
print("-" * 65)
for u in usuarios:
    pasajero = UsuarioPasajero.objects.filter(usuario_id=u.id).first()
    conductor = UsuarioConductor.objects.filter(usuario_id=u.id).first()
    print(f"{u.id:<5} {u.matricula:<15} {u.nombre_completo:<25} {'✓' if pasajero else '-':<10} {'✓' if conductor else '-':<10}")
