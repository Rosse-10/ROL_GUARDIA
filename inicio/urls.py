from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    
    # Módulo de Personal (CRUD Estudiantes)
    path('estudiantes/', views.lista_estudiantes, name='lista_estudiantes'),
    path('estudiantes/nuevo/', views.nuevo_estudiante, name='nuevo_estudiante'),
    path('estudiantes/editar/<int:id>/', views.editar_estudiante, name='editar_estudiante'),
    path('estudiantes/eliminar/<int:id>/', views.eliminar_estudiante, name='eliminar_estudiante'),
    
    # Módulo de Gestión Académica
    path('gestiones/', views.lista_gestiones, name='lista_gestiones'),
    path('gestiones/nueva/', views.nueva_gestion, name='nueva_gestion'),
    
    # Módulo de Rodillo de Guardias por Fechas
    path('planificacion/', views.planificacion_guardias, name='planificacion_guardias'),
    path('planificacion/generar/', views.generar_rango_guardias, name='generar_rango_guardias'),
    
    # Sistema de Seguridad y Cuentas
    path('registro/', views.registro, name='registro'),

    path('gestiones/editar/<int:id>/', views.editar_gestion, name='editar_gestion'),
    path('gestiones/eliminar/<int:id>/', views.eliminar_gestion, name='eliminar_gestion'),

    path('esquemas/', views.lista_esquemas, name='lista_esquemas'),
    path('esquemas/nuevo/', views.nuevo_esquema, name='nuevo_esquema'),
    path('esquemas/editar/<int:id>/', views.editar_esquema, name='editar_esquema'),
    path('esquemas/eliminar/<int:id>/', views.eliminar_esquema, name='eliminar_esquema'),

    path('ausencias/', views.gestion_ausencias, name='gestion_ausencias'),
    
    path('permutas/', views.gestion_permutas, name='gestion_permutas'),


]



