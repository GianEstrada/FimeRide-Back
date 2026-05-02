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

## Nuevas Funcionalidades (Rama: integration/rekognition)

Esta rama introduce la verificacion automatizada de documentos mediante **AWS Rekognition**. A continuacion se detallan los endpoints especificos para probar estas funcionalidades.

### Verificacion IA (AWS Rekognition)

- `POST /api/verificar_credencial/`: Compara la foto de perfil del usuario contra una foto de su credencial universitaria.
  - **Payload (Multipart)**: `usuario_id`, `credencial_frontal` (imagen).
  - **Logica**: Utiliza `compare_faces` de AWS Rekognition. El umbral de aceptacion se define en `.env` (`FACE_SIMILARITY_THRESHOLD`).

- `POST /api/verificar_boleta/`: Valida el estatus de pago del alumno mediante la lectura de la boleta de rectoria.
  - **Payload (Multipart)**: `usuario_id`, `boleta_pdf` (PDF o Imagen).
  - **Logica**: Extrae texto mediante OCR. Busca la matricula del usuario y la leyenda "RECIBO PAGADO" para validar el documento.

- `GET /api/usuario/<id>/ai_status/`: Consulta el estado consolidado de las validaciones de IA para un usuario.
  - **Respuesta**: Retorna si la credencial y la boleta han sido autorizadas.

---

## Guia de Pruebas Paso a Paso

### 1. Preparacion de Datos
Asegurate de que el usuario tenga una foto de perfil cargada antes de verificar la credencial.
Puedes usar el admin de Django o el endpoint `POST /api/usuario/<id>/foto/`.

### 2. Ejecucion de Pruebas Automatizadas
Se han incluido pruebas unitarias que utilizan mocks para AWS.
```bash
python manage.py test usuarios.tests.VerificationTests
```

### 3. Pruebas Manuales con curl

#### Verificar Credencial
```bash
curl -X POST http://localhost:8000/api/verificar_credencial/ \
  -F "usuario_id=1" \
  -F "credencial_frontal=@/ruta/a/tu/foto_credencial.jpg"
```

#### Verificar Boleta
```bash
curl -X POST http://localhost:8000/api/verificar_boleta/ \
  -F "usuario_id=1" \
  -F "boleta_pdf=@/ruta/a/tu/boleta.pdf"
```

#### Consultar Estatus IA
```bash
curl -X GET http://localhost:8000/api/usuario/1/ai_status/
```

---

## Solucion de Problemas

1. **SQLite**: Si tienes problemas de permisos, asegurate de que el usuario tenga escritura en la carpeta raiz.
2. **AWS**: Si los endpoints de IA fallan, verifica que tus credenciales tengan permisos para `Rekognition` y `S3`.
3. **CORS**: En desarrollo local, `CORS_ALLOW_ALL_ORIGINS` esta en `True` si `DEBUG=True`.
