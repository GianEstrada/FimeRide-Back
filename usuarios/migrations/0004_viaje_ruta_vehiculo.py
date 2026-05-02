from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0003_viaje_alertas'),
    ]

    operations = [
        migrations.AddField(
            model_name='viaje',
            name='destino_lat',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='viaje',
            name='destino_lng',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='viaje',
            name='direccion_destino',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='viaje',
            name='direccion_inicio',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='viaje',
            name='modelo_vehiculo',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='viaje',
            name='origen_lat',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='viaje',
            name='origen_lng',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='viaje',
            name='placas_vehiculo',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
    ]
