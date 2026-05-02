# FimeRide Backend - Guia de Pruebas

Esta guia detalla como configurar el entorno de desarrollo y probar los diferentes endpoints de la API de FimeRide.

## Configuracion para Pruebas

### 1. Variables de Entorno (.env)

Crea un archivo `.env` en la raiz del proyecto. Las variables requeridas son:

| Variable | Descripcion | Valor Ejemplo |
|----------|-------------|---------------|
| `SECRET_KEY` | Clave secreta de Django | `tu_clave_secreta` |
| `DEBUG` | Activa el modo depuracion | `True` |
| `DATABASE_URL` | URL de PostgreSQL (Opcional) | `postgres://user:pass@localhost:5432/db` |
| `AWS_ACCESS_KEY_ID` | ID de acceso de AWS | `AKIA...` |
| `AWS_SECRET_ACCESS_KEY` | Clave secreta de AWS | `wJalr...` |
| `AWS_STORAGE_BUCKET_NAME` | Nombre del bucket S3 | `fimeridearchivos` |
| `AWS_S3_REGION_NAME` | Region de S3 | `us-east-2` |
| `AWS_REKOGNITION_REGION`| Region de AWS Rekognition | `us-east-2` |
| `FACE_SIMILARITY_THRESHOLD`| Umbral de similitud facial | `80` |
| `TOKEN_SEGURO` | Token de seguridad interno | `mi_token_seguro` |
| `TOKEN_MAPBOX` | Token de la API de Mapbox | `pk.eyJ...` |

### 2. Base de Datos (SQLite vs PostgreSQL)

Para desarrollo local rapido, puedes usar **SQLite** (no requiere instalacion adicional):
- Simplemente **no definas** `DATABASE_URL` en tu archivo `.env`.
- El sistema creara automaticamente un archivo `db.sqlite3` en la raiz.

Si prefieres usar **PostgreSQL** con Docker:
```bash
docker run --name fimeride-db -e POSTGRES_PASSWORD=admin -e POSTGRES_DB=fimeride -p 5432:5432 -d postgres
# Luego agrega DATABASE_URL=postgres://postgres:admin@localhost:5432/fimeride a tu .env
```

### 3. Instalacion y Ejecucion

```bash
# Instalar dependencias
pip install -r requirements.txt

# Aplicar migraciones
python manage.py migrate

# Crear un superusuario (opcional, para el panel de admin)
python manage.py createsuperuser

# Iniciar servidor
python manage.py runserver
```

---

## Endpoints de la API

Todos los endpoints tienen el prefijo `/api/`.

### Autenticacion y Perfil

- `POST /api/login/`: Iniciar sesion. Retorna IDs y datos basicos.
- `POST /api/registrar/`: Registro de usuario (pasajero). Requiere multipart (imagenes/PDF).
- `POST /api/registrar_conductor/`: Registro de documentacion extra para conductores.
- `POST /api/token/`: Obtener par de tokens JWT (SimpleJWT).
- `GET /api/usuario/<id>/`: Obtener informacion detallada del usuario.
- `POST /api/usuario/<id>/foto/`: Actualizar solo la foto de perfil.

### Gestion de Viajes

- `GET /api/viajes/`: Listar viajes disponibles (puedes filtrar por `conductor_id` para excluir propios).
- `POST /api/registrar_viaje/`: Crear un nuevo viaje.
- `GET /api/conductor_estado/<id>/`: Verificar el estado actual de un conductor.
- `POST /api/viajes/<id>/accion_conductor/`: Acciones: `confirmar`, `cancelar`, `esperar_5_mas`, `iniciar`.
- `POST /api/viajes/<id>/ubicacion_conductor/`: Actualizar lat/lng en tiempo real.
- `GET /api/viajes/conductor/<id>/en_curso/`: Obtener viaje actual del conductor.
- `GET /api/viajes/pasajero/<id>/en_curso/`: Obtener viaje actual del pasajero.
- `POST /api/viajes/conductor/<id>/forzar_en_curso/`: Forzar estado de viaje en curso (Debug).
- `POST /api/viajes/pasajero/<id>/forzar_en_curso/`: Forzar estado de viaje en curso (Debug).
- `GET /api/viajes_realizados/conductor/<id>/`: Historial de viajes del conductor.
- `GET /api/viajes_realizados/pasajero/<id>/`: Historial de viajes del pasajero.

### Asignaciones y Paradas

- `POST /api/asignaciones/`: Solicitar unirse a un viaje.
- `GET /api/asignaciones/conductor/<id>/`: Listar pasajeros asignados al viaje del conductor.
- `PATCH /api/asignaciones/<id>/`: Actualizar datos de una asignacion.
- `PATCH /api/asignaciones/<id>/abordo/`: Confirmar que el pasajero subio al vehiculo.
- `POST /api/asignaciones/<id>/solicitar_parada/`: Solicitar descenso en coordenadas especificas.
- `POST /api/asignaciones/<id>/estado_parada/`: Acciones: `baje_del_vehiculo`, `no_realizo_parada`.
- `GET /api/recordatorios/conductor/<id>/`: Recordatorios de proximos viajes.
- `GET /api/recordatorios/pasajero/<id>/`: Recordatorios de proximos viajes.

### Mensajeria

- `POST /api/mensajes/`: Enviar un mensaje.
- `GET /api/mensajes/<id>/`: Listar conversaciones activas del usuario.
- `GET /api/mensajes/<usuario_id>/<otro_id>/<viaje_id>/`: Obtener historial de chat especifico.

### Verificacion IA (AWS Rekognition)

- `POST /api/verificar_credencial/`: Compara foto de perfil vs credencial (Multipart).
- `POST /api/verificar_boleta/`: Extrae matricula de PDF/Imagen de boleta de rectoria.
- `GET /api/usuario/<id>/ai_status/`: Consulta si el usuario paso las validaciones de IA.

---

## Ejemplos con curl

### Crear un Viaje
```bash
curl -X POST http://localhost:8000/api/registrar_viaje/ \
  -H "Content-Type: application/json" \
  -d '{
    "direccion": "Hacia FIME",
    "es_hacia_fime": true,
    "hora_salida": "07:00",
    "asientos_disponibles": 3,
    "costo": "15.00",
    "fecha_viaje": "2025-05-10",
    "conductor_id": 1
  }'
```

---

## Solucion de Problemas

1. **SQLite**: Si tienes problemas de permisos, asegurate de que el usuario tenga escritura en la carpeta raiz.
2. **AWS**: Si los endpoints de IA fallan, verifica que tus credenciales tengan permisos para `Rekognition` y `S3`.
3. **CORS**: En desarrollo local, `CORS_ALLOW_ALL_ORIGINS` esta en `True` si `DEBUG=True`.
