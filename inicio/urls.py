from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    
    # Módulo de Personal (CRUD Estudiantes)
    path('estudiantes/', views.lista_estudiantes, name='lista_estudiantes'),
    path('estudiantes/nuevo/', views.nuevo_estudiante, name='nuevo_estudiante'),
    path('estudiantes/editar/<int:id>/', views.editar_estudiante, name='editar_estudiante'),
    path('estudiantes/eliminar/<int:id>/', views.eliminar_estudiante, name='eliminar_estudiante'),
    
    # Módulo de Rodillo de Guardias por Fechas (Paso 3)
    path('planificacion/', views.planificacion_guardias, name='planificacion_guardias'),
    path('planificacion/generar/', views.generar_rango_guardias, name='generar_rango_guardias'),
    
    # Sistema de Seguridad y Cuentas
    path('registro/', views.registro, name='registro'),
]
