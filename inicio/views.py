from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from .forms import RegistroForm, AsignacionForm # Importamos el nuevo form
from .models import Asignacion, Estudiante, Guardia, Rol
from .forms import RegistroForm, AsignacionForm, EstudianteForm, GuardiaForm, CarreraForm
import random
from django.db import transaction
from .models import Estudiante, Guardia, Rol, Asignacion, Mes
from django.utils import timezone
from django.contrib.auth.decorators import user_passes_test

@login_required
def generar_sorteo_mes(request, guardia_id):
    guardia_actual = get_object_or_404(Guardia, id=guardia_id)
    mes_actual = guardia_actual.mes
    
    # 1. Traer Roles
    try:
        comandante_rol = Rol.objects.get(nombre__icontains="Comandante")
        sargento_rol = Rol.objects.get(nombre__icontains="Sargento")
        numero_rol = Rol.objects.get(nombre__icontains="Numero")
    except Rol.DoesNotExist:
        return render(request, 'error.html', {'mensaje': 'Faltan roles base en la base de datos.'})

    # 2. Filtrar disponibilidad (Rotación mensual)
    ids_ya_asignados = Asignacion.objects.filter(
        guardia__mes=mes_actual
    ).values_list('estudiante_id', flat=True)

    estudiantes_disponibles = Estudiante.objects.exclude(id__in=ids_ya_asignados)
    candidatos_4to = list(estudiantes_disponibles.filter(anio=4))
    candidatos_numeros = list(estudiantes_disponibles.filter(anio__in=[2, 3]))

    if mes_actual.mes > 6:
        candidatos_numeros.extend(list(estudiantes_disponibles.filter(anio=1)))

    # Validación mínima
    if len(candidatos_4to) < 2 or len(candidatos_numeros) < 4:
        return render(request, 'error.html', {
            'mensaje': f'No hay suficientes estudiantes disponibles para aplicar Montecarlo en este mes.'
        })

    # --- INICIO MODELO MONTECARLO ---
    mejor_puntaje = -10000
    mejor_combinacion = {'comandante': None, 'sargento': None, 'numeros': []}

    # Simulamos 1000 escenarios posibles
    for _ in range(1000):
        # Generar una muestra aleatoria para esta iteración
        iter_4to = random.sample(candidatos_4to, 2)
        iter_numeros = random.sample(candidatos_numeros, 4)
        
        puntaje_iteracion = 0
        
        # REGLA 1: Favorecer a los de años superiores en roles altos
        # (Ejemplo: Un estudiante con mejor promedio o más antiguo suma más)
        comandante_candidato = iter_4to[0]
        sargento_candidato = iter_4to[1]
        
        # Aquí puedes agregar lógica de "Puntaje":
        # Por ejemplo, si tienes un campo 'promedio' en Estudiante:
        # puntaje_iteracion += comandante_candidato.promedio 
        
        # REGLA 2: Evitar que alguien de 2do año sea "Número" si hay muchos de 3ero libres
        for n in iter_numeros:
            if n.anio == 3:
                puntaje_iteracion += 5  # Preferimos 3ros sobre 2dos para esta guardia
            else:
                puntaje_iteracion += 2

        # Guardar la mejor combinación encontrada
        if puntaje_iteracion > mejor_puntaje:
            mejor_puntaje = puntaje_iteracion
            mejor_combinacion = {
                'comandante': comandante_candidato,
                'sargento': sargento_candidato,
                'numeros': iter_numeros
            }
    # --- FIN MODELO MONTECARLO ---

    # 6. Guardar la mejor opción encontrada por el modelo
    with transaction.atomic():
        # Limpiar si ya existía algo para esta guardia específica
        Asignacion.objects.filter(guardia=guardia_actual).delete()
        
        # Crear asignaciones basadas en el ganador de Montecarlo
        Asignacion.objects.create(estudiante=mejor_combinacion['comandante'], guardia=guardia_actual, rol=comandante_rol)
        Asignacion.objects.create(estudiante=mejor_combinacion['sargento'], guardia=guardia_actual, rol=sargento_rol)
        
        for est in mejor_combinacion['numeros']:
            Asignacion.objects.create(estudiante=est, guardia=guardia_actual, rol=numero_rol)

    return redirect('home')


@login_required
def nuevo_estudiante(request):
    if request.method == 'POST':
        form = EstudianteForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('home')
    else:
        form = EstudianteForm()
    return render(request, 'asignaciones/form_asignacion.html', {'form': form, 'titulo': 'Registrar Nuevo Estudiante'})
from django.contrib.auth.decorators import user_passes_test

@user_passes_test(lambda u: u.is_superuser)
def lista_estudiantes(request):
    estudiantes = Estudiante.objects.all().order_by('apellido')
    # Correcto: Le indicas que entre a la carpeta 'asignaciones'
    return render(request, 'asignaciones/estudiantes_lista.html', {'estudiantes': estudiantes})

from django.shortcuts import get_object_or_404

# EDITAR ESTUDIANTE
@user_passes_test(lambda u: u.is_superuser)
def editar_estudiante(request, pk):
    estudiante = get_object_or_404(Estudiante, pk=pk)
    if request.method == 'POST':
        form = EstudianteForm(request.POST, instance=estudiante)
        if form.is_valid():
            form.save()
            return redirect('lista_estudiantes')
    else:
        form = EstudianteForm(instance=estudiante)
    return render(request, 'asignaciones/form_asignacion.html', {
        'form': form, 
        'titulo': f'Editar Estudiante: {estudiante.nombre}'
    })

# ELIMINAR ESTUDIANTE
@user_passes_test(lambda u: u.is_superuser)
def eliminar_estudiante(request, pk):
    estudiante = get_object_or_404(Estudiante, pk=pk)
    if request.method == 'POST':
        estudiante.delete()
        return redirect('lista_estudiantes')
    return render(request, 'asignaciones/confirmar_eliminar.html', {'objeto': estudiante})

@login_required
def nueva_guardia(request):
    if request.method == 'POST':
        form = GuardiaForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('home')
    else:
        form = GuardiaForm()
    return render(request, 'asignaciones/form_asignacion.html', {'form': form, 'titulo': 'Programar Nueva Guardia y Asignar Mes'})

@login_required
def nueva_carrera(request):
    if request.method == 'POST':
        form = CarreraForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('home')
    else:
        form = CarreraForm()
    return render(request, 'asignaciones/form_asignacion.html', {'form': form, 'titulo': 'Agregar Nueva Carrera'})
# --- Vistas de Usuario ---

@login_required
def home(request):
    mes_id = request.GET.get('mes_filtro')
    meses_disponibles = Mes.objects.all().order_by('anio', 'mes')
    
    # --- NUEVA LÓGICA: TRAER ESTUDIANTES ---
    # Usamos .all() para traer a todos los registrados en la tabla inicio_estudiante
    estudiantes_registrados = Estudiante.objects.all().order_by('apellido') 
    
    # Filtramos las GUARDIAS
    if mes_id:
        guardias = Guardia.objects.filter(mes_id=mes_id).order_by('fecha_inicio')
        mes_seleccionado = get_object_or_404(Mes, id=mes_id)
    else:
        mes_actual_num = timezone.now().month
        guardias = Guardia.objects.filter(mes__mes=mes_actual_num).order_by('fecha_inicio')
        mes_seleccionado = Mes.objects.filter(mes=mes_actual_num).first()

    # --- INCREMENTO EN EL CONTEXTO ---
    return render(request, 'home.html', {
        'guardias': guardias,
        'meses': meses_disponibles,
        'mes_seleccionado': mes_seleccionado,
        'estudiantes': estudiantes_registrados  # <--- Debes agregar esta línea
    })

def registro(request):
    if request.method == 'POST':
        form = RegistroForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('home')
    else:
        form = RegistroForm()
    return render(request, 'registration/registro.html', {'form': form})

# --- CRUD de Asignaciones (NUEVO) ---

@login_required
def crear_asignacion(request):
    if request.method == 'POST':
        form = AsignacionForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('home')
    else:
        form = AsignacionForm()
    return render(request, 'asignaciones/form_asignacion.html', {'form': form, 'titulo': 'Nueva Asignación'})

@login_required
def editar_asignacion(request, id):
    asignacion = get_object_or_404(Asignacion, id=id)
    if request.method == 'POST':
        form = AsignacionForm(request.POST, instance=asignacion)
        if form.is_valid():
            form.save()
            return redirect('home')
    else:
        form = AsignacionForm(instance=asignacion)
    return render(request, 'asignaciones/form_asignacion.html', {'form': form, 'titulo': 'Editar Asignación'})

@login_required
def eliminar_asignacion(request, id):
    asignacion = get_object_or_404(Asignacion, id=id)
    if request.method == 'POST':
        asignacion.delete()
        return redirect('home')
    return render(request, 'asignaciones/confirmar_eliminar.html', {'asignacion': asignacion})

@login_required
def eliminar_guardia(request, guardia_id):
    guardia = get_object_or_404(Guardia, id=guardia_id)
    guardia.delete()
    return redirect('home')