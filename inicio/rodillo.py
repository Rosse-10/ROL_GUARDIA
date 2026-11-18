"""
RODILLO DE GUARDIAS
===================

Cada año (1ro a 4to) tiene su propia FILA, ordenada por carrera y luego por apellido:

    Sistemas (A..Z)  ->  Civil (A..Z)  ->  Comercial (A..Z)  ->  vuelve a Sistemas

Reglas:
- La fila avanza en orden estricto: nadie repite hasta que todos los de su año pasaron.
- Si al cadete le toca y ese día tiene licencia/permiso APROBADO (o todavía no está
  habilitado), PIERDE EL TURNO: se le salta y la fila sigue.
- Cuando los cadetes suben de año (febrero), cada fila vuelve a empezar desde el primero
  de Sistemas: se detecta porque el último que hizo guardia en ese año ya no es de ese año.
- Dentro del mismo año, la fila continúa donde quedó entre generaciones y gestiones. Para saber dónde
  quedó se usa DetalleGuardia.estudiante_rodillo (a quién le tocó según el rodillo),
  que no cambia con permutas ni reemplazos.
- Si un año tiene varios puestos el mismo día, se toman los siguientes de la fila.
- Un cadete nunca ocupa dos puestos el mismo día.
"""
import unicodedata
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import models, transaction

from .models import AusenciaLicencia, DetalleGuardia, EsquemaVigencia, Estudiante, GuardiaDia

ORDEN_CARRERAS = ['SISTEMAS', 'CIVIL', 'COMERCIAL']
ANIOS = Estudiante.ANIOS_CON_GUARDIA  # 5to año no hace guardia
MAX_DIAS_POR_GENERACION = 370


def _texto_para_ordenar(texto):
    """'ÁLVAREZ  muñoz' -> 'ALVAREZ MUNOZ' (sin tildes ni espacios dobles), para que Á no quede después de Z"""
    sin_tildes = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    return ' '.join(sin_tildes.upper().split())


def clave_fila(estudiante):
    """Posición del cadete dentro de la fila de su año"""
    carrera = estudiante.carrera.nombre
    orden_carrera = ORDEN_CARRERAS.index(carrera) if carrera in ORDEN_CARRERAS else len(ORDEN_CARRERAS)
    return (
        orden_carrera,
        _texto_para_ordenar(estudiante.apellidos),
        _texto_para_ordenar(estudiante.nombres),
        estudiante.id,
    )


def fila_del_anio(anio):
    estudiantes = Estudiante.objects.filter(anio=anio, activo=True).select_related('carrera')
    return sorted(estudiantes, key=clave_fila)


def ultimo_del_rodillo(anio, antes_de):
    """Último cadete al que le tocó guardia (según el rodillo) en ese año, antes de la fecha"""
    detalle = (
        DetalleGuardia.objects
        .filter(puesto__anio_requerido=anio, guardia__fecha__lt=antes_de)
        .select_related('estudiante_rodillo__carrera', 'estudiante__carrera')
        .order_by('-guardia__fecha', '-puesto__orden', '-id')
        .first()
    )
    if detalle is None:
        return None
    return _rodillo_de(detalle, anio)


def _rodillo_de(detalle, anio):
    """Cadete desde el cual continúa la fila. Si ese cadete ya no es de ese año (hubo
    promoción de año en febrero, o egresó), la fila tiene otra gente: se reinicia (None)."""
    estudiante = detalle.estudiante_rodillo or detalle.estudiante
    return estudiante if estudiante.anio == anio else None


def posicion_siguiente(fila, estudiante):
    """Índice del cadete que sigue a `estudiante` en la fila. Funciona aunque ese cadete
    ya no esté en la fila (dado de baja, cambió de año): se busca por su posición."""
    if estudiante is None or not fila:
        return 0
    clave = clave_fila(estudiante)
    for i, candidato in enumerate(fila):
        if clave_fila(candidato) > clave:
            return i
    return 0  # Era el último de la fila: vuelve a empezar


@dataclass
class ResultadoGeneracion:
    dias_generados: int = 0
    dias_ya_completos: int = 0
    dias_sin_esquema: list = field(default_factory=list)
    esquemas_sin_puestos: set = field(default_factory=set)
    puestos_vacios: list = field(default_factory=list)  # (fecha, puesto)
    turnos_perdidos: list = field(default_factory=list)  # (fecha, estudiante)


def _vigencia_para(vigencias, fecha):
    for v in vigencias:
        if v.fecha_desde <= fecha and (v.fecha_hasta is None or fecha <= v.fecha_hasta):
            return v
    return None


@transaction.atomic
def generar_rol(fecha_inicio, fecha_fin, usuario=None):
    """Genera (o completa) el rol de guardia entre dos fechas, ambas inclusive"""
    resultado = ResultadoGeneracion()
    filas = {anio: fila_del_anio(anio) for anio in ANIOS}
    punteros = {anio: posicion_siguiente(filas[anio], ultimo_del_rodillo(anio, fecha_inicio)) for anio in ANIOS}

    vigencias = list(
        EsquemaVigencia.objects.select_related('esquema')
        .filter(fecha_desde__lte=fecha_fin)
        .filter(models.Q(fecha_hasta__isnull=True) | models.Q(fecha_hasta__gte=fecha_inicio))
        .order_by('fecha_desde')
    )
    ausencias = list(
        AusenciaLicencia.objects.filter(estado='APROBADA', fecha_inicio__lte=fecha_fin, fecha_fin__gte=fecha_inicio)
        .values_list('estudiante_id', 'fecha_inicio', 'fecha_fin')
    )
    puestos_por_esquema = {}

    fecha = fecha_inicio
    while fecha <= fecha_fin:
        vigencia = _vigencia_para(vigencias, fecha)
        if vigencia is None:
            resultado.dias_sin_esquema.append(fecha)
            fecha += timedelta(days=1)
            continue

        esquema = vigencia.esquema
        if esquema.id not in puestos_por_esquema:
            puestos_por_esquema[esquema.id] = list(esquema.puesto_set.order_by('orden', 'id'))
        puestos = puestos_por_esquema[esquema.id]
        if not puestos:
            resultado.esquemas_sin_puestos.add(esquema.nombre)
            fecha += timedelta(days=1)
            continue

        guardia, _ = GuardiaDia.objects.get_or_create(fecha=fecha, defaults={'esquema': esquema, 'creado_por': usuario})
        existentes = {
            d.puesto_id: d for d in guardia.detalles.select_related('estudiante__carrera', 'estudiante_rodillo__carrera')
        }
        asignados_hoy = {d.estudiante_id for d in existentes.values()}
        no_disponibles = {
            est_id for est_id, desde, hasta in ausencias if desde <= fecha <= hasta
        }
        creados_hoy = 0

        for puesto in puestos:
            anio = puesto.anio_requerido
            fila = filas.get(anio, [])

            if puesto.id in existentes:
                # Puesto ya asignado (de una generación anterior): la fila continúa después de él
                punteros[anio] = posicion_siguiente(fila, _rodillo_de(existentes[puesto.id], anio))
                continue

            elegido = None
            for paso in range(len(fila)):
                idx = (punteros[anio] + paso) % len(fila)
                candidato = fila[idx]
                if candidato.id in asignados_hoy:
                    continue  # Ya tiene otro puesto hoy (solo pasa si el año tiene muy pocos cadetes)
                sin_habilitar = candidato.habilitado_desde and candidato.habilitado_desde > fecha
                if candidato.id in no_disponibles or sin_habilitar:
                    if candidato.id in no_disponibles:
                        resultado.turnos_perdidos.append((fecha, candidato))
                    continue  # Pierde el turno: la fila sigue con el siguiente
                elegido = candidato
                punteros[anio] = idx + 1
                break

            if elegido is None:
                resultado.puestos_vacios.append((fecha, puesto))
                continue

            DetalleGuardia.objects.create(
                guardia=guardia, puesto=puesto, estudiante=elegido,
                estudiante_rodillo=elegido, registrado_por=usuario,
            )
            asignados_hoy.add(elegido.id)
            creados_hoy += 1

        if creados_hoy:
            resultado.dias_generados += 1
        else:
            resultado.dias_ya_completos += 1
        fecha += timedelta(days=1)

    return resultado
