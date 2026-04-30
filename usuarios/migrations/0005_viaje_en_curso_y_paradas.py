from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0004_viaje_ruta_vehiculo'),
    ]

    operations = [
        migrations.AddField(
            model_name='viaje',
            name='conductor_lat_actual',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='viaje',
            name='conductor_lng_actual',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='viaje',
            name='conductor_ubicacion_actualizada_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='viaje',
            name='finalizado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='viaje',
            name='finalizado_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='asignacion',
            name='destino_descripcion',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='asignacion',
            name='destino_lat',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='asignacion',
            name='destino_lng',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='asignacion',
            name='descenso_confirmado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='asignacion',
            name='descenso_confirmado_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='asignacion',
            name='parada_objetivo_lat',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='asignacion',
            name='parada_objetivo_lng',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='asignacion',
            name='parada_referencia_lat',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='asignacion',
            name='parada_referencia_lng',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='asignacion',
            name='parada_solicitada',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='asignacion',
            name='parada_solicitada_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]