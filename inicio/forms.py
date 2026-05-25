from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Asignacion, Estudiante, Guardia, Rol

class RegistroForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs.update({'class': 'form-control'})
        self.fields['password2'].widget.attrs.update({'class': 'form-control'})

# --- Formulario para el CRUD de Asignaciones ---
class AsignacionForm(forms.ModelForm):
    class Meta:
        model = Asignacion
        fields = ['estudiante', 'guardia', 'rol']
        # Usamos widgets para que se vea bien con Bootstrap (como tus capturas)
        widgets = {
            'estudiante': forms.Select(attrs={'class': 'form-select'}),
            'guardia': forms.Select(attrs={'class': 'form-select'}),
            'rol': forms.Select(attrs={'class': 'form-select'}),
        }

# --- Formulario para registrar Estudiantes ---
class EstudianteForm(forms.ModelForm):
    class Meta:
        model = Estudiante
        fields = ['nombre', 'apellido', 'anio', 'carrera']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre'}),
            'apellido': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Apellido'}),
            'anio': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Año (ej: 3)'}),
            'carrera': forms.Select(attrs={'class': 'form-select'}),
        }

# --- Formulario para definir Horarios de Guardia ---
class GuardiaForm(forms.ModelForm):
    class Meta:
        model = Guardia
        fields = ['mes','fecha_inicio', 'fecha_fin']
        labels = {
            'fecha_inicio': 'Fecha y Hora de Inicio',
            'fecha_fin': 'Fecha y Hora de Finalización',
            'mes': 'Seleccionar Mes de Programación',
        }
        widgets = {
            # El tipo 'datetime-local' abre el calendario con hora automáticamente
            'fecha_inicio': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'fecha_fin': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'mes': forms.Select(attrs={'class': 'form-select'}),
        }

# --- Formulario para registrar Carreras ---
from .models import Carrera # Asegúrate de que Carrera esté importado arriba
class CarreraForm(forms.ModelForm):
    class Meta:
        model = Carrera
        fields = ['nombre']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Ingeniería de Sistemas'}),
        }