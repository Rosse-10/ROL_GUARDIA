from django.db import migrations

GRUPO_OFICIAL = 'Oficial'


def crear_grupo(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name=GRUPO_OFICIAL)


def borrar_grupo(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name=GRUPO_OFICIAL).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '__first__'),
        ('inicio', '0008_solicitudes_ausencia'),
    ]

    operations = [
        migrations.RunPython(crear_grupo, borrar_grupo),
    ]
