from datetime import timedelta

from django import forms
from django.utils import timezone
from .models import Estudiante
from .models import EsquemaGuardia
from .models import Estudiante, Gestion,EsquemaVigencia
from .models import AusenciaLicencia, EXTENSIONES_JUSTIFICATIVO, TAMANO_MAX_JUSTIFICATIVO_MB

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

# ==========================================================
# AUSENCIAS, LICENCIAS Y PERMISOS
# ==========================================================

DIAS_RETROACTIVOS_PERMITIDOS = 7  # El cadete puede justificar hasta 7 días hacia atrás


class SolicitudAusenciaForm(forms.ModelForm):
    """Formulario que llena el propio cadete desde su panel"""

    class Meta:
        model = AusenciaLicencia
        fields = ['tipo', 'fecha_inicio', 'fecha_fin', 'motivo', 'justificativo']
        widgets = {
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'fecha_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'fecha_fin': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'motivo': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 3,
                'placeholder': 'Explique con detalle el motivo (Ej. internado en el hospital por apendicitis)...',
            }),
            'justificativo': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': ','.join('.' + ext for ext in EXTENSIONES_JUSTIFICATIVO),
            }),
        }
        labels = {
            'tipo': 'Tipo de solicitud',
            'fecha_inicio': 'Desde',
            'fecha_fin': 'Hasta',
            'motivo': 'Motivo',
            'justificativo': 'Justificativo (foto o PDF)',
        }

    def __init__(self, *args, estudiante=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.estudiante = estudiante
        self.fields['tipo'].choices = [('', 'Seleccione el tipo...')] + list(AusenciaLicencia.OPCIONES_TIPO)

    def clean_justificativo(self):
        archivo = self.cleaned_data.get('justificativo')
        if archivo and archivo.size > TAMANO_MAX_JUSTIFICATIVO_MB * 1024 * 1024:
            raise forms.ValidationError(
                f"El archivo pesa demasiado. El máximo permitido es {TAMANO_MAX_JUSTIFICATIVO_MB} MB."
            )
        return archivo

    def validar_fecha_minima(self, fecha_inicio):
        limite = timezone.localdate() - timedelta(days=DIAS_RETROACTIVOS_PERMITIDOS)
        if fecha_inicio < limite:
            self.add_error('fecha_inicio', f"Solo puede justificar hasta {DIAS_RETROACTIVOS_PERMITIDOS} días hacia atrás.")

    def clean(self):
        datos = super().clean()
        inicio, fin = datos.get('fecha_inicio'), datos.get('fecha_fin')
        estudiante = datos.get('estudiante') or self.estudiante

        if inicio and fin:
            if fin < inicio:
                self.add_error('fecha_fin', "La fecha de fin no puede ser anterior a la fecha de inicio.")
            else:
                self.validar_fecha_minima(inicio)

            # Evitar solicitudes superpuestas (pendientes o aprobadas) del mismo cadete
            if estudiante and not self.errors:
                superpuesta = AusenciaLicencia.objects.filter(
                    estudiante=estudiante,
                    estado__in=['PENDIENTE', 'APROBADA'],
                    fecha_inicio__lte=fin,
                    fecha_fin__gte=inicio,
                ).exclude(pk=self.instance.pk).first()
                if superpuesta:
                    raise forms.ValidationError(
                        f"Ya existe una solicitud {superpuesta.get_estado_display().lower()} que cubre esas fechas "
                        f"({superpuesta.fecha_inicio:%d/%m/%Y} al {superpuesta.fecha_fin:%d/%m/%Y})."
                    )
        return datos


class AusenciaOficialForm(SolicitudAusenciaForm):
    """El oficial registra directamente una ausencia para cualquier cadete (queda aprobada)"""

    class Meta(SolicitudAusenciaForm.Meta):
        fields = ['estudiante'] + SolicitudAusenciaForm.Meta.fields
        widgets = {
            **SolicitudAusenciaForm.Meta.widgets,
            'estudiante': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {**SolicitudAusenciaForm.Meta.labels, 'estudiante': 'Estudiante (Cadete)'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['estudiante'].queryset = Estudiante.objects.filter(activo=True).order_by('apellidos', 'nombres')
        self.fields['estudiante'].empty_label = 'Seleccione un cadete...'

    def validar_fecha_minima(self, fecha_inicio):
        pass  # El oficial puede registrar ausencias de cualquier fecha
