from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

import usuarios

class UsuarioManager(BaseUserManager):
    def create_user(self, matricula, password=None, **extra_fields):
        if not matricula:
            raise ValueError('La matrícula es obligatoria')
        user = self.model(matricula=matricula, **extra_fields)
        user.set_password(password)  # Encripta la contraseña
        user.save(using=self._db)
        return user

    def create_superuser(self, matricula, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(matricula, password, **extra_fields)

class Usuario(AbstractBaseUser, PermissionsMixin):
    matricula = models.CharField(max_length=20, unique=True)
    nombre_completo = models.CharField(max_length=255)
    correo_universitario = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    foto_perfil = models.ImageField(upload_to='fotos_perfil/', null=True, blank=True)
    

    objects = UsuarioManager()

    USERNAME_FIELD = 'matricula'
    REQUIRED_FIELDS = ['correo_universitario', 'nombre_completo']

    def __str__(self):
        return self.matricula

class UsuarioPasajero(models.Model):
    id = models.AutoField(primary_key=True)
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE)
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    fecha_aprobacion = models.DateTimeField(null=True, blank=True)
    activo = models.BooleanField(default=False)

class DocumentacionPasajero(models.Model):
    id = models.AutoField(primary_key=True)
    pasajero = models.ForeignKey(UsuarioPasajero, on_delete=models.CASCADE)
    tipo_documento = models.CharField(max_length=50, choices=[
        ('credencial_universitaria', 'Credencial Universitaria'),
        ('boleta_rectoria', 'Boleta de Rectoría'),
    ])
    documento = models.FileField(upload_to='documentos/pasajeros/')
    necesita_autorizacion = models.BooleanField(default=True)
    autorizado = models.BooleanField(default=False)

class UsuarioConductor(models.Model):
    id = models.AutoField(primary_key=True)
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE)
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    fecha_aprobacion = models.DateTimeField(null=True, blank=True)
    activo = models.BooleanField(default=False)

class DocumentacionConductor(models.Model):
    id = models.AutoField(primary_key=True)
    conductor = models.ForeignKey(UsuarioConductor, on_delete=models.CASCADE)
    tipo_documento = models.CharField(max_length=50, choices=[
        ('numero_placas', 'Número de Placas'),
        ('marca_modelo_año', 'Marca, Modelo y Año del Vehículo'),
        ('licencia_conducir', 'Licencia de Conducir'),
        ('identificacion_oficial', 'Identificación Oficial'),
        ('poliza_seguro', 'Póliza de Seguro'),
    ])
    documento = models.FileField(upload_to='documentos/conductores/')
    necesita_autorizacion = models.BooleanField(default=True)
    autorizado = models.BooleanField(default=False)

class Solicitud(models.Model):
    id = models.AutoField(primary_key=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    pasajero = models.OneToOneField(UsuarioPasajero, on_delete=models.CASCADE)
    conductor = models.OneToOneField(UsuarioConductor, on_delete=models.CASCADE, null=True, blank=True)
    solicito_conductor = models.BooleanField(default=False)
    aprobado_pasajero = models.BooleanField(default=False)
    aprobado_conductor = models.BooleanField(default=False)
    fecha_aprobado_pasajero = models.DateTimeField(null=True, blank=True)
    fecha_aprobado_conductor = models.DateTimeField(null=True, blank=True)

class Viaje(models.Model):
    id = models.AutoField(primary_key=True)  # ID del viaje
    direccion = models.CharField(max_length=255)  # Dirección proporcionada
    es_hacia_fime = models.BooleanField()  # Indica si es hacia o desde FIME
    hora_salida = models.CharField(max_length=10)  # Hora de salida (puede ser nomenclatura o formato normal)
    hora_llegada = models.CharField(max_length=10)  # Hora de llegada (puede ser nomenclatura o formato normal)
    descripcion = models.TextField()  # Descripción del viaje
    asientos_disponibles = models.PositiveIntegerField()  # Número de asientos disponibles
    costo = models.DecimalField(max_digits=10, decimal_places=2)  # Costo del viaje
    fecha_viaje = models.DateField()  # Fecha del viaje
    fecha_ofrecido = models.DateTimeField(auto_now_add=True)  # Fecha en la que se ofreció el viaje
    activo = models.BooleanField(default=True)  # Indica si el viaje está activo
    conductor = models.ForeignKey(
        UsuarioConductor, on_delete=models.CASCADE, related_name="viajes"
    )  # Relación con el conductor que ofreció el viaje

    def __str__(self):
        return f"Viaje {self.id} - {self.direccion} ({'Hacia FIME' if self.es_hacia_fime else 'Desde FIME'})"

class Asignacion(models.Model):
    id = models.AutoField(primary_key=True)
    pasajero = models.ForeignKey(UsuarioPasajero, on_delete=models.CASCADE, related_name='asignaciones')
    viaje = models.ForeignKey(Viaje, on_delete=models.CASCADE, related_name='asignaciones')
    conductor = models.ForeignKey(UsuarioConductor, on_delete=models.CASCADE, related_name='asignaciones')
    asignado = models.BooleanField(default=False)  # Estado de la asignación
    activo = models.BooleanField(default=True)  # Si la solicitud sigue activa
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Asignación {self.id} - Pasajero {self.pasajero.usuario.nombre_completo}"
    
    from django.db import models
from django.utils.timezone import now

class Mensaje(models.Model):
    id = models.AutoField(primary_key=True)
    enviado_por = models.ForeignKey('Usuario', on_delete=models.CASCADE, related_name='mensajes_enviados')
    recibido_por = models.ForeignKey('Usuario', on_delete=models.CASCADE, related_name='mensajes_recibidos')
    id_viaje = models.ForeignKey('Viaje', on_delete=models.CASCADE)
    mensaje = models.TextField()  # Mensaje cifrado
    fecha_envio = models.DateTimeField(default=now)
    activo = models.BooleanField(default=True)

    def __str__(self):
        return f"Mensaje {self.id} - {self.enviado_por} -> {self.recibido_por}"


class VerificacionIdentidad(models.Model):
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='verificacion_identidad')
    boleta_pagada = models.BooleanField(default=False)
    matricula_en_boleta = models.BooleanField(default=False)
    matricula_en_credencial = models.BooleanField(default=False)
    matricula_coincide = models.BooleanField(default=False)
    face_match_registro = models.BooleanField(default=False)
    similitud_face_registro = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    registro_aprobado = models.BooleanField(default=False)
    motivo_rechazo = models.TextField(blank=True)
    detalle_respuesta = models.JSONField(default=dict, blank=True)
    fecha_verificacion = models.DateTimeField(default=now)

    def __str__(self):
        return f"Verificacion {self.usuario.matricula} - {'OK' if self.registro_aprobado else 'RECHAZADA'}"