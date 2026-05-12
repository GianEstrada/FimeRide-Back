import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fimeride_backend.settings")
import django

django.setup()

from usuarios.models import Usuario, UsuarioPasajero, Viaje, Asignacion, Mensaje

print("usuarios:", Usuario.objects.count())
print("pasajeros:", UsuarioPasajero.objects.count())
print("viajes:", Viaje.objects.count())
print("asignaciones:", Asignacion.objects.count())
print("mensajes:", Mensaje.objects.count())
