from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import models  # Importante para models.Q
from .models import Estudiante, Carrera, Gestion, EsquemaGuardia, EsquemaVigencia, Puesto, GuardiaDia, DetalleGuardia, AusenciaLicencia,Cambio
from .forms import EstudianteForm, GestionForm, EsquemaGuardiaForm
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

    contexto = {
        'hoy': hoy,
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


@login_required
def gestion_ausencias(request):
    """Panel exclusivo del Oficial Administrador para registrar y consultar ausencias y licencias"""
    if request.method == 'POST':
        estudiante_id = request.POST.get('estudiante')
        tipo = request.POST.get('tipo')
        fecha_inicio = request.POST.get('fecha_inicio')
        fecha_fin = request.POST.get('fecha_fin')
        motivo = request.POST.get('motivo')

        # Validación de negocio: la fecha fin no puede ser anterior a la de inicio
        if fecha_inicio > fecha_fin:
            messages.error(request, "Error: La fecha de fin no puede ser anterior a la fecha de inicio.")
            return redirect('gestion_ausencias')

        # Registrar la ausencia en la base de datos
        AusenciaLicencia.objects.create(
            estudiante_id=estudiante_id,
            tipo=tipo,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            motivo=motivo,
            registrado_por=request.user
        )

        # Validación cruzada de impacto: verificar si el cadete ya tenía guardias en este rango
        guardias_afectadas = DetalleGuardia.objects.filter(
            estudiante_id=estudiante_id,
            guardia__fecha__gte=fecha_inicio,
            guardia__fecha__lte=fecha_fin
        ).select_related('guardia')

        if guardias_afectadas.exists():
            fechas_str = ", ".join([d.guardia.fecha.strftime('%d/%m/%Y') for d in guardias_afectadas])
            messages.warning(request, f"Ausencia registrada, pero ¡Atención! El cadete ya tenía guardias asignadas en las fechas: {fechas_str}.")
        else:
            messages.success(request, "¡Ausencia o licencia registrada correctamente!")

        return redirect('gestion_ausencias')

    # Listar ausencias ordenadas de la más reciente a la más antigua
    ausencias = AusenciaLicencia.objects.select_related('estudiante', 'registrado_por').order_by('-fecha_inicio')
    estudiantes = Estudiante.objects.filter(activo=True).order_by('apellidos', 'nombres')

    return render(request, 'guardias/ausencias.html', {
        'ausencias': ausencias,
        'estudiantes': estudiantes
    })

@login_required
def gestion_permutas(request):
    """Módulo para solicitar, autorizar y ejecutar cambios y permutas de guardia"""
    if request.method == 'POST':
        accion = request.POST.get('accion')

        # Acción 1: Crear la solicitud de permuta/reemplazo
        if accion == 'crear':
            tipo = request.POST.get('tipo')
            detalle_origen_id = request.POST.get('detalle_origen')
            estudiante_destino_id = request.POST.get('estudiante_destino')
            detalle_destino_id = request.POST.get('detalle_destino') or None
            motivo = request.POST.get('motivo')

            # Obtener el detalle origen para extraer al estudiante solicitante automáticamente
            detalle_orig = get_object_or_404(DetalleGuardia, id=detalle_origen_id)
            estudiante_origen = detalle_orig.estudiante

            if estudiante_destino_id and int(estudiante_destino_id) == estudiante_origen.id:
                messages.error(request, "Error: El cadete de origen y destino no pueden ser el mismo.")
                return redirect('gestion_permutas')

            Cambio.objects.create(
                tipo=tipo,
                detalle_origen_id=detalle_origen_id,
                detalle_destino_id=detalle_destino_id,
                estudiante_origen=estudiante_origen,
                estudiante_destino_id=estudiante_destino_id if estudiante_destino_id else None,
                motivo=motivo,
                estado='PENDIENTE'
            )
            messages.success(request, "Solicitud de permuta/reemplazo registrada correctamente.")
            return redirect('gestion_permutas')

        # Acción 2: Aprobación o Rechazo por el Oficial Administrador
        elif accion in ['aprobar', 'rechazar'] and request.user.is_superuser:
            cambio_id = request.POST.get('cambio_id')
            cambio = get_object_or_404(Cambio, id=cambio_id)
            observacion = request.POST.get('observacion', '')

            if accion == 'aprobar':
                cambio.estado = 'ACEPTADO'
                cambio.oficial_id = request.user
                cambio.fecha_resolucion = timezone.now()
                cambio.observacion = observacion
                cambio.save()

                # Ejecutar el intercambio real en los detalles de guardia
                det_origen = cambio.detalle_origen
                est_origen_original = det_origen.estudiante

                if cambio.tipo == 'PERMUTA' and cambio.detalle_destino and cambio.estudiante_destino:
                    # Intercambio cruzado entre dos guardias
                    det_destino = cambio.detalle_destino
                    est_destino_original = det_destino.estudiante

                    det_origen.estudiante = est_destino_original
                    det_origen.save()

                    det_destino.estudiante = est_origen_original
                    det_destino.save()
                elif cambio.estudiante_destino:
                    # Reemplazo simple por fuerza mayor
                    det_origen.estudiante = cambio.estudiante_destino
                    det_origen.save()

                messages.success(request, "Permuta aprobada y aplicada con éxito al rol de guardia.")

            elif accion == 'rechazar':
                cambio.estado = 'RECHAZADO'
                cambio.oficial_id = request.user
                cambio.fecha_resolucion = timezone.now()
                cambio.observacion = observacion
                cambio.save()
                messages.warning(request, "La solicitud de permuta ha sido rechazada.")

            return redirect('gestion_permutas')

    # Datos para renderizar la interfaz
    cambios = Cambio.objects.select_related(
        'detalle_origen__guardia', 'detalle_origen__estudiante', 
        'estudiante_origen', 'estudiante_destino', 'oficial_id'
    ).order_by('-fecha_solicitud')

    estudiantes = Estudiante.objects.filter(activo=True).order_by('apellidos')
    detalles_guardia = DetalleGuardia.objects.select_related('guardia', 'estudiante').filter(
        guardia__fecha__gte=timezone.now().date()
    ).order_by('guardia__fecha')

    return render(request, 'guardias/permutas.html', {
        'cambios': cambios,
        'estudiantes': estudiantes,
        'detalles_guardia': detalles_guardia
    })