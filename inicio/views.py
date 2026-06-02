from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from .models import Estudiante, Carrera, GuardiaDia
from .forms import RegistroForm, EstudianteForm
from datetime import datetime, timedelta
from django.contrib import messages
from django.utils import timezone

def asegurar_carreras():
    """Garantiza la existencia de las 3 carreras oficiales de la EMI del Trópico"""
    for codigo, nombre_completo in Carrera.OPCIONES_CARRERA:
        Carrera.objects.get_or_create(nombre=codigo)

def home(request):
    """Pantalla principal dual (Módulo de Transparencia Pública con filtros de Día, Semana y Mes)"""
    asegurar_carreras()
    
    # Obtener la fecha actual local
    hoy = timezone.now().date()
    manana = hoy + timedelta(days=1)
    una_semana_despues = hoy + timedelta(days=7)
    
    # 🔴 1. Datos para la pestaña: Guardia de Hoy
    guardia_hoy = GuardiaDia.objects.filter(fecha=hoy).first()
    
    # 📅 2. Datos para la pestaña: Vista Semanal (Próximos 7 días)
    guardias_semana = GuardiaDia.objects.filter(fecha__range=[hoy, una_semana_despues]).order_by('fecha')
    
    # 📋 3. Datos para la pestaña: Todo el Mes (Muestra todo el rol acumulado hacia adelante)
    guardias_mes = GuardiaDia.objects.filter(fecha__gte=hoy).order_by('fecha')
    
    contexto = {
        'guardia_hoy': guardia_hoy,
        'guardias_semana': guardias_semana,
        'guardias_mes': guardias_mes,
        'hoy': hoy,
    }
    
    return render(request, 'home.html', contexto)

@login_required
def lista_estudiantes(request):
    """Muestra la lista de estudiantes organizada estrictamente por Carrera y Año"""
    asegurar_carreras()
    
    # Obtenemos las carreras existentes
    carreras = Carrera.objects.all()
    
    # Estructuramos un diccionario organizado por carrera y luego por año (1 al 4)
    datos_agrupados = {}
    for c in carreras:
        datos_agrupados[c] = {
            1: Estudiante.objects.filter(carrera=c, anio=1).order_by('apellido', 'nombre'),
            2: Estudiante.objects.filter(carrera=c, anio=2).order_by('apellido', 'nombre'),
            3: Estudiante.objects.filter(carrera=c, anio=3).order_by('apellido', 'nombre'),
            4: Estudiante.objects.filter(carrera=c, anio=4).order_by('apellido', 'nombre'),
        }
    
    return render(request, 'estudiantes/lista.html', {'datos_agrupados': datos_agrupados})

@login_required
def nuevo_estudiante(request):
    """Registrar un nuevo estudiante en la institución"""
    asegurar_carreras()
    if request.method == 'POST':
        form = EstudianteForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('lista_estudiantes')
    else:
        form = EstudianteForm()
    return render(request, 'estudiantes/form_estudiante.html', {'form': form, 'titulo': 'Nuevo Estudiante'})

@login_required
def editar_estudiante(request, id):
    """Modificar los datos de un estudiante existente"""
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
    """Dar de baja a un estudiante del sistema"""
    estudiante = get_object_or_404(Estudiante, id=id)
    if request.method == 'POST':
        estudiante.delete()
        return redirect('lista_estudiantes')
    return render(request, 'estudiantes/confirmar_eliminar.html', {'estudiante': estudiante})

def registro(request):
    """Registro de nuevos usuarios administradores"""
    if request.method == 'POST':
        form = RegistroForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('home')
    else:
        form = RegistroForm()
    return render(request, 'registration/registro.html', {'form': form})


# ==========================================================
# ALGORITMO DE ROTACIÓN SECUENCIAL CONTINUA (PASO 3)
# ==========================================================

@login_required
def planificacion_guardias(request):
    """Pantalla para ver las guardias generadas y lanzar el formulario de creación"""
    guardias = GuardiaDia.objects.all().order_by('fecha')
    return render(request, 'guardias/planificacion.html', {'guardias': guardias})

@login_required
def generar_rango_guardias(request):
    """Algoritmo de rodillo continuo que asigna personal por fechas sin repetir hasta ciclar"""
    if request.method == 'POST':
        fecha_inicio_str = request.POST.get('fecha_inicio')
        fecha_fin_str = request.POST.get('fecha_fin')

        if not fecha_inicio_str or not fecha_fin_str:
            messages.error(request, "Por favor, seleccione ambas fechas.")
            return redirect('planificacion_guardias')

        fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()

        if fecha_fin < fecha_inicio:
            messages.error(request, "La fecha de fin no puede ser menor a la de inicio.")
            return redirect('planificacion_guardias')

        # OBTENER LISTAS DE ESTUDIANTES ORDENADAS ALFABÉTICAMENTE
        estud_4to = list(Estudiante.objects.filter(anio=4).order_by('apellido', 'nombre'))
        estud_3ro = list(Estudiante.objects.filter(anio=3).order_by('apellido', 'nombre'))
        estud_2do = list(Estudiante.objects.filter(anio=2).order_by('apellido', 'nombre'))
        estud_1ro = list(Estudiante.objects.filter(anio=1).order_by('apellido', 'nombre'))

        # VALIDACIÓN: Verificar que tengamos el personal mínimo para armar el servicio
        if len(estud_4to) < 1 or len(estud_3ro) < 1 or len(estud_2do) < 2 or len(estud_1ro) < 2:
            messages.error(request, "Faltan estudiantes. Se requiere mínimo: 1 de 4to, 1 de 3ro, 2 de 2do y 2 de 1ro.")
            return redirect('lista_estudiantes')

        # DETERMINAR EN QUÉ ÍNDICE DEL RODILLO NOS QUEDAMOS EN LA ÚLTIMA GUARDIA
        ultima_guardia = GuardiaDia.objects.all().order_by('-fecha').first()
        
        idx_4to = 0
        idx_3ro = 0
        idx_2do = 0
        idx_1ro = 0

        if ultima_guardia:
            # Buscamos quién fue el último asignado para arrancar desde el siguiente
            if ultima_guardia.estudiante_4to in estud_4to:
                idx_4to = (estud_4to.index(ultima_guardia.estudiante_4to) + 1) % len(estud_4to)
            if ultima_guardia.estudiante_3ro in estud_3ro:
                idx_3ro = (estud_3ro.index(ultima_guardia.estudiante_3ro) + 1) % len(estud_3ro)
            if ultima_guardia.estudiante_2do_2 in estud_2do:
                idx_2do = (estud_2do.index(ultima_guardia.estudiante_2do_2) + 1) % len(estud_2do)
            if ultima_guardia.estudiante_1ro_2 in estud_1ro:
                idx_1ro = (estud_1ro.index(ultima_guardia.estudiante_1ro_2) + 1) % len(estud_1ro)

        # RECORRER EL RANGO DE FECHAS DÍA POR DÍA
        fecha_actual = fecha_inicio
        while fecha_actual <= fecha_fin:
            
            # Si la guardia de este día ya existe, la saltamos para no duplicar
            if GuardiaDia.objects.filter(fecha=fecha_actual).exists():
                fecha_actual += timedelta(days=1)
                continue

            # Selección secuencial de alumnos usando operador residuo (%) para el bucle continuo
            e_4to = estud_4to[idx_4to]
            idx_4to = (idx_4to + 1) % len(estud_4to)

            e_3ro = estud_3ro[idx_3ro]
            idx_3ro = (idx_3ro + 1) % len(estud_3ro)

            # Segundos años (requiere 2 alumnos por día)
            e_2do_1 = estud_2do[idx_2do]
            idx_2do = (idx_2do + 1) % len(estud_2do)
            e_2do_2 = estud_2do[idx_2do]
            idx_2do = (idx_2do + 1) % len(estud_2do)

            # Primeros años (requiere 2 alumnos por día)
            e_1ro_1 = estud_1ro[idx_1ro]
            idx_1ro = (idx_1ro + 1) % len(estud_1ro)
            e_1ro_2 = estud_1ro[idx_1ro]
            idx_1ro = (idx_1ro + 1) % len(estud_1ro)

            # Guardar la asignación del día en la base de datos
            GuardiaDia.objects.create(
                fecha=fecha_actual,
                estudiante_4to=e_4to,
                estudiante_3ro=e_3ro,
                estudiante_2do_1=e_2do_1,
                estudiante_2do_2=e_2do_2,
                estudiante_1ro_1=e_1ro_1,
                estudiante_1ro_2=e_1ro_2
            )

            fecha_actual += timedelta(days=1)

        messages.success(request, "Rol de servicio generado de forma secuencial exitosamente.")
        return redirect('planificacion_guardias')

    return redirect('planificacion_guardias')