from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0002_mensaje'),
    ]

    operations = [
        migrations.AddField(
            model_name='asignacion',
            name='abordo_confirmado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='asignacion',
            name='abordo_confirmado_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='viaje',
            name='confirmado_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='viaje',
            name='confirmado_por_conductor',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='viaje',
            name='gracia_adicional_hasta',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='viaje',
            name='iniciado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='viaje',
            name='inicio_real',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
