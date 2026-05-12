import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fimeride_backend.settings")
import django

django.setup()

from django.db import connection

exclude = {"django_migrations"}
all_tables = connection.introspection.table_names()
tables = [t for t in all_tables if t not in exclude]
if not tables:
    print("No hay tablas para limpiar")
    raise SystemExit(0)

quoted = ", ".join(f'"{t}"' for t in tables)
sql = f"TRUNCATE {quoted} RESTART IDENTITY CASCADE;"

with connection.cursor() as c:
    c.execute(sql)
    connection.commit()

print(f"OK: {len(tables)} tablas truncadas")
