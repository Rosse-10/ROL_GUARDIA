from django.db import migrations

# Las 3 carreras oficiales de la EMI - UA del Trópico. Antes se creaban en cada visita
# a ciertas páginas (asegurar_carreras); ahora se crean una sola vez aquí.
CARRERAS = ['SISTEMAS', 'CIVIL', 'COMERCIAL']


def crear_carreras(apps, schema_editor):
    Carrera = apps.get_model('inicio', 'Carrera')
    for nombre in CARRERAS:
        Carrera.objects.get_or_create(nombre=nombre)


class Migration(migrations.Migration):

    dependencies = [
        ('inicio', '0015_flujo_permutas'),
    ]

    operations = [
        # Al revertir no se borran: podrían tener estudiantes asociados
        migrations.RunPython(crear_carreras, migrations.RunPython.noop),
    ]
