"""
Verificar zona horaria del servidor
"""
import os
import django
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fimeride_backend.settings')
django.setup()

from django.utils.timezone import now, get_current_timezone
from django.conf import settings

print("=" * 70)
print("INFORMACIÓN DE ZONA HORARIA")
print("=" * 70)

print(f"\nConfiguraciones Django:")
print(f"  TIME_ZONE: {settings.TIME_ZONE}")
print(f"  USE_TZ: {settings.USE_TZ}")

print(f"\nHora con timezone-aware (Django now()):")
print(f"  {now()}")
print(f"  Zona: {get_current_timezone()}")

print(f"\nHora local (sin timezone):")
print(f"  {datetime.now()}")

print(f"\nHora UTC:")
print(f"  {datetime.utcnow()}")

print("\n" + "=" * 70)
