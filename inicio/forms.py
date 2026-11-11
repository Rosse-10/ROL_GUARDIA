from django import forms
from .models import Estudiante
from .models import EsquemaGuardia
from .models import Estudiante, Gestion,EsquemaVigencia

class EstudianteForm(forms.ModelForm):
    class Meta:
        model = Estudiante
        fields = ['ci', 'nombres', 'apellidos', 'anio', 'carrera', 'activo', 'habilitado_desde']
        widgets = {
            'ci': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Cédula de Identidad'}),
            'nombres': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombres'}),
            'apellidos': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Apellidos'}),
            'anio': forms.Select(attrs={'class': 'form-control'}),
            'carrera': forms.Select(attrs={'class': 'form-control'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'habilitado_desde': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }


class GestionForm(forms.ModelForm):
    class Meta:
        model = Gestion
        fields = ['nombre', 'fecha_inicio', 'fecha_fin', 'activa']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. Gestión 2026'}),
            'fecha_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'fecha_fin': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }



class EsquemaGuardiaForm(forms.ModelForm):
    class Meta:
        model = EsquemaGuardia
        fields = ['nombre', 'activo']