import re
from datetime import date, timedelta

from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import (
    AusenciaLicencia, Cambio, DetalleGuardia, EsquemaGuardia, EsquemaVigencia, Estudiante, Gestion, Puesto,
    EXTENSIONES_JUSTIFICATIVO, TAMANO_MAX_JUSTIFICATIVO_MB, cuenta_reutilizable,
)

class EstudianteForm(forms.ModelForm):
    class Meta:
        model = Estudiante
        fields = ['ci', 'nombres', 'apellidos', 'anio', 'carrera', 'activo', 'egresado', 'habilitado_desde']
        widgets = {
            'ci': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Cédula de Identidad'}),
            'nombres': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombres'}),
            'apellidos': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Apellidos'}),
            'anio': forms.Select(attrs={'class': 'form-control'}),
            'carrera': forms.Select(attrs={'class': 'form-control'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'egresado': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'habilitado_desde': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }
        help_texts = {
            'ci': 'Será el usuario con el que el cadete inicia sesión. Clave inicial: su primer apellido.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ci'].required = True
        self.fields['ci'].label = 'C.I.'
        self.fields['ci'].error_messages['required'] = (
            "El C.I. es obligatorio: es el usuario con el que el cadete ingresa."
        )

    def clean_ci(self):
        ci = (self.cleaned_data.get('ci') or '').strip()
        if not ci:
            raise forms.ValidationError("El C.I. es obligatorio: es el usuario con el que el cadete ingresa.")
        if not re.fullmatch(r'[A-Za-z0-9-]+', ci):
            raise forms.ValidationError("El C.I. solo puede tener números, letras y guiones (sin espacios). Ej. 9309384 o 9309384-1B")

        otra_cuenta = User.objects.filter(username__iexact=ci).exclude(pk=self.instance.usuario_id).first()
        if otra_cuenta:
            # Solo se permite si el estudiante aún no tiene cuenta y esa cuenta es una vieja sin dueño
            if self.instance.usuario_id or not cuenta_reutilizable(otra_cuenta):
                raise forms.ValidationError("Ese C.I. ya es el usuario de otra cuenta del sistema.")
        return ci


class CambiarClaveForm(PasswordChangeForm):
    """Cambio de contraseña que no permite volver a usar la clave inicial (primer apellido)"""

    def clean_new_password1(self):
        nueva = self.cleaned_data.get('new_password1')
        estudiante = getattr(self.user, 'estudiante', None)
        if nueva and estudiante is not None and nueva.strip().lower() == estudiante.clave_inicial:
            raise forms.ValidationError("La nueva contraseña no puede ser su apellido.")
        return nueva


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
        fields = ['nombre']
        widgets = {'nombre': forms.TextInput(attrs={'placeholder': 'Ej. Esquema A (sin 1er año)'})}


class _PuestosBaseFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        for form in self.deleted_forms:
            puesto = form.instance
            if puesto.pk and DetalleGuardia.objects.filter(puesto=puesto).exists():
                raise forms.ValidationError(
                    f"No se puede quitar el puesto «{puesto.nombre}» porque ya se usó en guardias generadas."
                )


class _VigenciasBaseFormSet(forms.BaseInlineFormSet):
    def clean(self):
        """Las vigencias de este mismo formulario tampoco pueden superponerse entre sí"""
        super().clean()
        rangos = []
        for form in self.forms:
            if not hasattr(form, 'cleaned_data') or not form.cleaned_data or form in self.deleted_forms:
                continue
            desde, hasta = form.cleaned_data.get('fecha_desde'), form.cleaned_data.get('fecha_hasta')
            if desde:
                rangos.append((desde, hasta or date.max))
        rangos.sort()
        for (d1, h1), (d2, _) in zip(rangos, rangos[1:]):
            if d2 <= h1:
                raise forms.ValidationError("Dos de las vigencias cargadas se superponen entre sí.")


PuestoFormSet = forms.inlineformset_factory(
    EsquemaGuardia, Puesto, formset=_PuestosBaseFormSet,
    fields=['orden', 'nombre', 'cargo', 'anio_requerido'],
    labels={'orden': 'Orden', 'nombre': 'Puesto', 'cargo': 'Cargo', 'anio_requerido': 'Año'},
    widgets={
        'orden': forms.NumberInput(attrs={'min': 1, 'style': 'width: 60px;'}),
        'nombre': forms.TextInput(attrs={'placeholder': 'Ej. Guardia 2do Año - 1'}),
    },
    extra=1, can_delete=True,
)

VigenciaFormSet = forms.inlineformset_factory(
    EsquemaGuardia, EsquemaVigencia, formset=_VigenciasBaseFormSet,
    fields=['fecha_desde', 'fecha_hasta'],
    labels={'fecha_desde': 'Desde', 'fecha_hasta': 'Hasta (vacío = sin fin)'},
    widgets={
        'fecha_desde': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        'fecha_hasta': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
    },
    extra=1, can_delete=True,
)

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


# ==========================================================
# CAMBIOS Y PERMUTAS
# ==========================================================

class _DetalleChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, d):
        return (f"{d.guardia.fecha:%d/%m/%Y} · {d.puesto.nombre} ({d.puesto.anio_requerido}° año) · "
                f"{d.estudiante.apellidos}, {d.estudiante.nombres}")


class _CadeteChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, e):
        return f"{e.apellidos}, {e.nombres} ({e.anio}° año · {e.carrera})"


class SolicitudCambioForm(forms.Form):
    """Solicitud de permuta o reemplazo. El cadete solo ve sus guardias y a los de su año;
    el oficial ve todas las guardias desde hoy."""
    tipo = forms.ChoiceField(choices=Cambio.OPCIONES_TIPO, label='Tipo de solicitud',
                             widget=forms.Select(attrs={'class': 'form-select', 'id': 'tipo'}))
    detalle_origen = _DetalleChoiceField(queryset=DetalleGuardia.objects.none(), label='Guardia a cambiar',
                                         empty_label='Seleccione la guardia...',
                                         widget=forms.Select(attrs={'class': 'form-select'}))
    detalle_destino = _DetalleChoiceField(queryset=DetalleGuardia.objects.none(), required=False,
                                          label='Guardia del cadete con quien intercambiar',
                                          empty_label='Seleccione la otra guardia...',
                                          widget=forms.Select(attrs={'class': 'form-select', 'id': 'detalle_destino'}))
    reemplazante = _CadeteChoiceField(queryset=Estudiante.objects.none(), required=False,
                                      label='Cadete que realizará el reemplazo',
                                      empty_label='Seleccione el cadete...',
                                      widget=forms.Select(attrs={'class': 'form-select', 'id': 'reemplazante'}))
    motivo = forms.CharField(max_length=250, label='Motivo', widget=forms.TextInput(attrs={
        'class': 'form-control', 'placeholder': 'Ej. Comisión académica, salud, cruce de turnos...'}))

    def __init__(self, *args, estudiante=None, por_oficial=False, **kwargs):
        from .permutas import fecha_minima
        super().__init__(*args, **kwargs)
        self.por_oficial = por_oficial
        guardias = DetalleGuardia.objects.select_related('guardia', 'puesto', 'estudiante').filter(
            guardia__fecha__gte=fecha_minima(por_oficial)
        ).order_by('guardia__fecha', 'puesto__orden')
        cadetes = Estudiante.objects.filter(activo=True, anio__in=Estudiante.ANIOS_CON_GUARDIA).select_related('carrera')

        if por_oficial:
            self.fields['detalle_origen'].queryset = guardias
            self.fields['detalle_destino'].queryset = guardias
            self.fields['reemplazante'].queryset = cadetes.order_by('anio', 'apellidos', 'nombres')
        else:
            self.fields['detalle_origen'].label = 'Mi guardia'
            self.fields['detalle_origen'].queryset = guardias.filter(estudiante=estudiante)
            # Solo guardias y cadetes de su mismo año
            self.fields['detalle_destino'].queryset = guardias.exclude(estudiante=estudiante).filter(
                puesto__anio_requerido=estudiante.anio)
            self.fields['reemplazante'].queryset = cadetes.filter(anio=estudiante.anio).exclude(
                pk=estudiante.pk).order_by('apellidos', 'nombres')

    def clean(self):
        from .permutas import CambioInvalido, validar
        datos = super().clean()
        origen = datos.get('detalle_origen')
        if origen and datos.get('tipo') and not self.errors:
            try:
                validar(datos['tipo'], origen, datos.get('detalle_destino'), datos.get('reemplazante'),
                        por_oficial=self.por_oficial)
            except CambioInvalido as error:
                raise forms.ValidationError(str(error))
        return datos
