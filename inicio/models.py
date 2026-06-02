from django.db import models

class Carrera(models.Model):
    OPCIONES_CARRERA = [
        ('SISTEMAS', 'Ingeniería de Sistemas'),
        ('CIVIL', 'Ingeniería Civil'),
        ('COMERCIAL', 'Ingeniería Comercial'),
    ]
    nombre = models.CharField(max_length=50, choices=OPCIONES_CARRERA, unique=True)

    def __str__(self):
        return self.get_nombre_display()

class Estudiante(models.Model):
    OPCIONES_ANIO = [
        (1, 'Primer Año'),
        (2, 'Segundo Año'),
        (3, 'Tercer Año'),
        (4, 'Cuarto Año'),
    ]
    nombre = models.CharField(max_length=50)
    apellido = models.CharField(max_length=50)
    anio = models.IntegerField(choices=OPCIONES_ANIO)
    carrera = models.ForeignKey(Carrera, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.nombre} {self.apellido} - {self.get_anio_display()} ({self.carrera})"

class GuardiaDia(models.Model):
    fecha = models.DateField(unique=True)  # Cada fecha del calendario es única
    
    # Los 6 cupos obligatorios diarios por jerarquía requeridos para la EMI:
    estudiante_4to = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='guardias_4to')
    estudiante_3ro = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='guardias_3ro')
    estudiante_2do_1 = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='guardias_2do_1')
    estudiante_2do_2 = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='guardias_2do_2')
    estudiante_1ro_1 = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='guardias_1ro_1')
    estudiante_1ro_2 = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='guardias_1ro_2')

    def __str__(self):
        return f"Guardia del {self.fecha.strftime('%d/%m/%Y')}"