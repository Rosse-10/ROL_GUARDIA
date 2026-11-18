"""
PROMOCIÓN DE AÑO (se hace una vez al año, en febrero)
=====================================================
La EMI tiene 5 años; solo de 1ro a 4to hacen guardia.

- 5to año  -> EGRESAN (quedan inactivos y su cuenta se desactiva)
- 4to -> 5to (deja de hacer guardia, pero sigue siendo estudiante y puede entrar al sistema)
- 3ro -> 4to, 2do -> 3ro, 1ro -> 2do
- Los marcados como "repite el año" se quedan en su año.
- Solo se promueve a los cadetes activos (los dados de baja no cambian).
- Se guarda el estado anterior de cada cadete para poder DESHACER la última promoción.

Después de promover, el rodillo reinicia cada fila desde el primero de Sistemas.
"""
from django.db import transaction
from django.utils import timezone

from .models import DetalleGuardia, Estudiante, PromocionAnual

NOMBRE_ANIO = {1: '1er Año', 2: '2do Año', 3: '3er Año', 4: '4to Año', 5: '5to Año'}
ULTIMO_ANIO = 5
CLAVE_RESUMEN = {2: 'a_2do', 3: 'a_3ro', 4: 'a_4to', 5: 'a_5to'}


def cadetes_a_promover():
    return (
        Estudiante.objects.filter(activo=True, egresado=False)
        .select_related('carrera', 'usuario')
        .order_by('-anio', 'carrera__nombre', 'apellidos', 'nombres')
    )


def vista_previa():
    """Lo que va a pasar con cada año, para mostrarlo antes de confirmar"""
    por_anio = {anio: [] for anio in range(ULTIMO_ANIO, 0, -1)}
    for e in cadetes_a_promover():
        por_anio[e.anio].append(e)
    pasos = []
    for anio in range(ULTIMO_ANIO, 0, -1):
        if anio == ULTIMO_ANIO:
            destino = '🎓 Egresan'
        elif anio + 1 == ULTIMO_ANIO:
            destino = f'Pasan a {NOMBRE_ANIO[anio + 1]} (sin guardia)'
        else:
            destino = f'Pasan a {NOMBRE_ANIO[anio + 1]}'
        pasos.append({'anio': anio, 'nombre': NOMBRE_ANIO[anio], 'destino': destino, 'cadetes': por_anio[anio]})
    return pasos


def guardias_futuras_generadas():
    """Guardias ya generadas desde mañana: se armaron con los años de antes de promover"""
    return DetalleGuardia.objects.filter(guardia__fecha__gt=timezone.localdate()).values('guardia').distinct().count()


def ultima_promocion():
    return PromocionAnual.objects.first()


@transaction.atomic
def promover(usuario, repiten_ids=()):
    repiten_ids = set(repiten_ids)
    resumen = {'egresados': 0, 'repiten': 0, **{clave: 0 for clave in CLAVE_RESUMEN.values()}}
    cambios = []

    for e in cadetes_a_promover():
        if e.id in repiten_ids:
            resumen['repiten'] += 1
            continue
        cambios.append({'id': e.id, 'anio': e.anio, 'activo': e.activo, 'egresado': e.egresado})
        if e.anio >= ULTIMO_ANIO:
            e.egresado, e.activo = True, False
            resumen['egresados'] += 1
        else:
            e.anio += 1
            resumen[CLAVE_RESUMEN[e.anio]] += 1
        e.save()  # save() también desactiva la cuenta de los egresados

    return PromocionAnual.objects.create(realizada_por=usuario, resumen=resumen, cambios=cambios)


@transaction.atomic
def deshacer(promocion):
    """Devuelve a cada cadete el año y estado que tenía antes de esa promoción"""
    if promocion.deshecha_en:
        return 0
    estudiantes = Estudiante.objects.in_bulk([c['id'] for c in promocion.cambios])
    restaurados = 0
    for c in promocion.cambios:
        e = estudiantes.get(c['id'])
        if e is None:
            continue  # Fue eliminado después de la promoción
        e.anio, e.activo, e.egresado = c['anio'], c['activo'], c['egresado']
        e.save()
        restaurados += 1
    promocion.deshecha_en = timezone.now()
    promocion.save(update_fields=['deshecha_en'])
    return restaurados
