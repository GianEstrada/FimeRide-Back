# FimeRide Backend - Guía de Pruebas

Esta guía detalla cómo configurar el entorno de desarrollo y probar los diferentes endpoints de la API de FimeRide.

## 🔧 Configuración para Pruebas

### 1. Variables de Entorno (.env)

El proyecto requiere un archivo `.env` en la raíz con las siguientes variables:

- **SECRET_KEY**: Clave secreta de Django.
- **DEBUG**: Debe ser `True` para habilitar el acceso desde cualquier IP y desactivar funciones de seguridad restrictivas durante el desarrollo.
- **DATABASE_URL**: Cadena de conexión para PostgreSQL (ej. `postgres://admin:admin@localhost:5432/fimeride`).
- **AWS_ACCESS_KEY_ID** / **AWS_SECRET_ACCESS_KEY**: Credenciales de AWS para S3 y Rekognition.
- **TOKEN_SEGURO**: Token de seguridad personalizado usado en la app.
- **TOKEN_MAPBOX**: Token de la API de Mapbox para funciones de mapas.

### 2. Configuración de Base de Datos (Docker)

Se recomienda usar PostgreSQL mediante Docker:

```bash
# Iniciar contenedor
docker run --name fimeride-db \
  -e POSTGRES_USER=admin \
  -e POSTGRES_PASSWORD=admin \
  -e POSTGRES_DB=fimeride \
  -p 5432:5432 \
  -d postgres
```

### 3. Instalación y Ejecución

```bash
# Instalar dependencias
pip install -r requirements.txt

# Aplicar migraciones
python manage.py migrate

# Iniciar servidor
python manage.py runserver 0.0.0.0:8000
```

---

## 📡 Endpoints de la API

Todos los endpoints tienen el prefijo `/api/`.

### 🔐 Autenticación y Registro

#### Login de Usuario
- **URL**: `POST /api/login/`
- **Cuerpo (JSON)**: `{"username": "matricula", "password": "password"}`
- **Respuesta**: Retorna `usuario_id`, `conductor_id`, `pasajero_id` y el nombre del usuario.

#### Registro de Usuario (Pasajero)
- **URL**: `POST /api/registrar/`
- **Cuerpo (Multipart/Form-Data)**:
  - `nombre_completo`, `correo_universitario`, `matricula`, `contraseña`.
  - `foto_perfil` (Archivo imagen).
  - `credencial_frontal`, `credencial_trasera` (Archivos imagen).
  - `boleta_rectoria` (Archivo PDF/Imagen).
  - `solicito_conductor` (bool, opcional).

#### Registro de Conductor (Documentación Extra)
- **URL**: `POST /api/registrar_conductor/`
- **Cuerpo (Multipart/Form-Data)**:
  - `usuario_id` (int).
  - `licencia_frontal`, `licencia_trasera` (Archivos imagen).
  - `identificacion_frontal`, `identificacion_trasera` (Archivos imagen).
  - `poliza_seguro` (Archivo).

---

### 🚗 Gestión de Viajes

#### Listar Viajes Disponibles
- **URL**: `GET /api/viajes/`
- **Parámetros**: `conductor_id` (opcional, para excluir viajes propios).
- **Descripción**: Lista viajes activos en los que el usuario puede unirse como pasajero.

#### Registrar Nuevo Viaje (Conductor)
- **URL**: `POST /api/registrar_viaje/`
- **Cuerpo (JSON)**:
  - `direccion`, `es_hacia_fime`, `hora_salida`, `hora_llegada`, `descripcion`, `asientos_disponibles`, `costo`, `fecha_viaje`, `conductor_id`.
  - Opcionales: `origen_lat`, `origen_lng`, `destino_lat`, `destino_lng`, `modelo_vehiculo`, `placas_vehiculo`.

#### Acciones del Conductor sobre el Viaje
- **URL**: `POST /api/viajes/<viaje_id>/accion_conductor/`
- **Cuerpo (JSON)**: `{"accion": "confirmar" | "cancelar" | "esperar_5_mas" | "iniciar"}`

#### Actualizar Ubicación en Tiempo Real
- **URL**: `POST /api/viajes/<viaje_id>/ubicacion_conductor/`
- **Cuerpo (JSON)**: `{"lat": float, "lng": float}`

---

### 👥 Asignaciones (Pasajeros uniéndose a viajes)

#### Solicitar unirse a un viaje
- **URL**: `POST /api/asignaciones/`
- **Cuerpo (JSON)**: `{"pasajero_id": int, "viaje_id": int}`

#### Confirmar Abordaje (Pasajero)
- **URL**: `PATCH /api/asignaciones/<asignacion_id>/abordo/`
- **Descripción**: El pasajero confirma que ya subió al vehículo.

#### Solicitar Parada (Pasajero en curso)
- **URL**: `POST /api/asignaciones/<asignacion_id>/solicitar_parada/`
- **Cuerpo (JSON)**: `{"lat": float, "lng": float}` (opcional).

#### Actualizar Estado de Parada/Descenso
- **URL**: `POST /api/asignaciones/<asignacion_id>/estado_parada/`
- **Cuerpo (JSON)**: `{"accion": "baje_del_vehiculo" | "no_realizo_parada"}`

---

### 💬 Mensajería

#### Enviar Mensaje
- **URL**: `POST /api/mensajes/`
- **Cuerpo (JSON)**: `{"enviado_por": id, "recibido_por": id, "id_viaje": id, "mensaje": "texto"}`

#### Obtener Chats Activos
- **URL**: `GET /api/mensajes/<usuario_id>/`
- **Descripción**: Lista las últimas conversaciones del usuario.

#### Obtener Historial de Chat
- **URL**: `GET /api/mensajes/<usuario_id>/<otro_usuario_id>/<id_viaje>/`

---

### 🤖 Verificación IA (AWS Rekognition)

#### Verificar Credencial contra Foto de Perfil
- **URL**: `POST /api/verificar_credencial/`
- **Cuerpo (Multipart)**: `usuario_id`, `credencial_frontal` (imagen).

#### Verificar Boleta (Extracción de Matrícula)
- **URL**: `POST /api/verificar_boleta/`
- **Cuerpo (Multipart)**: `usuario_id`, `boleta_pdf` (archivo).

#### Obtener Estado de Verificación IA
- **URL**: `GET /api/usuario/<uid>/ai_status/`
- **Respuesta**: Indica si hay rostro presente, si coincide con la credencial y si la boleta es válida.

---

### 📊 Otros

#### Crear Reporte (Quejas/Soporte)
- **URL**: `POST /api/reportes/`
- **Cuerpo (JSON)**: `{"usuario_id": id, "viaje_id": id, "descripcion": "...", "rol_reportante": "pasajero"|"conductor", "categoria": "...", "canal_preferido": "..."}`

#### Obtener Token de Mapbox
- **URL**: `GET /api/mapbox-token/`

#### Obtener Información de Usuario
- **URL**: `GET /api/usuario/<usuario_id>/`

---

## 💡 Ejemplos de Prueba con curl

### Iniciar Sesión
```bash
curl -X POST http://localhost:8000/api/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "20211234", "password": "mipassword"}'
```

### Crear un Viaje
```bash
curl -X POST http://localhost:8000/api/registrar_viaje/ \
  -H "Content-Type: application/json" \
  -d '{
    "direccion": "Hacia FIME",
    "es_hacia_fime": true,
    "hora_salida": "07:00:00",
    "hora_llegada": "07:30:00",
    "descripcion": "Viaje matutino",
    "asientos_disponibles": 3,
    "costo": "15.00",
    "fecha_viaje": "2025-05-10",
    "conductor_id": 1
  }'
```

---

## 🔍 Solución de Problemas

1. **Error 403 (No autorizado)**: Algunos endpoints requieren autenticación JWT. Asegúrate de incluir el header `Authorization: Bearer <token>` si es necesario (el endpoint `/api/token/` genera tokens JWT estándar).
2. **Error 405 (Método no permitido)**: Verifica si el endpoint requiere POST, GET, PATCH o DELETE.
3. **Imágenes no cargan**: Verifica que `MEDIA_URL` y `MEDIA_ROOT` estén configurados en `settings.py` y que AWS S3 esté bien configurado si `DEBUG=False`.
