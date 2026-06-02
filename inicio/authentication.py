from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import User
from .models import Estudiante

class EstudianteAuthBackend(BaseBackend):
    """
    Permite a los estudiantes de la EMI ingresar usando su Nombre como usuario 
    y su Apellido como contraseña (insensible a mayúsculas/minúsculas).
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
            
        try:
            # Limpiamos espacios en blanco y convertimos a minúsculas para evitar fallos de tipeo
            nombre_limpio = username.strip().lower()
            apellido_limpio = password.strip().lower()
            
            # Buscamos en la tabla de Estudiantes de la EMI
            # Usamos __iexact para que no falle por mayúsculas o minúsculas
            estudiante = Estudiante.objects.filter(
                nombre__iexact=nombre_limpio, 
                apellido__iexact=apellido_limpio
            ).first()
            
            if estudiante:
                # Si el estudiante existe, buscamos o creamos un usuario virtual en Django
                # para que pueda mantener la sesión abierta en el navegador
                username_virtual = f"est_{estudiante.id}"
                user, created = User.objects.get_or_create(username=username_virtual)
                
                if created:
                    user.first_name = estudiante.nombre
                    user.last_name = estudiante.apellido
                    user.save()
                    
                # Guardamos la referencia de qué estudiante es en el objeto de usuario temporal
                user.is_staff = False
                user.is_superuser = False
                return user
                
        except Exception:
            return None
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None