from django.contrib import admin
from .models import Carrera, Estudiante, GuardiaDia

@admin.register(Carrera)
class CarreraAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre')

@admin.register(Estudiante)
class EstudianteAdmin(admin.ModelAdmin):
    list_display = ('apellido', 'nombre', 'anio', 'carrera')
    list_filter = ('carrera', 'anio')
    search_fields = ('nombre', 'apellido')

@admin.register(GuardiaDia)
class GuardiaDiaAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'estudiante_4to', 'estudiante_3ro')
    list_filter = ('fecha',)
    date_hierarchy = 'fecha'