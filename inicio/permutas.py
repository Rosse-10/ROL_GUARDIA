"""
PERMUTAS Y REEMPLAZOS
=====================

Flujo cuando lo pide un cadete:
    A solicita  ->  ESPERA_CADETE  --B acepta-->  ESPERA_OFICIAL  --oficial aprueba-->  APROBADO (se aplica)
                        |  B rechaza / A cancela          |  oficial rechaza / A cancela
                        v                                 v
                    RECHAZADO / CANCELADO             RECHAZADO / CANCELADO

Si lo registra el oficial, se valida y se aplica directo (APROBADO).

- PERMUTA: A y B intercambian sus guardias.
- REEMPLAZO: B cubre la guardia de A (A no recibe otra a cambio).

Plazos:
- Cadetes (solicitar / aceptar): hasta el día ANTERIOR a la guardia.
- Oficial (aprobar / registrar directo): hasta el MISMO día de la guardia.
- Una solicitud que nadie resolvió a tiempo queda VENCIDA.

Reglas (se revisan al solicitar, al aceptar y al aprobar):
- Solo entre cadetes del mismo año que el puesto.
- Nadie queda dos veces el mismo día.
- Nadie recibe una guardia en un día en que tiene licencia/permiso aprobado.
- Una sola solicitud abierta por guardia.
- Al aprobar, las guardias deben seguir como cuando se pidió el cambio.
"""
from datetime import timedelta

from django.db import models, transaction
from django.utils import timezone

from .models import AusenciaLicencia, Cambio, DetalleGuardia


class CambioInvalido(Exception):
    """El cambio no cumple alguna regla; el mensaje se muestra tal cual al usuario"""


def _hoy():
    return timezone.localdate()


def fecha_minima(por_oficial):
    """Primera fecha de guardia que todavía se puede cambiar"""
    return _hoy() if por_oficial else _hoy() + timedelta(days=1)


def _tiene_licencia(estudiante, fecha):
    return AusenciaLicencia.objects.filter(
        estudiante=estudiante, estado='APROBADA', fecha_inicio__lte=fecha, fecha_fin__gte=fecha
    ).exists()


def _nombre(estudiante):
    return f"{estudiante.apellidos}, {estudiante.nombres}"


def validar(tipo, origen, destino=None, reemplazante=None, por_oficial=False, excluir=None):
    """Revisa todas las reglas. Devuelve el cadete B (quien recibe la guardia de A).
    Lanza CambioInvalido con un mensaje claro si algo no se cumple."""
    minimo = fecha_minima(por_oficial)
    plazo = ("No se pueden cambiar guardias pasadas." if por_oficial else
             "Los cambios se piden hasta el día anterior a la guardia. Para hoy, consulte con el oficial.")
    a = origen.estudiante
    anio = origen.puesto.anio_requerido
    fecha_a = origen.guardia.fecha

    if fecha_a < minimo:
        raise CambioInvalido(plazo)

    if tipo == 'PERMUTA':
        if destino is None:
            raise CambioInvalido("Seleccione la guardia del cadete con quien desea intercambiar.")
        if destino.pk == origen.pk or destino.estudiante_id == a.id:
            raise CambioInvalido("No puede intercambiar una guardia consigo mismo.")
        if destino.guardia.fecha < minimo:
            raise CambioInvalido(plazo)
        if destino.puesto.anio_requerido != anio:
            raise CambioInvalido(f"Solo se puede permutar con guardias de {anio}° año.")
        if destino.guardia_id == origen.guardia_id:
            raise CambioInvalido("Ambas guardias son del mismo día: no hay nada que intercambiar.")
        b = destino.estudiante
        fecha_b = destino.guardia.fecha
        if DetalleGuardia.objects.filter(guardia=destino.guardia, estudiante=a).exists():
            raise CambioInvalido(f"{_nombre(a)} ya tiene otro puesto el {fecha_b:%d/%m/%Y}.")
        if _tiene_licencia(a, fecha_b):
            raise CambioInvalido(f"{_nombre(a)} tiene licencia/permiso aprobado el {fecha_b:%d/%m/%Y}.")
    elif tipo == 'REEMPLAZO':
        if reemplazante is None:
            raise CambioInvalido("Seleccione al cadete que realizará el reemplazo.")
        b = reemplazante
        if b.id == a.id:
            raise CambioInvalido("No puede seleccionarse a sí mismo como reemplazante.")
        if not b.activo or b.anio != anio:
            raise CambioInvalido(f"El reemplazante debe ser un cadete activo de {anio}° año.")
    else:
        raise CambioInvalido("El tipo de solicitud no es válido.")

    # B no puede quedar dos veces el día de A, ni recibir una guardia en un día con licencia
    if DetalleGuardia.objects.filter(guardia=origen.guardia, estudiante=b).exists():
        raise CambioInvalido(f"{_nombre(b)} ya tiene un puesto el {fecha_a:%d/%m/%Y}.")
    if _tiene_licencia(b, fecha_a):
        raise CambioInvalido(f"{_nombre(b)} tiene licencia/permiso aprobado el {fecha_a:%d/%m/%Y}.")

    # Una sola solicitud abierta por guardia
    involucradas = [origen.pk] + ([destino.pk] if destino is not None and tipo == 'PERMUTA' else [])
    abiertas = Cambio.objects.filter(estado__in=Cambio.ESTADOS_ABIERTOS).filter(
        models.Q(detalle_origen__in=involucradas) | models.Q(detalle_destino__in=involucradas)
    )
    if excluir is not None:
        abiertas = abiertas.exclude(pk=excluir.pk)
    if abiertas.exists():
        raise CambioInvalido("Ya existe una solicitud de cambio abierta sobre esa guardia.")
    return b


def _verificar_sin_cambios(cambio):
    """Las guardias deben seguir con los mismos cadetes que cuando se pidió el cambio"""
    if cambio.detalle_origen.estudiante_id != cambio.estudiante_origen_id or (
        cambio.tipo == 'PERMUTA' and cambio.detalle_destino.estudiante_id != cambio.estudiante_destino_id
    ):
        raise CambioInvalido("Las guardias cambiaron desde que se pidió esta solicitud; ya no se puede aplicar.")


def _revalidar(cambio, por_oficial):
    _verificar_sin_cambios(cambio)
    validar(
        cambio.tipo, cambio.detalle_origen, cambio.detalle_destino,
        cambio.estudiante_destino if cambio.tipo == 'REEMPLAZO' else None,
        por_oficial=por_oficial, excluir=cambio,
    )


def _aplicar(cambio, usuario):
    """Mueve a los cadetes en las guardias. Siempre dentro de una transacción."""
    origen, destino = cambio.detalle_origen, cambio.detalle_destino
    a, b = cambio.estudiante_origen, cambio.estudiante_destino
    afectados = [(origen, b)] + ([(destino, a)] if cambio.tipo == 'PERMUTA' else [])
    for detalle, nuevo in afectados:
        detalle.estudiante = nuevo
        # La asistencia/licencia era del cadete anterior: el nuevo empieza en Pendiente
        detalle.asistencia = 'PENDIENTE'
        detalle.ausencia = None
        detalle.observacion = f"{cambio.get_tipo_display()} #{cambio.pk} aprobada"
        detalle.registrado_por = usuario
        detalle.save()
    cambio.estado = 'APROBADO'
    cambio.oficial = usuario
    cambio.fecha_resolucion = timezone.now()
    cambio.save()


@transaction.atomic
def solicitar(usuario, tipo, origen, destino=None, reemplazante=None, motivo='', por_oficial=False):
    b = validar(tipo, origen, destino, reemplazante, por_oficial=por_oficial)
    cambio = Cambio.objects.create(
        tipo=tipo, detalle_origen=origen, detalle_destino=destino if tipo == 'PERMUTA' else None,
        estudiante_origen=origen.estudiante, estudiante_destino=b, motivo=motivo,
        estado='ESPERA_CADETE', registrado_por=usuario,
    )
    if por_oficial:
        _aplicar(cambio, usuario)  # El oficial tiene la potestad: se aplica directo
    return cambio


@transaction.atomic
def responder_cadete(cambio, estudiante, acepta, respuesta=''):
    if cambio.estado != 'ESPERA_CADETE' or cambio.estudiante_destino_id != estudiante.id:
        raise CambioInvalido("Esta solicitud ya no está esperando su respuesta.")
    if cambio.fecha_limite < fecha_minima(por_oficial=False):
        raise CambioInvalido("La solicitud venció: ya no se puede responder.")
    if acepta:
        _revalidar(cambio, por_oficial=False)
        cambio.estado = 'ESPERA_OFICIAL'
    else:
        cambio.estado = 'RECHAZADO'
    cambio.respuesta_cadete = respuesta
    cambio.fecha_respuesta_cadete = timezone.now()
    cambio.save()
    return cambio


@transaction.atomic
def cancelar(cambio, estudiante):
    if not cambio.abierto or cambio.estudiante_origen_id != estudiante.id:
        raise CambioInvalido("Solo puede cancelar sus propias solicitudes pendientes.")
    cambio.estado = 'CANCELADO'
    cambio.save()
    return cambio


@transaction.atomic
def resolver_oficial(cambio, usuario, aprueba, observacion=''):
    if cambio.estado != 'ESPERA_OFICIAL':
        raise CambioInvalido("Esta solicitud no está esperando la aprobación del oficial.")
    if cambio.fecha_limite < fecha_minima(por_oficial=True):
        raise CambioInvalido("La guardia ya pasó: la solicitud venció.")
    if aprueba:
        _revalidar(cambio, por_oficial=True)
        cambio.observacion = observacion
        _aplicar(cambio, usuario)
    else:
        if not observacion:
            raise CambioInvalido("Para rechazar una solicitud debe indicar el motivo.")
        cambio.estado = 'RECHAZADO'
        cambio.oficial = usuario
        cambio.fecha_resolucion = timezone.now()
        cambio.observacion = observacion
        cambio.save()
    return cambio


def vencer_pendientes():
    """Marca como VENCIDAS las solicitudes que ya no se pueden resolver a tiempo"""
    hoy = _hoy()

    def con_guardia_hasta(fecha_tope_incluida):
        return (models.Q(detalle_origen__guardia__fecha__lte=fecha_tope_incluida)
                | models.Q(detalle_destino__guardia__fecha__lte=fecha_tope_incluida))

    # El cadete B solo puede responder hasta el día anterior
    vencidas = Cambio.objects.filter(estado='ESPERA_CADETE').filter(con_guardia_hasta(hoy)).update(estado='VENCIDO')
    # El oficial puede aprobar hasta el mismo día de la guardia
    vencidas += Cambio.objects.filter(estado='ESPERA_OFICIAL').filter(
        con_guardia_hasta(hoy - timedelta(days=1))
    ).update(estado='VENCIDO')
    return vencidas
