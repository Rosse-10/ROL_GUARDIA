from django.db import models

class Carrera(models.Model):
    nombre = models.CharField(max_length=50)
    def __str__(self): return self.nombre

class Estudiante(models.Model):
    nombre = models.CharField(max_length=50)
    apellido = models.CharField(max_length=50)
    anio = models.IntegerField()
    carrera = models.ForeignKey(Carrera, on_delete=models.CASCADE)
    def __str__(self): return f"{self.nombre} {self.apellido} - {self.anio}°"

class Rol(models.Model):
    nombre = models.CharField(max_length=50)
    def __str__(self): return self.nombre

class Mes(models.Model):
    OPCIONES_MES = [
        (1, 'Enero'), (2, 'Febrero'), (3, 'Marzo'), (4, 'Abril'),
        (5, 'Mayo'), (6, 'Junio'), (7, 'Julio'), (8, 'Agosto'),
        (9, 'Septiembre'), (10, 'Octubre'), (11, 'Noviembre'), (12, 'Diciembre'),
    ]
    mes = models.IntegerField(choices=OPCIONES_MES)
    anio = models.IntegerField()

    def __str__(self):
        return f"{self.get_mes_display()} {self.anio}"

class Guardia(models.Model):
    fecha_inicio = models.DateTimeField()
    fecha_fin = models.DateTimeField()
    mes = models.ForeignKey(Mes, on_delete=models.CASCADE)
    def __str__(self): return f"Guardia {self.fecha_inicio.strftime('%d/%m')} al {self.fecha_fin.strftime('%d/%m')}"

class Asignacion(models.Model):
    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE)
    guardia = models.ForeignKey(Guardia, on_delete=models.CASCADE)
    rol = models.ForeignKey(Rol, on_delete=models.CASCADE)
    def __str__(self): return f"{self.estudiante} - {self.rol}"