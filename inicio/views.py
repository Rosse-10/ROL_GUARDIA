import calendar
import os
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db import models, transaction  # Importante para models.Q
from django.db.models import ProtectedError
from django.http import FileResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    AusenciaOficialForm, CambiarClaveForm, EsquemaGuardiaForm, EstudianteForm, GestionForm,
    PuestoFormSet, SolicitudAusenciaForm, SolicitudCambioForm, VigenciaFormSet,
)
from .models import (
    Estudiante, Carrera, Gestion, EsquemaGuardia, EsquemaVigencia, Puesto,
    GuardiaDia, DetalleGuardia, AusenciaLicencia, Cambio, PromocionAnual,
)
from . import permutas as permutas_svc
from . import promocion as promocion_svc
from .permisos import es_oficial, solo_oficial
from .rodillo import MAX_DIAS_POR_GENERACION, generar_rol

def _guardias_con_detalles():
    """Guardias con sus puestos y cadetes ya cargados (pocas consultas, sin importar cuántos días)"""
    return GuardiaDia.objects.select_related('esquema').prefetch_related(
        models.Prefetch(
            'detalles',
            queryset=DetalleGuardia.objects.select_related('puesto', 'estudiante').order_by('puesto__orden'),
        )
    ).order_by('fecha')


@login_required
def home(request):
    hoy = timezone.localdate()  # Fecha de Bolivia (TIME_ZONE = America/La_Paz)

    # 1. Gestión activa actual
    gestion_activa = Gestion.objects.filter(activa=True).first()
    
    # 2. Esquema vigente según la fecha de hoy
    vigencia_actual = EsquemaVigencia.objects.filter(
        fecha_desde__lte=hoy
    ).filter(
        models.Q(fecha_hasta__gte=hoy) | models.Q(fecha_hasta__isnull=True)
    ).first()
    
    esquema_vigente = vigencia_actual.esquema if vigencia_actual else None

    # 3. Datos para la interfaz (Guardia de hoy, semana y mes)
    guardia_hoy = _guardias_con_detalles().filter(fecha=hoy).first()

    # Previsión de la semana (hoy y los próximos 6 días)
    guardias_semana = _guardias_con_detalles().filter(fecha__gte=hoy, fecha__lte=hoy + timedelta(days=6))

    # Rol del mes actual: del 1 al último día del mes
    inicio_mes = hoy.replace(day=1)
    fin_mes = hoy.replace(day=calendar.monthrange(hoy.year, hoy.month)[1])
    guardias_mes = _guardias_con_detalles().filter(fecha__gte=inicio_mes, fecha__lte=fin_mes)

    # 4. Resumen de solicitudes para el botón del panel (oficial o cadete)
    permutas_svc.vencer_pendientes()
    if es_oficial(request.user):
        solicitudes_pendientes = AusenciaLicencia.objects.filter(estado='PENDIENTE').count()
        cambios_pendientes = Cambio.objects.filter(estado='ESPERA_OFICIAL').count()
    else:
        estudiante = estudiante_de_usuario(request.user)
        solicitudes_pendientes = estudiante.ausencias.filter(estado='PENDIENTE').count() if estudiante else 0
        cambios_pendientes = estudiante.cambios_recibidos.filter(estado='ESPERA_CADETE').count() if estudiante else 0

    contexto = {
        'hoy': hoy,
        'solicitudes_pendientes': solicitudes_pendientes,
        'cambios_pendientes': cambios_pendientes,
        'gestion_activa': gestion_activa,
        'esquema_vigente': esquema_vigente,
        'guardia_hoy': guardia_hoy,
        'guardias_semana': guardias_semana,
        'guardias_mes': guardias_mes,
        'inicio_mes': inicio_mes,
    }
    return render(request, 'home.html', contexto)

@solo_oficial
def lista_estudiantes(request):
    """Muestra la lista de estudiantes organizada estrictamente por Carrera y Año"""
    carreras = Carrera.objects.all()
    
    datos_agrupados = {}
    for c in carreras:
        datos_agrupados[c] = {
            anio: Estudiante.objects.filter(carrera=c, anio=anio, egresado=False)
            .select_related('usuario').order_by('apellidos', 'nombres')
            for anio, _ in Estudiante.OPCIONES_ANIO
        }
    egresados = Estudiante.objects.filter(egresado=True).select_related('carrera').order_by('carrera__nombre', 'apellidos')

    return render(request, 'estudiantes/lista.html', {'datos_agrupados': datos_agrupados, 'egresados': egresados})

@solo_oficial
def nuevo_estudiante(request):
    if request.method == 'POST':
        form = EstudianteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Estudiante registrado exitosamente.")
            return redirect('lista_estudiantes')
    else:
        form = EstudianteForm()
    return render(request, 'estudiantes/form_estudiante.html', {'form': form, 'titulo': 'Nuevo Estudiante'})

@solo_oficial
def editar_estudiante(request, id):
    estudiante = get_object_or_404(Estudiante, id=id)
    if request.method == 'POST':
        form = EstudianteForm(request.POST, instance=estudiante)
        if form.is_valid():
            form.save()
            return redirect('lista_estudiantes')
    else:
        form = EstudianteForm(instance=estudiante)
    return render(request, 'estudiantes/form_estudiante.html', {'form': form, 'titulo': 'Editar Estudiante'})

@solo_oficial
def eliminar_estudiante(request, id):
    estudiante = get_object_or_404(Estudiante, id=id)
    if request.method == 'POST':
        try:
            estudiante.delete()
        except ProtectedError:
            messages.error(
                request,
                f"No se puede eliminar a {estudiante.apellidos}, {estudiante.nombres} porque tiene guardias "
                "asignadas. Márquelo como inactivo para sacarlo de las próximas guardias."
            )
            return redirect('lista_estudiantes')
        messages.success(request, "Estudiante eliminado.")
        return redirect('lista_estudiantes')
    return render(request, 'estudiantes/confirmar_eliminar.html', {'estudiante': estudiante})

# --- GESTIONES ACADÉMICAS (DESDE LA UI) ---

@solo_oficial
def lista_gestiones(request):
    """Permite listar todas las gestiones académicas"""
    gestiones = Gestion.objects.all().order_by('-fecha_inicio')
    return render(request, 'guardias/lista_gestiones.html', {'gestiones': gestiones})

@solo_oficial
def nueva_gestion(request):
    """Permite registrar una nueva gestión académica"""
    if request.method == 'POST':
        form = GestionForm(request.POST)
        if form.is_valid():
            if form.cleaned_data.get('activa'):
                Gestion.objects.filter(activa=True).update(activa=False)
            form.save()
            messages.success(request, "Gestión registrada exitosamente.")
            return redirect('lista_gestiones')
    else:
        form = GestionForm()
    return render(request, 'configuracion/form_gestion.html', {'form': form, 'titulo': 'Nueva Gestión'})

@login_required
def cambiar_clave(request):
    """Cambio de contraseña. Es obligatorio para el cadete mientras use la clave inicial."""
    estudiante = getattr(request.user, 'estudiante', None)
    obligatorio = estudiante is not None and estudiante.debe_cambiar_clave

    if request.method == 'POST':
        form = CambiarClaveForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Mantener la sesión abierta tras el cambio
            if estudiante is not None:
                Estudiante.objects.filter(pk=estudiante.pk).update(debe_cambiar_clave=False)
            messages.success(request, "Su contraseña fue cambiada correctamente.")
            return redirect('home')
    else:
        form = CambiarClaveForm(request.user)
    return render(request, 'registration/cambiar_clave.html', {'form': form, 'obligatorio': obligatorio})


@solo_oficial
@require_POST
def restablecer_clave(request, id):
    """El oficial devuelve la contraseña del cadete a su primer apellido"""
    estudiante = get_object_or_404(Estudiante.objects.select_related('usuario'), id=id)
    if estudiante.restablecer_clave():
        messages.success(
            request,
            f"Clave de {estudiante.apellidos}, {estudiante.nombres} restablecida. "
            f"Usuario: {estudiante.usuario.username} — contraseña: su primer apellido en minúsculas. "
            "Deberá cambiarla al ingresar."
        )
    else:
        messages.error(request, "Ese estudiante todavía no tiene cuenta: cargue su C.I. para crearla.")
    return redirect('lista_estudiantes')

def _leer_fecha(valor):
    try:
        return datetime.strptime(valor or '', '%Y-%m-%d').date()
    except ValueError:
        return None


def _informar_generacion(request, resultado):
    """Traduce el resultado del rodillo a mensajes para el oficial"""
    if resultado.dias_generados:
        messages.success(request, f"Rodillo aplicado: {resultado.dias_generados} día(s) de guardia generados.")
    if resultado.dias_ya_completos:
        messages.info(request, f"{resultado.dias_ya_completos} día(s) ya estaban generados y no se modificaron.")
    if resultado.esquemas_sin_puestos:
        messages.error(
            request,
            f"El esquema {', '.join(sorted(resultado.esquemas_sin_puestos))} no tiene puestos configurados; "
            "esos días no se generaron. Cargue sus puestos desde el panel de administración."
        )
    if resultado.dias_sin_esquema:
        dias = resultado.dias_sin_esquema
        messages.warning(
            request,
            f"{len(dias)} día(s) sin esquema vigente (del {dias[0]:%d/%m/%Y} al {dias[-1]:%d/%m/%Y}); no se generaron."
        )
    if resultado.puestos_vacios:
        ejemplos = ', '.join(f"{p.nombre} el {f:%d/%m}" for f, p in resultado.puestos_vacios[:5])
        messages.warning(
            request,
            f"{len(resultado.puestos_vacios)} puesto(s) quedaron sin cadete disponible ({ejemplos}...). Asígnelos manualmente."
        )
    if resultado.turnos_perdidos:
        ejemplos = ', '.join(f"{e.apellidos} ({f:%d/%m})" for f, e in resultado.turnos_perdidos[:5])
        messages.info(request, f"Perdieron su turno por licencia/permiso: {ejemplos}.")


@solo_oficial
def planificacion_guardias(request):
    """Vista principal para la administración y generación del rodillo de guardias"""
    if request.method == 'POST':
        fecha = _leer_fecha(request.POST.get('fecha_generar'))
        if fecha is None:
            messages.error(request, "Indique una fecha válida.")
        else:
            _informar_generacion(request, generar_rol(fecha, fecha, request.user))
        return redirect('planificacion_guardias')

    guardias_generadas = GuardiaDia.objects.select_related('esquema').prefetch_related(
        models.Prefetch('detalles', queryset=DetalleGuardia.objects.select_related('estudiante', 'puesto').order_by('puesto__orden'))
    ).order_by('-fecha')
    return render(request, 'guardias/planificacion.html', {'guardias': guardias_generadas})


@solo_oficial
@require_POST
def generar_rango_guardias(request):
    """Genera el rol de guardia para un rango de fechas con el rodillo (ver inicio/rodillo.py)"""
    f_inicio = _leer_fecha(request.POST.get('fecha_inicio'))
    f_fin = _leer_fecha(request.POST.get('fecha_fin'))

    if f_inicio is None or f_fin is None:
        messages.error(request, "Indique fechas de inicio y fin válidas.")
    elif f_inicio > f_fin:
        messages.error(request, "La fecha de inicio no puede ser posterior a la fecha de fin.")
    elif (f_fin - f_inicio).days + 1 > MAX_DIAS_POR_GENERACION:
        messages.error(request, f"Como máximo se pueden generar {MAX_DIAS_POR_GENERACION} días de una vez.")
    else:
        _informar_generacion(request, generar_rol(f_inicio, f_fin, request.user))
    return redirect('planificacion_guardias')


@solo_oficial
def editar_gestion(request, id):
    gestion = get_object_or_404(Gestion, id=id)
    if request.method == 'POST':
        form = GestionForm(request.POST, instance=gestion)
        if form.is_valid():
            if form.cleaned_data.get('activa'):
                Gestion.objects.filter(activa=True).exclude(id=id).update(activa=False)
            form.save()
            messages.success(request, "¡Gestión actualizada exitosamente!")
            return redirect('lista_gestiones')
    else:
        form = GestionForm(instance=gestion)
    return render(request, 'configuracion/form_gestion.html', {'form': form, 'titulo': 'Editar Gestión Académica'})

@solo_oficial
@require_POST
def eliminar_gestion(request, id):
    gestion = get_object_or_404(Gestion, id=id)
    try:
        gestion.delete()
    except ProtectedError:
        messages.error(request, f"No se puede eliminar la gestión {gestion} porque tiene datos asociados.")
        return redirect('lista_gestiones')
    messages.success(request, "¡Gestión eliminada exitosamente!")
    return redirect('lista_gestiones')

@solo_oficial
def lista_esquemas(request):
    hoy = timezone.localdate()
    esquemas = list(EsquemaGuardia.objects.prefetch_related(
        models.Prefetch('puesto_set', queryset=Puesto.objects.order_by('orden', 'id')),
        models.Prefetch('esquemavigencia_set', queryset=EsquemaVigencia.objects.order_by('fecha_desde')),
    ).order_by('nombre'))
    for e in esquemas:
        e.vigente_hoy = any(
            v.fecha_desde <= hoy and (v.fecha_hasta is None or hoy <= v.fecha_hasta)
            for v in e.esquemavigencia_set.all()
        )
    return render(request, 'configuracion/lista_esquemas.html', {'esquemas': esquemas, 'hoy': hoy})


def _formulario_esquema(request, esquema, titulo):
    """Alta/edición de un esquema junto con sus puestos y sus vigencias en una sola pantalla"""
    datos = request.POST if request.method == 'POST' else None
    form = EsquemaGuardiaForm(datos, instance=esquema)
    puestos = PuestoFormSet(datos, instance=esquema, prefix='puestos')
    vigencias = VigenciaFormSet(datos, instance=esquema, prefix='vigencias')

    if request.method == 'POST':
        if form.is_valid() and puestos.is_valid() and vigencias.is_valid():
            with transaction.atomic():
                esquema = form.save()
                puestos.instance = vigencias.instance = esquema
                puestos.save()
                vigencias.save()
            messages.success(request, f"Esquema «{esquema.nombre}» guardado correctamente.")
            return redirect('lista_esquemas')
        messages.error(request, "Revise los datos marcados en el formulario.")

    return render(request, 'configuracion/form_esquema.html', {
        'form': form, 'puestos': puestos, 'vigencias': vigencias, 'titulo': titulo,
    })


@solo_oficial
def nuevo_esquema(request):
    return _formulario_esquema(request, EsquemaGuardia(), 'Nuevo Esquema de Guardia')


@solo_oficial
def editar_esquema(request, id):
    return _formulario_esquema(request, get_object_or_404(EsquemaGuardia, id=id), 'Editar Esquema de Guardia')


@solo_oficial
@require_POST
def eliminar_esquema(request, id):
    esquema = get_object_or_404(EsquemaGuardia, id=id)
    try:
        esquema.delete()
    except ProtectedError:
        messages.error(
            request,
            f"No se puede eliminar el esquema {esquema.nombre} porque ya se usó en guardias generadas. "
            "Márquelo como inactivo en su lugar."
        )
        return redirect('lista_esquemas')
    messages.success(request, "Esquema eliminado exitosamente.")
    return redirect('lista_esquemas')


# ==========================================================
# AUSENCIAS, LICENCIAS Y PERMISOS
# ==========================================================

def estudiante_de_usuario(user):
    """Devuelve el Estudiante vinculado a la cuenta que inició sesión (o None)"""
    estudiante = getattr(user, 'estudiante', None)
    if estudiante is None and user.is_authenticated:
        # Respaldo para cuentas creadas antes del vínculo usuario <-> estudiante
        estudiante = Estudiante.objects.filter(ci=user.username, usuario__isnull=True).first()
        if estudiante:
            estudiante.usuario = user
            Estudiante.objects.filter(pk=estudiante.pk).update(usuario=user)
    return estudiante


def _avisar_guardias_afectadas(request, ausencia, cantidad):
    if cantidad:
        messages.warning(
            request,
            f"{cantidad} guardia(s) de {ausencia.estudiante.apellidos} quedaron marcadas como "
            f"'{dict(DetalleGuardia.OPCIONES_ASISTENCIA)[ausencia.estado_asistencia]}'. "
            "Recuerde asignar un reemplazo para esos puestos."
        )


@solo_oficial
def gestion_ausencias(request):
    """Panel del Oficial Administrador: registrar ausencias y aprobar/rechazar solicitudes de los cadetes"""
    form = AusenciaOficialForm()

    if request.method == 'POST':
        accion = request.POST.get('accion')

        # Acción 1: el oficial registra directamente una ausencia (queda aprobada)
        if accion == 'registrar':
            form = AusenciaOficialForm(request.POST, request.FILES)
            if form.is_valid():
                with transaction.atomic():
                    ausencia = form.save(commit=False)
                    ausencia.estado = 'APROBADA'
                    ausencia.registrado_por = request.user
                    ausencia.resuelto_por = request.user
                    ausencia.fecha_resolucion = timezone.now()
                    ausencia.save()
                    afectadas = ausencia.aplicar_a_guardias(request.user)
                messages.success(request, "¡Ausencia o licencia registrada y aprobada correctamente!")
                _avisar_guardias_afectadas(request, ausencia, afectadas)
                return redirect('gestion_ausencias')
            messages.error(request, "Revise los datos del formulario de registro.")

        # Acción 2: aprobar o rechazar una solicitud enviada por un cadete
        elif accion in ('aprobar', 'rechazar'):
            solicitud = get_object_or_404(AusenciaLicencia, id=request.POST.get('solicitud_id'))
            observacion = request.POST.get('observacion', '').strip()

            if solicitud.estado != 'PENDIENTE':
                messages.error(request, "Esa solicitud ya fue resuelta anteriormente.")
                return redirect('gestion_ausencias')
            if accion == 'rechazar' and not observacion:
                messages.error(request, "Para rechazar una solicitud debe indicar el motivo del rechazo.")
                return redirect('gestion_ausencias')

            with transaction.atomic():
                solicitud.estado = 'APROBADA' if accion == 'aprobar' else 'RECHAZADA'
                solicitud.resuelto_por = request.user
                solicitud.fecha_resolucion = timezone.now()
                solicitud.observacion_oficial = observacion
                solicitud.save()
                afectadas = solicitud.aplicar_a_guardias(request.user) if accion == 'aprobar' else 0

            nombre = f"{solicitud.estudiante.apellidos}, {solicitud.estudiante.nombres}"
            if accion == 'aprobar':
                messages.success(request, f"Solicitud de {nombre} APROBADA.")
                _avisar_guardias_afectadas(request, solicitud, afectadas)
            else:
                messages.warning(request, f"Solicitud de {nombre} RECHAZADA.")
            return redirect('gestion_ausencias')

    base = AusenciaLicencia.objects.select_related(
        'estudiante', 'estudiante__carrera', 'registrado_por', 'resuelto_por'
    )
    pendientes = base.filter(estado='PENDIENTE').order_by('fecha_solicitud', 'id')
    historial = base.exclude(estado='PENDIENTE').order_by('-fecha_resolucion', '-fecha_inicio')

    return render(request, 'guardias/ausencias.html', {
        'form': form,
        'pendientes': pendientes,
        'historial': historial,
    })


@login_required
def mis_solicitudes_ausencia(request):
    """Panel del cadete: enviar solicitudes de licencia/ausencia y ver su estado"""
    estudiante = estudiante_de_usuario(request.user)
    if estudiante is None:
        messages.error(request, "Su cuenta no está vinculada a ningún estudiante. Consulte con el oficial.")
        return redirect('home')

    if request.method == 'POST':
        form = SolicitudAusenciaForm(request.POST, request.FILES, estudiante=estudiante)
        if form.is_valid():
            solicitud = form.save(commit=False)
            solicitud.estudiante = estudiante
            solicitud.estado = 'PENDIENTE'
            solicitud.registrado_por = request.user
            solicitud.save()
            messages.success(request, "Su solicitud fue enviada y quedó PENDIENTE de aprobación por el oficial.")
            return redirect('mis_solicitudes_ausencia')
        messages.error(request, "Revise los datos del formulario.")
    else:
        form = SolicitudAusenciaForm(estudiante=estudiante)

    solicitudes = estudiante.ausencias.select_related('resuelto_por').annotate(
        guardias_marcadas=models.Count('detalles_afectados')
    ).order_by('-fecha_solicitud', '-id')

    # Guardias próximas del cadete, para que sepa qué fechas está justificando
    proximas_guardias = DetalleGuardia.objects.filter(
        estudiante=estudiante, guardia__fecha__gte=timezone.localdate()
    ).select_related('guardia', 'puesto').order_by('guardia__fecha')[:10]

    return render(request, 'guardias/mis_ausencias.html', {
        'estudiante': estudiante,
        'form': form,
        'solicitudes': solicitudes,
        'proximas_guardias': proximas_guardias,
    })

# ==========================================================
# GESTIÓN DE CAMBIOS Y PERMUTAS
# ADMINISTRADOR: FORMULARIO + HISTORIAL + APROBACIONES
# ESTUDIANTE: SOLAMENTE FORMULARIO DE SOLICITUD
# ==========================================================

@login_required
def ver_justificativo(request, id):
    """Entrega el archivo justificativo solo al oficial o al cadete dueño de la solicitud"""
    ausencia = get_object_or_404(AusenciaLicencia.objects.select_related('estudiante'), id=id)
    es_dueno = ausencia.estudiante.usuario_id == request.user.id
    if not (es_oficial(request.user) or es_dueno) or not ausencia.justificativo:
        raise Http404("Justificativo no disponible")
    try:
        archivo = ausencia.justificativo.open('rb')
    except FileNotFoundError:
        raise Http404("El archivo ya no existe en el servidor")
    return FileResponse(archivo, filename=os.path.basename(ausencia.justificativo.name))

@login_required
def gestion_permutas(request):
    """Cambios y permutas. Cadete: solicitar, responder lo que le piden y cancelar.
    Oficial: registrar cambios directos y aprobar/rechazar los que aceptó el otro cadete."""
    es_admin = es_oficial(request.user)
    estudiante = None if es_admin else estudiante_de_usuario(request.user)
    if not es_admin and estudiante is None:
        messages.error(request, "Su cuenta no está vinculada a ningún estudiante. Consulte con el oficial.")
        return redirect('home')

    permutas_svc.vencer_pendientes()
    form = SolicitudCambioForm(estudiante=estudiante, por_oficial=es_admin)

    if request.method == 'POST':
        accion = request.POST.get('accion')
        try:
            if accion == 'crear':
                form = SolicitudCambioForm(request.POST, estudiante=estudiante, por_oficial=es_admin)
                if form.is_valid():
                    d = form.cleaned_data
                    cambio = permutas_svc.solicitar(
                        request.user, d['tipo'], d['detalle_origen'], d.get('detalle_destino'),
                        d.get('reemplazante'), d['motivo'], por_oficial=es_admin,
                    )
                    if es_admin:
                        messages.success(request, f"{cambio.get_tipo_display()} registrada y aplicada al rol de guardia.")
                    else:
                        messages.success(
                            request,
                            f"Solicitud enviada. Ahora {cambio.estudiante_destino.apellidos} debe aceptarla "
                            "y luego el oficial la aprobará."
                        )
                    return redirect('gestion_permutas')
                messages.error(request, "Revise los datos de la solicitud.")

            elif accion in ('aceptar', 'rechazar_cadete') and estudiante is not None:
                cambio = get_object_or_404(Cambio, id=request.POST.get('cambio_id'), estudiante_destino=estudiante)
                permutas_svc.responder_cadete(cambio, estudiante, accion == 'aceptar',
                                              request.POST.get('respuesta', '').strip())
                if accion == 'aceptar':
                    messages.success(request, "Aceptó la solicitud. Ahora queda esperando la aprobación del oficial.")
                else:
                    messages.warning(request, "Rechazó la solicitud.")
                return redirect('gestion_permutas')

            elif accion == 'cancelar' and estudiante is not None:
                cambio = get_object_or_404(Cambio, id=request.POST.get('cambio_id'), estudiante_origen=estudiante)
                permutas_svc.cancelar(cambio, estudiante)
                messages.info(request, "Solicitud cancelada.")
                return redirect('gestion_permutas')

            elif accion in ('aprobar', 'rechazar') and es_admin:
                cambio = get_object_or_404(Cambio, id=request.POST.get('cambio_id'))
                permutas_svc.resolver_oficial(cambio, request.user, accion == 'aprobar',
                                              request.POST.get('observacion', '').strip())
                if accion == 'aprobar':
                    messages.success(request, f"{cambio.get_tipo_display()} #{cambio.pk} aprobada y aplicada al rol.")
                else:
                    messages.warning(request, f"{cambio.get_tipo_display()} #{cambio.pk} rechazada.")
                return redirect('gestion_permutas')
            else:
                messages.error(request, "Acción no permitida.")
                return redirect('gestion_permutas')
        except permutas_svc.CambioInvalido as error:
            messages.error(request, str(error))
            return redirect('gestion_permutas')

    cambios = Cambio.objects.select_related(
        'detalle_origen__guardia', 'detalle_origen__puesto', 'detalle_destino__guardia', 'detalle_destino__puesto',
        'estudiante_origen', 'estudiante_destino', 'oficial',
    )
    if es_admin:
        contexto = {
            'por_aprobar': cambios.filter(estado='ESPERA_OFICIAL').order_by('detalle_origen__guardia__fecha'),
            'esperando_cadete': cambios.filter(estado='ESPERA_CADETE'),
            'historial': cambios.exclude(estado__in=Cambio.ESTADOS_ABIERTOS)[:100],
        }
    else:
        contexto = {
            'me_pidieron': cambios.filter(estudiante_destino=estudiante, estado='ESPERA_CADETE'),
            'mis_solicitudes': cambios.filter(estudiante_origen=estudiante)[:50],
            'recibidas': cambios.filter(estudiante_destino=estudiante).exclude(estado='ESPERA_CADETE')[:50],
            'mis_guardias': DetalleGuardia.objects.filter(
                estudiante=estudiante, guardia__fecha__gte=timezone.localdate()
            ).select_related('guardia', 'puesto').order_by('guardia__fecha')[:10],
        }
    contexto.update({'es_admin': es_admin, 'estudiante_actual': estudiante, 'form': form})
    return render(request, 'guardias/permutas.html', contexto)


# ==========================================================
# PROMOCIÓN DE AÑO (ver inicio/promocion.py)
# ==========================================================

@solo_oficial
def promocion_anio(request):
    """Vista previa didáctica de la promoción de año y su confirmación"""
    if request.method == 'POST':
        if not request.POST.get('confirmo'):
            messages.error(request, "Marque la casilla de confirmación para realizar la promoción.")
            return redirect('promocion_anio')
        repiten = [int(i) for i in request.POST.getlist('repite') if i.isdigit()]
        promocion = promocion_svc.promover(request.user, repiten)
        r = promocion.resumen
        messages.success(
            request,
            f"¡Promoción realizada! Egresaron {r['egresados']} cadetes de 5to año; "
            f"{r['a_5to']} pasaron a 5to, {r['a_4to']} a 4to, {r['a_3ro']} a 3ro y {r['a_2do']} a 2do"
            + (f"; {r['repiten']} repiten el año." if r['repiten'] else ".")
            + " Ahora registre a los nuevos cadetes de 1er año."
        )
        return redirect('lista_estudiantes')

    ultima = promocion_svc.ultima_promocion()
    reciente = bool(ultima and not ultima.deshecha_en and (timezone.now() - ultima.realizada_en).days < 180)
    return render(request, 'estudiantes/promocion.html', {
        'pasos': promocion_svc.vista_previa(),
        'ultima': ultima,
        'reciente': reciente,
        'guardias_futuras': promocion_svc.guardias_futuras_generadas(),
    })


@solo_oficial
@require_POST
def deshacer_promocion(request, id):
    promocion = get_object_or_404(PromocionAnual, id=id)
    if promocion.deshecha_en or promocion != promocion_svc.ultima_promocion():
        messages.error(request, "Solo se puede deshacer la última promoción realizada.")
        return redirect('promocion_anio')
    restaurados = promocion_svc.deshacer(promocion)
    messages.success(request, f"Promoción deshecha: {restaurados} cadetes volvieron a su año y estado anteriores.")
    return redirect('lista_estudiantes')
