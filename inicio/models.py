from django.db import models
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone


class Gestion(models.Model):
    """Representa el año académico o gestión (Ej. Gestión 2026)"""
    nombre = models.CharField(max_length=50, unique=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    activa = models.BooleanField(default=False)

    def __str__(self):
        return self.nombre

class Carrera(models.Model):
    """Carreras oficiales de la EMI"""
    OPCIONES_CARRERA = [
        ('SISTEMAS', 'Ingeniería de Sistemas'),
        ('CIVIL', 'Ingeniería Civil'),
        ('COMERCIAL', 'Ingeniería Comercial'),
    ]
    nombre = models.CharField(max_length=50, choices=OPCIONES_CARRERA, unique=True)

    def __str__(self):
        return self.get_nombre_display()


class Estudiante(models.Model):
    """Información general del estudiante/cadete"""
    OPCIONES_ANIO = [
        (1, 'Primer Año'),
        (2, 'Segundo Año'),
        (3, 'Tercer Año'),
        (4, 'Cuarto Año'),
        (5, 'Quinto Año'),  # Último año: NO hace guardia
    ]
    ANIOS_CON_GUARDIA = (1, 2, 3, 4)
    ci = models.CharField(max_length=20, unique=True, null=True, blank=True)
    nombres = models.CharField(max_length=50)
    apellidos = models.CharField(max_length=50)
    anio = models.IntegerField(choices=OPCIONES_ANIO)
    carrera = models.ForeignKey(Carrera, on_delete=models.PROTECT)
    activo = models.BooleanField(default=True)
    egresado = models.BooleanField(default=False)  # Terminó 5to año (lo marca la Promoción de año)
    habilitado_desde = models.DateField(null=True, blank=True)  # Clave para el ingreso de 1er año
    usuario = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='estudiante'
    )  # Cuenta con la que el cadete ingresa a su panel (usuario = CI)
    debe_cambiar_clave = models.BooleanField(default=True)  # True mientras use la clave inicial

    def __str__(self):
        return f"{self.apellidos} {self.nombres} ({self.get_anio_display()})"

    # ---------- CUENTA DE ACCESO DEL CADETE ----------
    # Usuario = CI. Clave inicial = primer apellido en minúsculas; en el primer ingreso
    # se le obliga a cambiarla. La clave NUNCA se toca al editar la ficha del estudiante:
    # solo al crear la cuenta o cuando el oficial pulsa "Restablecer clave".

    @property
    def clave_inicial(self):
        return self.apellidos.strip().split()[0].lower()

    def save(self, *args, **kwargs):
        if self.egresado:
            self.activo = False  # Un egresado ya no hace guardia ni puede iniciar sesión
        super().save(*args, **kwargs)
        self.sincronizar_cuenta()

    def sincronizar_cuenta(self):
        """Crea, vincula o actualiza la cuenta del cadete sin cambiar su contraseña"""
        ci = (self.ci or '').strip()
        user = self.usuario

        if user is None:
            if not ci:
                return  # Sin CI no hay cuenta: se creará cuando el oficial cargue el CI
            user = User.objects.filter(username=ci).first()
            if user is None:
                user = User(username=ci)
            elif not cuenta_reutilizable(user):
                return  # El CI choca con una cuenta ajena; el formulario ya lo impide
            user.first_name, user.last_name = self.nombres, self.apellidos
            user.is_active = self.activo
            user.set_password(self.clave_inicial)
            user.save()
            Estudiante.objects.filter(pk=self.pk).update(usuario=user, debe_cambiar_clave=True)
            self.usuario, self.debe_cambiar_clave = user, True
            return

        if user.is_staff or user.is_superuser:
            return  # Nunca modificar cuentas de oficiales desde la ficha de un estudiante

        user.first_name, user.last_name = self.nombres, self.apellidos
        user.is_active = self.activo  # Estudiante inactivo = no puede iniciar sesión
        if ci and user.username != ci and not User.objects.filter(username=ci).exists():
            user.username = ci  # Si se corrigió el CI, el usuario lo sigue
        user.save()

    def restablecer_clave(self):
        """El oficial devuelve la cuenta a la clave inicial (primer apellido)"""
        if self.usuario is None:
            return False
        self.usuario.set_password(self.clave_inicial)
        self.usuario.save(update_fields=['password'])
        Estudiante.objects.filter(pk=self.pk).update(debe_cambiar_clave=True)
        self.debe_cambiar_clave = True
        return True


def cuenta_reutilizable(user):
    """Una cuenta existente solo se puede vincular a un estudiante si no es de un oficial
    y no pertenece ya a otro estudiante (cuentas viejas creadas antes del vínculo)."""
    from .permisos import GRUPO_OFICIAL
    return not (
        user.is_staff or user.is_superuser
        or user.groups.filter(name=GRUPO_OFICIAL).exists()
        or Estudiante.objects.filter(usuario=user).exists()
    )


@receiver(post_delete, sender=Estudiante)
def borrar_cuenta_del_estudiante(sender, instance, **kwargs):
    """Al eliminar un estudiante se elimina su cuenta, para que no pueda seguir entrando"""
    if instance.usuario_id:
        User.objects.filter(pk=instance.usuario_id, is_staff=False, is_superuser=False).delete()


class PromocionAnual(models.Model):
    """Registro de cada 'Promoción de año' (febrero): guarda el estado anterior de cada
    cadete para poder deshacerla si se hizo por error."""
    realizada_en = models.DateTimeField(auto_now_add=True)
    realizada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    resumen = models.JSONField(default=dict)  # {'egresados': n, 'a_2do': n, 'a_3ro': n, 'a_4to': n, 'repiten': n}
    cambios = models.JSONField(default=list)  # [{'id', 'anio', 'activo', 'egresado'}] estado ANTES de promover
    deshecha_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-realizada_en']

    def __str__(self):
        return f"Promoción del {self.realizada_en:%d/%m/%Y}" + (" (deshecha)" if self.deshecha_en else "")


class Matricula(models.Model):
    """Relaciona al estudiante con la gestión académica y su estado anual"""
    OPCIONES_RESULTADO = [
        ('CURSANDO', 'Cursando'),
        ('APROBADO', 'Aprobado'),
        ('REPROBADO', 'Reprobado'),
        ('EGRESADO', 'Egresado'),
        ('BAJA', 'Baja'),
    ]
    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE)
    gestion = models.ForeignKey(Gestion, on_delete=models.CASCADE)
    anio = models.IntegerField()  # Año que cursa en esta gestión específica
    resultado = models.CharField(max_length=20, choices=OPCIONES_RESULTADO, default='CURSANDO')

    class Meta:
        unique_together = ('estudiante', 'gestion')

    def __str__(self):
        return f"{self.estudiante} - {self.gestion} [{self.resultado}]"


# ==========================================================
# FASE 2: ESQUEMAS Y PUESTOS DE GUARDIA
# ==========================================================

class EsquemaGuardia(models.Model):
    """Plantilla de puestos de un día de guardia (Ej. Esquema A sin 1er año, Esquema B con 1er año).
    Qué esquema rige cada día lo deciden sus vigencias (fechas), no un interruptor manual."""
    nombre = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.nombre

    def vigente_en(self, fecha):
        return self.esquemavigencia_set.filter(fecha_desde__lte=fecha).filter(
            models.Q(fecha_hasta__gte=fecha) | models.Q(fecha_hasta__isnull=True)
        ).exists()

class EsquemaVigencia(models.Model):
    """Controla la fecha de inicio y fin en que rige un determinado esquema"""
    esquema = models.ForeignKey(EsquemaGuardia, on_delete=models.CASCADE)
    fecha_desde = models.DateField()
    fecha_hasta = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Vigencia de {self.esquema} ({self.fecha_desde} al {self.fecha_hasta or 'Indefinido'})"

    def clean(self):
        """Evita fechas invertidas y vigencias superpuestas (cada día debe tener un solo esquema)"""
        from django.core.exceptions import ValidationError
        if self.fecha_hasta and self.fecha_hasta < self.fecha_desde:
            raise ValidationError({'fecha_hasta': "La fecha final no puede ser anterior a la inicial."})
        choques = EsquemaVigencia.objects.exclude(pk=self.pk).filter(
            models.Q(fecha_hasta__isnull=True) | models.Q(fecha_hasta__gte=self.fecha_desde)
        )
        if self.fecha_hasta:
            choques = choques.filter(fecha_desde__lte=self.fecha_hasta)
        choque = choques.select_related('esquema').first()
        if choque:
            raise ValidationError(
                f"Se superpone con la vigencia de {choque.esquema.nombre} "
                f"({choque.fecha_desde:%d/%m/%Y} al {choque.fecha_hasta:%d/%m/%Y})." if choque.fecha_hasta else
                f"Se superpone con la vigencia de {choque.esquema.nombre} (desde {choque.fecha_desde:%d/%m/%Y}, sin fin)."
            )


class Puesto(models.Model):
    """Define los puestos específicos que componen la guardia según el esquema"""
    OPCIONES_CARGO = [
        ('COMANDANTE', 'Comandante'),
        ('SARGENTO', 'Sargento'),
        ('NUMERO', 'Número'),
    ]
    esquema = models.ForeignKey(EsquemaGuardia, on_delete=models.CASCADE)
    nombre = models.CharField(max_length=50) # Ej. Puesto 1 - Prevención
    cargo = models.CharField(max_length=30, choices=OPCIONES_CARGO)
    anio_requerido = models.IntegerField(  # Año que debe cursar el cadete (5to año no hace guardia)
        choices=[(a, n) for a, n in Estudiante.OPCIONES_ANIO if a in Estudiante.ANIOS_CON_GUARDIA]
    )
    orden = models.IntegerField(default=1)

    def __str__(self):
        return f"{self.nombre} - {self.esquema} (Año {self.anio_requerido})"


    # ==========================================================
# FASE 3: EJECUCIÓN, ASISTENCIA Y NOVEDADES
# ==========================================================

class GuardiaDia(models.Model):
    """Planificación general para una fecha específica"""
    OPCIONES_ESTADO = [
        ('BORRADOR', 'Borrador'),
        ('PUBLICADA', 'Publicada'),
        ('CERRADA', 'Cerrada'),
    ]
    fecha = models.DateField(unique=True)
    esquema = models.ForeignKey(EsquemaGuardia, on_delete=models.PROTECT)
    estado = models.CharField(max_length=20, choices=OPCIONES_ESTADO, default='BORRADOR')
    observaciones = models.TextField(blank=True, null=True)
    creado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Guardia del {self.fecha.strftime('%d/%m/%Y')} [{self.estado}]"

    # --- PUESTOS POR CARGO PARA LAS TABLAS (funcionan con cualquier esquema) ---
    # Usan detalles.all(): si la consulta trae prefetch_related('detalles__...'), no hacen consultas extra.
    def _detalles_con_cargo(self, cargo):
        return [d for d in self.detalles.all() if d.puesto.cargo == cargo]

    @property
    def comandante(self):
        detalles = self._detalles_con_cargo('COMANDANTE')
        return detalles[0] if detalles else None

    @property
    def sargento(self):
        detalles = self._detalles_con_cargo('SARGENTO')
        return detalles[0] if detalles else None

    @property
    def numeros(self):
        """Números de guardia, de mayor a menor año (Esquema A: 4 de 2do; Esquema B: 2 de 2do y 2 de 1ro)"""
        return sorted(self._detalles_con_cargo('NUMERO'), key=lambda d: (-d.puesto.anio_requerido, d.puesto.orden))

 

class DetalleGuardia(models.Model):
    """Asignación de un estudiante a un puesto específico en una fecha de guardia"""
    OPCIONES_ASISTENCIA = [
        ('PENDIENTE', 'Pendiente'),
        ('PRESENTE', 'Presente'),
        ('FALTA', 'Falta'),
        ('JUSTIFICADA', 'Justificada'),
        ('REEMPLAZADO', 'Reemplazado'),
        ('LICENCIA', 'Con Licencia'),
        ('PERMISO', 'Con Permiso'),
    ]
    guardia = models.ForeignKey(GuardiaDia, on_delete=models.CASCADE, related_name='detalles')
    puesto = models.ForeignKey(Puesto, on_delete=models.PROTECT)
    estudiante = models.ForeignKey(Estudiante, on_delete=models.PROTECT, related_name='asignaciones_guardia')
    # A quién le tocó este puesto según el rodillo. No cambia con permutas ni reemplazos:
    # el rodillo usa este campo para saber dónde continuar la fila.
    estudiante_rodillo = models.ForeignKey(
        Estudiante, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    asistencia = models.CharField(max_length=20, choices=OPCIONES_ASISTENCIA, default='PENDIENTE')
    ausencia = models.ForeignKey(
        'AusenciaLicencia', on_delete=models.SET_NULL, null=True, blank=True, related_name='detalles_afectados'
    )  # Licencia/permiso aprobado que cubre esta guardia
    observacion = models.TextField(blank=True, null=True)
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    registrado_en = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['guardia', 'puesto'], name='puesto_unico_por_guardia'),
            models.UniqueConstraint(fields=['guardia', 'estudiante'], name='estudiante_unico_por_guardia')
        ]

    def __str__(self):
        return f"{self.guardia.fecha} - {self.puesto.nombre}: {self.estudiante}"


def ruta_justificativo(instance, filename):
    """Guarda cada justificativo en una carpeta por estudiante"""
    return f"justificativos/estudiante_{instance.estudiante_id}/{filename}"


EXTENSIONES_JUSTIFICATIVO = ['jpg', 'jpeg', 'png', 'webp', 'heic', 'pdf']
TAMANO_MAX_JUSTIFICATIVO_MB = 5


class AusenciaLicencia(models.Model):
    """Solicitudes y registros de licencias, ausencias y permisos de cadetes"""
    # Licencias: el cadete queda "Con Licencia" en sus guardias
    TIPOS_LICENCIA = [
        ('SALUD', 'Licencia por Salud / Baja Médica'),
        ('CUMPLEANOS', 'Licencia por Cumpleaños'),
        ('FAMILIAR', 'Licencia por Motivos Familiares'),
        ('LICENCIA', 'Licencia por Otros Motivos'),
    ]
    # Ausencias y permisos: el cadete queda "Con Permiso" en sus guardias
    TIPOS_PERMISO = [
        ('AUSENCIA', 'Ausencia por Motivo Personal'),
        ('PERMISO_EMI', 'Permiso Institucional de la EMI'),
        ('PERMISO', 'Permiso Especial'),
        ('COMISION', 'Comisión Oficial'),
        ('OTRO', 'Otro Motivo'),
    ]
    OPCIONES_TIPO = [
        ('Licencias', TIPOS_LICENCIA),
        ('Ausencias y Permisos', TIPOS_PERMISO),
    ]
    OPCIONES_ESTADO = [
        ('PENDIENTE', 'Pendiente'),
        ('APROBADA', 'Aprobada'),
        ('RECHAZADA', 'Rechazada'),
    ]

    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='ausencias')
    tipo = models.CharField(max_length=20, choices=OPCIONES_TIPO)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    motivo = models.TextField()
    justificativo = models.FileField(
        upload_to=ruta_justificativo, null=True, blank=True,
        validators=[FileExtensionValidator(EXTENSIONES_JUSTIFICATIVO)],
    )
    estado = models.CharField(max_length=20, choices=OPCIONES_ESTADO, default='PENDIENTE')
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)  # Quién la creó (cadete u oficial)
    fecha_solicitud = models.DateTimeField(auto_now_add=True, null=True)
    resuelto_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='ausencias_resueltas'
    )
    fecha_resolucion = models.DateTimeField(null=True, blank=True)
    observacion_oficial = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.estudiante} ({self.tipo}: {self.fecha_inicio} al {self.fecha_fin}) [{self.estado}]"

    @property
    def es_licencia(self):
        return self.tipo in dict(self.TIPOS_LICENCIA)

    @property
    def estado_asistencia(self):
        """Valor que toma DetalleGuardia.asistencia cuando esta solicitud se aprueba"""
        return 'LICENCIA' if self.es_licencia else 'PERMISO'

    @property
    def justificativo_es_imagen(self):
        nombre = self.justificativo.name.lower() if self.justificativo else ''
        return nombre.endswith(('.jpg', '.jpeg', '.png', '.webp'))

    def aplicar_a_guardias(self, usuario):
        """Marca como Con Licencia / Con Permiso las guardias del cadete dentro del rango.
        Devuelve la cantidad de guardias afectadas."""
        detalles = DetalleGuardia.objects.filter(
            estudiante=self.estudiante,
            guardia__fecha__gte=self.fecha_inicio,
            guardia__fecha__lte=self.fecha_fin,
        )
        return detalles.update(
            asistencia=self.estado_asistencia,
            ausencia=self,
            observacion=f"{self.get_tipo_display()} aprobada (solicitud #{self.id})",
            registrado_por=usuario,
            registrado_en=timezone.now(),
        )


class Cambio(models.Model):
    """Permuta o reemplazo entre cadetes.
    Flujo: cadete A solicita -> cadete B acepta -> oficial aprueba -> se aplica.
    Si lo registra el oficial, se aplica directo. Ver inicio/permutas.py"""
    OPCIONES_TIPO = [
        ('PERMUTA', 'Permuta entre Cadetes'),
        ('REEMPLAZO', 'Reemplazo por Fuerza Mayor'),
    ]
    OPCIONES_ESTADO = [
        ('ESPERA_CADETE', 'Esperando respuesta del cadete'),
        ('ESPERA_OFICIAL', 'Esperando aprobación del oficial'),
        ('APROBADO', 'Aprobado y aplicado'),
        ('RECHAZADO', 'Rechazado'),
        ('CANCELADO', 'Cancelado por el solicitante'),
        ('VENCIDO', 'Vencido'),
    ]
    ESTADOS_ABIERTOS = ('ESPERA_CADETE', 'ESPERA_OFICIAL')

    tipo = models.CharField(max_length=20, choices=OPCIONES_TIPO)
    detalle_origen = models.ForeignKey(DetalleGuardia, on_delete=models.CASCADE, related_name='cambios_origen')
    detalle_destino = models.ForeignKey(DetalleGuardia, on_delete=models.CASCADE, null=True, blank=True, related_name='cambios_destino')
    # Quiénes estaban en cada guardia al pedir el cambio (para detectar si algo cambió antes de aprobar)
    estudiante_origen = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='cambios_solicitados')
    estudiante_destino = models.ForeignKey(Estudiante, on_delete=models.CASCADE, null=True, blank=True, related_name='cambios_recibidos')
    motivo = models.TextField()
    estado = models.CharField(max_length=20, choices=OPCIONES_ESTADO, default='ESPERA_CADETE')
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='cambios_registrados')
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    # Respuesta del cadete B
    fecha_respuesta_cadete = models.DateTimeField(null=True, blank=True)
    respuesta_cadete = models.TextField(blank=True, default='')
    # Resolución del oficial
    fecha_resolucion = models.DateTimeField(null=True, blank=True)
    oficial = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='cambios_autorizados')
    observacion = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-fecha_solicitud']

    def __str__(self):
        return f"{self.get_tipo_display()} #{self.pk} [{self.get_estado_display()}]"

    @property
    def abierto(self):
        return self.estado in self.ESTADOS_ABIERTOS

    @property
    def fecha_limite(self):
        """La guardia más próxima involucrada: define hasta cuándo se puede resolver"""
        fechas = [self.detalle_origen.guardia.fecha]
        if self.detalle_destino_id:
            fechas.append(self.detalle_destino.guardia.fecha)
        return min(fechas)