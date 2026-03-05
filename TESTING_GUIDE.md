# FimeRide Backend - Testing Guide

## 🔧 Setup for Testing

### 1. Environment Variables (.env)

The project now includes a comprehensive `.env` file with all required variables:

#### **Required Variables:**

- **SECRET_KEY**: Django secret key (already set for dev)
- **DEBUG**: Set to `True` for testing (enables all IPs and disables security features)
- **DATABASE_URL**: PostgreSQL connection string
- **AWS_ACCESS_KEY_ID**: AWS Access Key for S3 file uploads
- **AWS_SECRET_ACCESS_KEY**: AWS Secret Key for S3
- **TOKEN_SEGURO**: Custom security token used in the app
- **TOKEN_MAPBOX**: Mapbox API token for map features

#### **What to update:**

1. **AWS Credentials**: Replace placeholder values with your actual AWS credentials
2. **TOKEN_MAPBOX**: Add your Mapbox token (get one at https://mapbox.com)
3. **DATABASE_URL** (optional): Update if using different database credentials

### 2. Debug Mode Configuration

✅ **Debug mode is now enabled!** When `DEBUG=True`:

- **ALLOWED_HOSTS = ["*"]** → All IP addresses are allowed
- **CORS_ALLOW_ALL_ORIGINS = True** → All origins accepted for API calls
- **Security features disabled** → No SSL redirect, no secure cookies
- **Perfect for testing from any device/IP**

### 3. Database Setup

Using Docker PostgreSQL (recommended):

```bash
# Start PostgreSQL container
docker run --name fimeride-db \
  -e POSTGRES_USER=admin \
  -e POSTGRES_PASSWORD=admin \
  -e POSTGRES_DB=fimeride \
  -p 5432:5432 \
  -d postgres

# Verify container is running
docker ps | grep fimeride-db

# Stop database (when needed)
docker stop fimeride-db

# Start existing container (after first run)
docker start fimeride-db

# View database logs
docker logs fimeride-db

# Connect to database directly (optional)
docker exec -it fimeride-db psql -U admin -d fimeride
```

**Note**: The `.env` file is already configured for this Docker setup.

### 4. Install Dependencies

```bash
# Activate virtual environment (if using one)
source venv/bin/activate  # Linux/macOS
# or
venv\Scripts\activate  # Windows

# Install all requirements
pip install -r requirements.txt
```

### 5. Run Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Create Superuser (Optional)

```bash
python manage.py createsuperuser
```

### 7. Run Development Server

```bash
python manage.py runserver 0.0.0.0:8000
```

The server will be accessible from:
- Local: http://localhost:8000
- Network: http://YOUR_IP:8000 (accessible from other devices on your network)

---

## 📡 Testing Endpoints

### Available Endpoints:

#### Authentication
- `POST /usuarios/login/` - User login
- `POST /usuarios/registrar/` - User registration
- `POST /usuarios/registrar-conductor/` - Register as conductor

#### User Management
- `GET /usuarios/info/<usuario_id>/` - Get user info
- `GET /usuarios/estado-conductor/<conductor_id>/` - Get conductor status

#### Trips (Viajes)
- `GET /usuarios/viajes/` - List available trips
- `POST /usuarios/registrar-viaje/` - Register new trip
- `GET /usuarios/viajes-realizados-pasajero/<pasajero_id>/` - Passenger trip history
- `GET /usuarios/viajes-realizados-conductor/<conductor_id>/` - Conductor trip history

#### Assignments (Asignaciones)
- `POST /usuarios/asignacion/` - Create trip assignment
- `GET /usuarios/asignaciones-conductor/<conductor_id>/` - Get conductor assignments
- `PATCH /usuarios/asignacion/<asignacion_id>/` - Update assignment status

#### Other
- `GET /usuarios/token-mapbox/` - Get Mapbox token

### Example API Testing

#### Using curl:

```bash
# Test login
curl -X POST http://localhost:8000/usuarios/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "20211234", "password": "your_password"}'

# Get available trips
curl http://localhost:8000/usuarios/viajes/?conductor_id=1

# Get Mapbox token
curl http://localhost:8000/usuarios/token-mapbox/
```

#### Using Python requests:

```python
import requests

BASE_URL = "http://localhost:8000"

# Login
response = requests.post(f"{BASE_URL}/usuarios/login/", json={
    "username": "20211234",
    "password": "your_password"
})
print(response.json())

# Get trips
response = requests.get(f"{BASE_URL}/usuarios/viajes/", params={"conductor_id": 1})
print(response.json())
```

#### Using Postman/Insomnia:
1. Import the endpoints listed above
2. Set base URL to `http://localhost:8000` or `http://YOUR_IP:8000`
3. No authentication headers needed for most endpoints (uses CSRF exempt)

---

## 📦 Requirements.txt Status

✅ **All dependencies are present and correctly versioned:**

- **Django 5.1.7** - Web framework
- **djangorestframework 3.16.0** - REST API support
- **django-cors-headers 4.7.0** - CORS handling
- **python-dotenv 1.2.2** - Environment variable management
- **dj-database-url 2.3.0** - Database URL parsing
- **psycopg2-binary 2.9.10** - PostgreSQL adapter
- **boto3 1.28.0 + django-storages 1.14.2** - AWS S3 integration
- **Pillow 11.2.1** - Image handling
- **gunicorn 23.0.0** - Production server (not needed for testing)

**Note**: Both `psycopg2` and `psycopg2-binary` are present. This is fine for development but in production you typically only need one.

---

## 🔍 Troubleshooting

### Common Issues:

1. **Database connection error**
   - Verify Docker container is running: `docker ps | grep fimeride-db`
   - Start container if stopped: `docker start fimeride-db`
   - Check DATABASE_URL in .env matches your Docker setup
   - Run migrations: `python manage.py migrate`

2. **AWS S3 upload errors**
   - Update AWS credentials in .env
   - For testing without S3, comment out DEFAULT_FILE_STORAGE in settings.py

3. **CORS errors**
   - Verify DEBUG=True in .env
   - Restart server after .env changes

4. **Port already in use**
   - Check if another process is using port 8000: `lsof -i :8000`
   - Use different port: `python manage.py runserver 0.0.0.0:8001`
   - Or for database port 5432: `docker ps -a | grep 5432`

5. **Docker database issues**
   - Container not starting: `docker logs fimeride-db`
   - Port conflict: Stop other PostgreSQL instances or change port mapping
   - Reset database: `docker stop fimeride-db && docker rm fimeride-db` then recreate

---

## 🚀 Quick Start Commands

```bash
# 1. Start Docker database
docker start fimeride-db
# (or run the full docker run command if first time)

# 2. Activate virtual environment and setup
source venv/bin/activate
pip install -r requirements.txt

# 3. Run migrations
python manage.py migrate

# 4. Start development server
python manage.py runserver 0.0.0.0:8000

# Access from mobile device on same network
# Find your IP: ip addr show | grep inet
# Then use: http://YOUR_IP:8000
```

---

## 📝 Notes

- **.env** is git-ignored for security
- **.env.example** shows required variables without sensitive data
- **Debug mode** should NEVER be used in production
- **All IPs allowed** in debug mode - convenient for testing but insecure for production
- Make sure to update AWS and Mapbox credentials before testing file uploads and maps

---

## 🐳 Docker Quick Reference

```bash
# Start existing container
docker start fimeride-db

# Stop container
docker stop fimeride-db

# View container status
docker ps -a | grep fimeride

# View database logs
docker logs fimeride-db

# Access PostgreSQL shell
docker exec -it fimeride-db psql -U admin -d fimeride

# Remove container (WARNING: deletes data)
docker stop fimeride-db && docker rm fimeride-db

# Recreate from scratch
docker run --name fimeride-db \
  -e POSTGRES_USER=admin \
  -e POSTGRES_PASSWORD=admin \
  -e POSTGRES_DB=fimeride \
  -p 5432:5432 \
  -d postgres
```
