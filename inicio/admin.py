from django.contrib import admin
from .models import Carrera, Estudiante, Rol, Mes, Guardia, Asignacion

# Configuración para ver más detalles en la lista de Estudiantes
class EstudianteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'apellido', 'anio', 'carrera') # Columnas visibles
    search_fields = ('nombre', 'apellido') # Buscador por nombre
    list_filter = ('carrera', 'anio') # Filtros laterales

# Configuración para ver detalles de la Guardia
class GuardiaAdmin(admin.ModelAdmin):
    list_display = ('fecha_inicio', 'fecha_fin', 'mes')
    list_filter = ('mes',)

# Configuración para las Asignaciones
class AsignacionAdmin(admin.ModelAdmin):
    list_display = ('estudiante', 'rol', 'guardia')
    list_filter = ('rol', 'guardia')

# Registramos los modelos con sus respectivas configuraciones
admin.site.register(Carrera)
admin.site.register(Estudiante, EstudianteAdmin)
admin.site.register(Rol)
admin.site.register(Mes)
admin.site.register(Guardia, GuardiaAdmin)
admin.site.register(Asignacion, AsignacionAdmin)