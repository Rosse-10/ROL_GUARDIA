import os
from functools import wraps

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import models, transaction  # Importante para models.Q
from django.http import FileResponse, Http404
from .models import Estudiante, Carrera, Gestion, EsquemaGuardia, EsquemaVigencia, Puesto, GuardiaDia, DetalleGuardia, AusenciaLicencia,Cambio
from .forms import EstudianteForm, GestionForm, EsquemaGuardiaForm, SolicitudAusenciaForm, AusenciaOficialForm
from datetime import datetime, timedelta
from django.contrib import messages
from django.utils import timezone
from .models import Puesto, GuardiaDia, DetalleGuardia
import random

def asegurar_carreras():
    """Garantiza la existencia de las 3 carreras oficiales de la EMI del Trópico"""
    for codigo, nombre_completo in Carrera.OPCIONES_CARRERA:
        Carrera.objects.get_or_create(nombre=codigo)

@login_required
def home(request):
    asegurar_carreras()
    hoy = timezone.now().date()
    
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
    guardia_hoy = GuardiaDia.objects.filter(fecha=hoy).first()

    # Previsión de la semana (desde hoy hasta los próximos 7 días)
    fin_semana = hoy + timedelta(days=7)
    guardias_semana = GuardiaDia.objects.filter(fecha__gte=hoy, fecha__lte=fin_semana).order_by('fecha')

    # Rol completo del mes actual
    inicio_mes = hoy.replace(day=1)
    guardias_mes = GuardiaDia.objects.filter(fecha__gte=inicio_mes).order_by('fecha')

    # 4. Resumen de solicitudes para el botón del panel (oficial o cadete)
    if request.user.is_superuser:
        solicitudes_pendientes = AusenciaLicencia.objects.filter(estado='PENDIENTE').count()
    else:
        estudiante = estudiante_de_usuario(request.user)
        solicitudes_pendientes = estudiante.ausencias.filter(estado='PENDIENTE').count() if estudiante else 0

    contexto = {
        'hoy': hoy,
        'solicitudes_pendientes': solicitudes_pendientes,
        'gestion_activa': gestion_activa,
        'esquema_vigente': esquema_vigente,
        'guardia_hoy': guardia_hoy,
        'guardias_semana': guardias_semana,
        'guardias_mes': guardias_mes,
    }
    return render(request, 'home.html', contexto)

@login_required
def lista_estudiantes(request):
    """Muestra la lista de estudiantes organizada estrictamente por Carrera y Año"""
    asegurar_carreras()
    carreras = Carrera.objects.all()
    
    datos_agrupados = {}
    for c in carreras:
        datos_agrupados[c] = {
            1: Estudiante.objects.filter(carrera=c, anio=1).order_by('apellidos', 'nombres'),
            2: Estudiante.objects.filter(carrera=c, anio=2).order_by('apellidos', 'nombres'),
            3: Estudiante.objects.filter(carrera=c, anio=3).order_by('apellidos', 'nombres'),
            4: Estudiante.objects.filter(carrera=c, anio=4).order_by('apellidos', 'nombres'),
        }
    
    return render(request, 'estudiantes/lista.html', {'datos_agrupados': datos_agrupados})

@login_required
def nuevo_estudiante(request):
    asegurar_carreras()
    if request.method == 'POST':
        form = EstudianteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Estudiante registrado exitosamente.")
            return redirect('lista_estudiantes')
    else:
        form = EstudianteForm()
    return render(request, 'estudiantes/form_estudiante.html', {'form': form, 'titulo': 'Nuevo Estudiante'})

@login_required
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

@login_required
def eliminar_estudiante(request, id):
    estudiante = get_object_or_404(Estudiante, id=id)
    if request.method == 'POST':
        estudiante.delete()
        return redirect('lista_estudiantes')
    return render(request, 'estudiantes/confirmar_eliminar.html', {'estudiante': estudiante})

# --- GESTIONES ACADÉMICAS (DESDE LA UI) ---

@login_required
def lista_gestiones(request):
    """Permite listar todas las gestiones académicas"""
    gestiones = Gestion.objects.all().order_by('-fecha_inicio')
    return render(request, 'guardias/lista_gestiones.html', {'gestiones': gestiones})

@login_required
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

def registro(request):
    return render(request, 'registration/registro.html')

@login_required
def planificacion_guardias(request):
    """Vista principal para la administración y generación del rodillo de guardias"""
    if request.method == 'POST':
        fecha_str = request.POST.get('fecha_generar')
        if fecha_str:
            fecha_evaluar = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            
            vigencia = EsquemaVigencia.objects.filter(
                fecha_desde__lte=fecha_evaluar
            ).filter(
                models.Q(fecha_hasta__gte=fecha_evaluar) | models.Q(fecha_hasta__isnull=True)
            ).first()
            
            if not vigencia:
                messages.error(request, f"No existe un esquema de guardia vigente para la fecha {fecha_evaluar}.")
            else:
                guardia_dia, creada = GuardiaDia.objects.get_or_create(
                    fecha=fecha_evaluar, 
                    defaults={'esquema': vigencia.esquema, 'creado_por': request.user}
                )

                puestos = Puesto.objects.filter(esquema=vigencia.esquema)
                for puesto in puestos:
                    if not DetalleGuardia.objects.filter(guardia=guardia_dia, puesto=puesto).exists():
                        asignados_hoy = DetalleGuardia.objects.filter(guardia=guardia_dia).values_list('estudiante_id', flat=True)

                        # 1. Obtener IDs de estudiantes con ausencia/licencia activa en la fecha evaluada
                        ausentes_hoy = AusenciaLicencia.objects.filter(
                            estado='APROBADA',
                            fecha_inicio__lte=fecha_evaluar,
                            fecha_fin__gte=fecha_evaluar
                        ).values_list('estudiante_id', flat=True)

                        # 2. Filtrar candidatos excluyendo asignados hoy Y ausentes
                        candidatos = Estudiante.objects.filter(
                            anio=puesto.anio_requerido,
                            activo=True
                        ).exclude(
                            id__in=asignados_hoy
                        ).exclude(
                            id__in=ausentes_hoy
                        )

                        if candidatos.exists():
                            estudiante_elegido = random.choice(list(candidatos))
                            DetalleGuardia.objects.create(
                                guardia=guardia_dia,
                                puesto=puesto,
                                estudiante=estudiante_elegido,
                                registrado_por=request.user
                            )
                
                messages.success(request, f"¡Rodillo generado con éxito para el {fecha_evaluar}!")
                return redirect('planificacion_guardias')

    guardias_generadas = GuardiaDia.objects.all().order_by('-fecha')
    return render(request, 'guardias/planificacion.html', {'guardias': guardias_generadas})

@login_required
def generar_rango_guardias(request):
    """Genera el rodillo de guardias masivo para un rango de fechas (Inicio a Fin)"""
    if request.method == 'POST':
        fecha_inicio_str = request.POST.get('fecha_inicio')
        fecha_fin_str = request.POST.get('fecha_fin')
        
        if fecha_inicio_str and fecha_fin_str:
            f_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            f_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
            
            if f_inicio > f_fin:
                messages.error(request, "La fecha de inicio no puede ser posterior a la fecha de fin.")
                return redirect('planificacion_guardias')
            
            delta = timedelta(days=1)
            f_actual = f_inicio
            dias_generados = 0
            
            while f_actual <= f_fin:
                vigencia = EsquemaVigencia.objects.filter(
                    fecha_desde__lte=f_actual
                ).filter(
                    models.Q(fecha_hasta__gte=f_actual) | models.Q(fecha_hasta__isnull=True)
                ).first()
                
                if vigencia:
                    guardia_dia, creada = GuardiaDia.objects.get_or_create(
                        fecha=f_actual, 
                        defaults={'esquema': vigencia.esquema, 'creado_por': request.user}
                    )

                    puestos = Puesto.objects.filter(esquema=vigencia.esquema)
                    for puesto in puestos:
                        if not DetalleGuardia.objects.filter(guardia=guardia_dia, puesto=puesto).exists():
                            asignados_hoy = DetalleGuardia.objects.filter(guardia=guardia_dia).values_list('estudiante_id', flat=True)
                            
                            # 1. Obtener IDs de estudiantes con ausencia/licencia activa en la fecha evaluada (f_actual)
                            ausentes_hoy = AusenciaLicencia.objects.filter(
                                estado='APROBADA',
                                fecha_inicio__lte=f_actual,
                                fecha_fin__gte=f_actual
                            ).values_list('estudiante_id', flat=True)
                            
                            # 2. Filtrar candidatos excluyendo asignados hoy Y ausentes
                            candidatos = Estudiante.objects.filter(
                                anio=puesto.anio_requerido,
                                activo=True
                            ).exclude(
                                id__in=asignados_hoy
                            ).exclude(
                                id__in=ausentes_hoy
                            )
                            
                            if candidatos.exists():
                                estudiante_elegido = random.choice(list(candidatos))
                                DetalleGuardia.objects.create(
                                    guardia=guardia_dia,
                                    puesto=puesto,
                                    estudiante=estudiante_elegido,
                                    registrado_por=request.user
                                )
                    dias_generados += 1
                
                f_actual += delta
                
            messages.success(request, f"¡Rol secuencial generado con éxito! Se procesaron {dias_generados} días de servicio.")
            return redirect('planificacion_guardias')
            
    return redirect('planificacion_guardias')



@login_required
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

@login_required
def eliminar_gestion(request, id):
    gestion = get_object_or_404(Gestion, id=id)
    gestion.delete()
    messages.success(request, "¡Gestión eliminada exitosamente!")
    return redirect('lista_gestiones')

@login_required
def lista_esquemas(request):
    esquemas = EsquemaGuardia.objects.all()
    return render(request, 'configuracion/lista_esquemas.html', {'esquemas': esquemas})

@login_required
def nuevo_esquema(request):
    if request.method == 'POST':
        form = EsquemaGuardiaForm(request.POST)
        if form.is_valid():
            if form.cleaned_data.get('activo'):
                EsquemaGuardia.objects.filter(activo=True).update(activo=False)
            form.save()
            messages.success(request, "Esquema de guardia registrado exitosamente.")
            return redirect('lista_esquemas')
    else:
        form = EsquemaGuardiaForm()
    return render(request, 'configuracion/form_esquema.html', {'form': form, 'titulo': 'Nuevo Esquema de Guardia'})

@login_required
def editar_esquema(request, id):
    esquema = get_object_or_404(EsquemaGuardia, id=id)
    if request.method == 'POST':
        form = EsquemaGuardiaForm(request.POST, instance=esquema)
        if form.is_valid():
            if form.cleaned_data.get('activo'):
                EsquemaGuardia.objects.filter(activo=True).exclude(id=id).update(activo=False)
            form.save()
            messages.success(request, "Esquema actualizado exitosamente.")
            return redirect('lista_esquemas')
    else:
        form = EsquemaGuardiaForm(instance=esquema)
    return render(request, 'configuracion/form_esquema.html', {'form': form, 'titulo': 'Editar Esquema de Guardia'})

@login_required
def eliminar_esquema(request, id):
    esquema = get_object_or_404(EsquemaGuardia, id=id)
    esquema.delete()
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


def solo_oficial(vista):
    """Restringe una vista al Oficial Administrador (superusuario)"""
    @wraps(vista)
    @login_required
    def envoltura(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "No tiene permisos para acceder a ese módulo.")
            return redirect('home')
        return vista(request, *args, **kwargs)
    return envoltura


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
    if not (request.user.is_superuser or es_dueno) or not ausencia.justificativo:
        raise Http404("Justificativo no disponible")
    try:
        archivo = ausencia.justificativo.open('rb')
    except FileNotFoundError:
        raise Http404("El archivo ya no existe en el servidor")
    return FileResponse(archivo, filename=os.path.basename(ausencia.justificativo.name))

@login_required
def gestion_permutas(request):

    # ==========================================
    # IDENTIFICAR AL USUARIO Y SU ROL
    # ==========================================

    es_admin = request.user.is_superuser
    estudiante_actual = None

    if not es_admin:

        # Buscar al estudiante utilizando su CI
        estudiante_actual = Estudiante.objects.filter(
            ci=request.user.username
        ).first()

        if not estudiante_actual:
            messages.error(
                request,
                "No se encontró un estudiante asociado a esta cuenta."
            )
            return redirect('home')

    hoy = timezone.now().date()

    # ==========================================
    # PROCESAR SOLICITUDES DEL FORMULARIO
    # ==========================================

    if request.method == 'POST':

        accion = request.POST.get('accion')

        # --------------------------------------
        # CREAR SOLICITUD DE CAMBIO O PERMUTA
        # --------------------------------------

        if accion == 'crear':

            tipo = request.POST.get('tipo')
            detalle_origen_id = request.POST.get('detalle_origen')
            detalle_destino_id = request.POST.get('detalle_destino')
            estudiante_destino_id = request.POST.get('estudiante_destino')
            motivo = request.POST.get('motivo', '').strip()

            try:

                detalle_origen = DetalleGuardia.objects.select_related(
                    'estudiante',
                    'guardia'
                ).get(
                    id=detalle_origen_id
                )

                # El estudiante solo puede solicitar cambios
                # sobre una guardia que le pertenece.
                if not es_admin and detalle_origen.estudiante != estudiante_actual:

                    messages.error(
                        request,
                        "No puedes solicitar cambios sobre la guardia de otro estudiante."
                    )
                    return redirect('gestion_permutas')

                # Verificar que la guardia todavía sea futura
                if detalle_origen.guardia.fecha < hoy:

                    messages.error(
                        request,
                        "No puedes solicitar cambios sobre una guardia pasada."
                    )
                    return redirect('gestion_permutas')

                detalle_destino = None
                estudiante_destino = None

                # ----------------------------------
                # VALIDAR PERMUTA
                # ----------------------------------

                if tipo == 'PERMUTA':

                    if not detalle_destino_id:

                        messages.error(
                            request,
                            "Debes seleccionar la guardia del estudiante con quien deseas intercambiar."
                        )
                        return redirect('gestion_permutas')

                    detalle_destino = DetalleGuardia.objects.select_related(
                        'estudiante',
                        'guardia'
                    ).get(
                        id=detalle_destino_id
                    )

                    if detalle_destino.id == detalle_origen.id:

                        messages.error(
                            request,
                            "No puedes intercambiar una guardia contigo mismo."
                        )
                        return redirect('gestion_permutas')

                    if detalle_destino.guardia.fecha < hoy:

                        messages.error(
                            request,
                            "No puedes seleccionar una guardia pasada."
                        )
                        return redirect('gestion_permutas')

                    estudiante_destino = detalle_destino.estudiante

                # ----------------------------------
                # VALIDAR REEMPLAZO
                # ----------------------------------

                elif tipo == 'REEMPLAZO':

                    if not estudiante_destino_id:

                        messages.error(
                            request,
                            "Debes seleccionar al estudiante que realizará el reemplazo."
                        )
                        return redirect('gestion_permutas')

                    estudiante_destino = Estudiante.objects.get(
                        id=estudiante_destino_id,
                        activo=True
                    )

                    if estudiante_destino == detalle_origen.estudiante:

                        messages.error(
                            request,
                            "No puedes seleccionarte a ti mismo como reemplazante."
                        )
                        return redirect('gestion_permutas')

                else:

                    messages.error(
                        request,
                        "El tipo de solicitud no es válido."
                    )
                    return redirect('gestion_permutas')

                # ----------------------------------
                # REGISTRAR SOLICITUD
                # ----------------------------------

                Cambio.objects.create(
                    tipo=tipo,
                    detalle_origen=detalle_origen,
                    detalle_destino=detalle_destino,
                    estudiante_origen=detalle_origen.estudiante,
                    estudiante_destino=estudiante_destino,
                    motivo=motivo,
                    estado='PENDIENTE'
                )

                messages.success(
                    request,
                    "La solicitud se registró correctamente y está pendiente de aprobación."
                )

            except DetalleGuardia.DoesNotExist:

                messages.error(
                    request,
                    "No se encontró la guardia seleccionada."
                )

            except Estudiante.DoesNotExist:

                messages.error(
                    request,
                    "No se encontró el estudiante seleccionado."
                )

            return redirect('gestion_permutas')

        # --------------------------------------
        # APROBAR O RECHAZAR SOLICITUD
        # --------------------------------------

        elif accion in ['aprobar', 'rechazar']:

            if not es_admin:

                messages.error(
                    request,
                    "No tienes permiso para resolver solicitudes."
                )
                return redirect('gestion_permutas')

            cambio_id = request.POST.get('cambio_id')
            observacion = request.POST.get('observacion', '').strip()

            try:

                cambio = Cambio.objects.select_related(
                    'detalle_origen',
                    'detalle_destino',
                    'estudiante_destino'
                ).get(
                    id=cambio_id
                )

                if cambio.estado != 'PENDIENTE':

                    messages.warning(
                        request,
                        "Esta solicitud ya fue resuelta anteriormente."
                    )
                    return redirect('gestion_permutas')

                # ----------------------------------
                # APROBAR SOLICITUD
                # ----------------------------------

                if accion == 'aprobar':

                    if cambio.tipo == 'PERMUTA':

                        if not cambio.detalle_destino:

                            messages.error(
                                request,
                                "No se puede aprobar la permuta porque no tiene una guardia de destino."
                            )
                            return redirect('gestion_permutas')

                        # Intercambiar los estudiantes
                        estudiante_temporal = cambio.detalle_origen.estudiante

                        cambio.detalle_origen.estudiante = (
                            cambio.detalle_destino.estudiante
                        )

                        cambio.detalle_destino.estudiante = (
                            estudiante_temporal
                        )

                        cambio.detalle_origen.save()
                        cambio.detalle_destino.save()

                    elif cambio.tipo == 'REEMPLAZO':

                        if not cambio.estudiante_destino:

                            messages.error(
                                request,
                                "No se puede aprobar el reemplazo porque no tiene un estudiante asignado."
                            )
                            return redirect('gestion_permutas')

                        # Asignar al estudiante reemplazante
                        cambio.detalle_origen.estudiante = (
                            cambio.estudiante_destino
                        )

                        cambio.detalle_origen.save()

                    cambio.estado = 'ACEPTADO'

                    messages.success(
                        request,
                        "La solicitud fue aprobada correctamente."
                    )

                # ----------------------------------
                # RECHAZAR SOLICITUD
                # ----------------------------------

                else:

                    cambio.estado = 'RECHAZADO'

                    messages.warning(
                        request,
                        "La solicitud fue rechazada."
                    )

                # ----------------------------------
                # GUARDAR RESOLUCIÓN
                # ----------------------------------

                cambio.oficial_id = request.user
                cambio.fecha_resolucion = timezone.now()
                cambio.observacion = observacion

                cambio.save()

            except Cambio.DoesNotExist:

                messages.error(
                    request,
                    "No se encontró la solicitud seleccionada."
                )

            return redirect('gestion_permutas')

    # ==========================================
    # LISTADO DE ESTUDIANTES ACTIVOS
    # ==========================================

    estudiantes = Estudiante.objects.filter(
        activo=True
    ).order_by(
        'anio',
        'apellidos',
        'nombres'
    )

    if not es_admin and estudiante_actual:

        estudiantes = estudiantes.exclude(
            id=estudiante_actual.id
        )

    # ==========================================
    # GUARDIAS DEL ESTUDIANTE
    # ==========================================

    detalles_guardia = DetalleGuardia.objects.select_related(
        'guardia',
        'estudiante',
        'puesto'
    ).filter(
        guardia__fecha__gte=hoy
    ).order_by(
        'guardia__fecha'
    )

    if not es_admin:

        detalles_guardia = detalles_guardia.filter(
            estudiante=estudiante_actual
        )

    # ==========================================
    # GUARDIAS DISPONIBLES PARA PERMUTAR
    # ==========================================

    detalles_destino = DetalleGuardia.objects.select_related(
        'guardia',
        'estudiante',
        'puesto'
    ).filter(
        guardia__fecha__gte=hoy
    ).order_by(
        'guardia__fecha'
    )

    if not es_admin:

        detalles_destino = detalles_destino.exclude(
            estudiante=estudiante_actual
        )

    # ==========================================
    # HISTORIAL DE SOLICITUDES
    # ==========================================

    if es_admin:

        # Administrador: puede visualizar todas las solicitudes.
        cambios = Cambio.objects.select_related(
            'estudiante_origen',
            'estudiante_destino',
            'detalle_origen',
            'detalle_destino'
        ).order_by(
            '-fecha_solicitud'
        )

    else:

        # Estudiante: solamente visualiza las solicitudes
        # que él mismo realizó.
        cambios = Cambio.objects.filter(
            estudiante_origen=estudiante_actual
        ).select_related(
            'estudiante_origen',
            'estudiante_destino',
            'detalle_origen',
            'detalle_destino'
        ).order_by(
            '-fecha_solicitud'
        )

    # ==========================================
    # ENVIAR INFORMACIÓN A LA PLANTILLA
    # ==========================================

    contexto = {
        'es_admin': es_admin,
        'estudiante_actual': estudiante_actual,
        'estudiantes': estudiantes,
        'detalles_guardia': detalles_guardia,
        'detalles_destino': detalles_destino,
        'cambios': cambios,
    }

    return render(
        request,
        'guardias/permutas.html',
        contexto
    )