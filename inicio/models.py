from django.db import models
from django.contrib.auth.models import User


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
    ]
    ci = models.CharField(max_length=20, unique=True, null=True, blank=True)
    nombres = models.CharField(max_length=50)
    apellidos = models.CharField(max_length=50)
    anio = models.IntegerField(choices=OPCIONES_ANIO)
    carrera = models.ForeignKey(Carrera, on_delete=models.PROTECT)
    activo = models.BooleanField(default=True)
    habilitado_desde = models.DateField(null=True, blank=True)  # Clave para el ingreso de 1er año

    def __str__(self):
        return f"{self.apellidos} {self.nombres} ({self.get_anio_display()})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)  # Guardar primero el estudiante en la BD

        # Definir el nombre de usuario (CI si existe, o primer nombre en minúsculas)
        if self.ci and self.ci.strip():
            username_estudiante = str(self.ci).strip()
        else:
            username_estudiante = self.nombres.strip().split()[0].lower()

        # Definir la contraseña (primer apellido en minúsculas)
        password_estudiante = self.apellidos.strip().split()[0].lower()

        # Crear o actualizar en auth_user
        user, creado = User.objects.get_or_create(
            username=username_estudiante,
            defaults={
                'first_name': self.nombres,
                'last_name': self.apellidos,
                'is_staff': False,
                'is_superuser': False
            }
        )

        if not creado:
            user.first_name = self.nombres
            user.last_name = self.apellidos

        user.set_password(password_estudiante)
        user.save()


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
    """Representa los esquemas de guardia (Ej. Esquema A, Esquema B)"""
    nombre = models.CharField(max_length=50, unique=True)
    activo = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.nombre} ({'Activo' if self.activo else 'Inactivo'})"

class EsquemaVigencia(models.Model):
    """Controla la fecha de inicio y fin en que rige un determinado esquema"""
    esquema = models.ForeignKey(EsquemaGuardia, on_delete=models.CASCADE)
    fecha_desde = models.DateField()
    fecha_hasta = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Vigencia de {self.esquema} ({self.fecha_desde} al {self.fecha_hasta or 'Indefinido'})"


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
    anio_requerido = models.IntegerField() # Año que debe cursar el cadete (1 a 4)
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

    # --- PROPIEDADES AUXILIARES PARA LAS TABLAS ---
    @property
    def estudiante_4to(self):
        d = self.detalles.filter(puesto__anio_requerido=4).first()
        return d.estudiante if d else None

    @property
    def estudiante_3ro(self):
        d = self.detalles.filter(puesto__anio_requerido=3).first()
        return d.estudiante if d else None

    @property
    def estudiante_2do_1(self):
        ds = self.detalles.filter(puesto__anio_requerido=2)
        return ds[0].estudiante if ds.count() > 0 else None

    @property
    def estudiante_2do_2(self):
        ds = self.detalles.filter(puesto__anio_requerido=2)
        return ds[1].estudiante if ds.count() > 1 else None

    @property
    def estudiante_1ro_1(self):
        ds = self.detalles.filter(puesto__anio_requerido=1)
        return ds[0].estudiante if ds.count() > 0 else None

    @property
    def estudiante_1ro_2(self):
        ds = self.detalles.filter(puesto__anio_requerido=1)
        return ds[1].estudiante if ds.count() > 1 else None

 

class DetalleGuardia(models.Model):
    """Asignación de un estudiante a un puesto específico en una fecha de guardia"""
    OPCIONES_ASISTENCIA = [
        ('PENDIENTE', 'Pendiente'),
        ('PRESENTE', 'Presente'),
        ('FALTA', 'Falta'),
        ('JUSTIFICADA', 'Justificada'),
        ('REEMPLAZADO', 'Reemplazado'),
    ]
    guardia = models.ForeignKey(GuardiaDia, on_delete=models.CASCADE, related_name='detalles')
    puesto = models.ForeignKey(Puesto, on_delete=models.PROTECT)
    estudiante = models.ForeignKey(Estudiante, on_delete=models.PROTECT, related_name='asignaciones_guardia')
    asistencia = models.CharField(max_length=20, choices=OPCIONES_ASISTENCIA, default='PENDIENTE')
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


class AusenciaLicencia(models.Model):
    """Control de bajas médicas, permisos, licencias o comisiones de cadetes"""
    OPCIONES_TIPO = [
        ('LICENCIA', 'Licencia'),
        ('SALUD', 'Baja Médica / Salud'),
        ('PERMISO', 'Permiso Especial'),
        ('COMISION', 'Comisión Oficial'),
    ]
    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='ausencias')
    tipo = models.CharField(max_length=20, choices=OPCIONES_TIPO)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    motivo = models.TextField()
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.estudiante} ({self.tipo}: {self.fecha_inicio} al {self.fecha_fin})"


class Cambio(models.Model):
    """Gestión de permutas o reemplazos entre cadetes para una guardia"""
    OPCIONES_TIPO = [
        ('PERMUTA', 'Permuta entre Cadetes'),
        ('REEMPLAZO', 'Reemplazo por Fuerza Mayor'),
    ]
    OPCIONES_ESTADO = [
        ('PENDIENTE', 'Pendiente de Aprobación'),
        ('ACEPTADO', 'Aceptado / Aprobado'),
        ('RECHAZADO', 'Rechazado'),
    ]
    tipo = models.CharField(max_length=20, choices=OPCIONES_TIPO)
    detalle_origen = models.ForeignKey(DetalleGuardia, on_delete=models.CASCADE, related_name='cambios_origen')
    detalle_destino = models.ForeignKey(DetalleGuardia, on_delete=models.CASCADE, null=True, blank=True, related_name='cambios_destino')
    estudiante_origen = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='cambios_solicitados')
    estudiante_destino = models.ForeignKey(Estudiante, on_delete=models.CASCADE, null=True, blank=True, related_name='cambios_recibidos')
    motivo = models.TextField()
    estado = models.CharField(max_length=20, choices=OPCIONES_ESTADO, default='PENDIENTE')
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    fecha_resolucion = models.DateTimeField(null=True, blank=True)
    oficial_id = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='cambios_autorizados')
    observacion = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Cambio ({self.tipo}) - {self.estado}"