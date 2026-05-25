from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('registro/', views.registro, name='registro'),
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('asignacion/nueva/', views.crear_asignacion, name='crear_asignacion'),
    path('asignacion/editar/<int:id>/', views.editar_asignacion, name='editar_asignacion'),
    path('asignacion/eliminar/<int:id>/', views.eliminar_asignacion, name='eliminar_asignacion'),
    path('estudiante/nuevo/', views.nuevo_estudiante, name='nuevo_estudiante'),
    path('guardia/nueva/', views.nueva_guardia, name='nueva_guardia'),
    path('carrera/nueva/', views.nueva_carrera, name='nueva_carrera'),
    path('sortear/<int:guardia_id>/', views.generar_sorteo_mes, name='sortear_mes'),
    path('eliminar-guardia/<int:guardia_id>/', views.eliminar_guardia, name='eliminar_guardia'),
    path('lista-estudiantes/', views.lista_estudiantes, name='lista_estudiantes'),
    path('estudiante/editar/<int:pk>/', views.editar_estudiante, name='editar_estudiante'),
    path('estudiante/eliminar/<int:pk>/', views.eliminar_estudiante, name='eliminar_estudiante'),
]