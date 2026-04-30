from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0005_viaje_en_curso_y_paradas'),
    ]

    operations = [
        migrations.CreateModel(
            name='Reporte',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('rol_reportante', models.CharField(default='pasajero', max_length=20)),
                ('categoria', models.CharField(default='viaje_en_curso', max_length=60)),
                ('descripcion', models.TextField()),
                ('canal_preferido', models.CharField(default='correo', max_length=20)),
                ('estado', models.CharField(default='pendiente', max_length=20)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('usuario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reportes', to='usuarios.usuario')),
                ('viaje', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reportes', to='usuarios.viaje')),
            ],
        ),
    ]