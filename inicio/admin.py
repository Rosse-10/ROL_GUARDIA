from django.contrib import admin
from .models import (
    Gestion, Carrera, Estudiante, Matricula, 
    EsquemaGuardia, EsquemaVigencia, Puesto, 
    GuardiaDia, DetalleGuardia, AusenciaLicencia, Cambio
)

@admin.register(Gestion)
class GestionAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'fecha_inicio', 'fecha_fin', 'activa')

@admin.register(Carrera)
class CarreraAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre')

@admin.register(Estudiante)
class EstudianteAdmin(admin.ModelAdmin):
    list_display = ('apellidos', 'nombres', 'ci', 'anio', 'carrera', 'activo')
    list_filter = ('carrera', 'anio', 'activo')
    search_fields = ('nombres', 'apellidos', 'ci')

@admin.register(Matricula)
class MatriculaAdmin(admin.ModelAdmin):
    list_display = ('estudiante', 'gestion', 'anio', 'resultado')
    list_filter = ('gestion', 'resultado', 'anio')

@admin.register(EsquemaGuardia)
class EsquemaGuardiaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activo')

@admin.register(EsquemaVigencia)
class EsquemaVigenciaAdmin(admin.ModelAdmin):
    list_display = ('esquema', 'fecha_desde', 'fecha_hasta')

@admin.register(Puesto)
class PuestoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'esquema', 'cargo', 'anio_requerido', 'orden')
    list_filter = ('esquema', 'anio_requerido', 'cargo')

@admin.register(GuardiaDia)
class GuardiaDiaAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'esquema', 'estado', 'creado_por')
    list_filter = ('estado', 'esquema', 'fecha')

@admin.register(DetalleGuardia)
class DetalleGuardiaAdmin(admin.ModelAdmin):
    list_display = ('guardia', 'puesto', 'estudiante', 'asistencia')
    list_filter = ('asistencia', 'puesto__cargo')
    search_fields = ('estudiante__apellidos', 'estudiante__nombres')

@admin.register(AusenciaLicencia)
class AusenciaLicenciaAdmin(admin.ModelAdmin):
    list_display = ('estudiante', 'tipo', 'fecha_inicio', 'fecha_fin')
    list_filter = ('tipo',)

@admin.register(Cambio)
class CambioAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'estudiante_origen', 'estado', 'fecha_solicitud')
    list_filter = ('estado', 'tipo')