from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

# Nombre del grupo de Django cuyos miembros administran el sistema.
# Se crea en la migración 0009_grupo_oficial. El superusuario también cuenta como oficial.
GRUPO_OFICIAL = 'Oficial'


def es_oficial(user):
    """True si el usuario puede administrar el sistema (superusuario o miembro del grupo Oficial)"""
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    # Se cachea en el objeto para no consultar la BD varias veces por request
    if not hasattr(user, '_es_oficial'):
        user._es_oficial = user.groups.filter(name=GRUPO_OFICIAL).exists()
    return user._es_oficial


def solo_oficial(vista):
    """Restringe una vista a los oficiales; el resto vuelve al inicio con un mensaje"""
    @wraps(vista)
    @login_required
    def envoltura(request, *args, **kwargs):
        if not es_oficial(request.user):
            messages.error(request, "No tiene permisos para acceder a ese módulo.")
            return redirect('home')
        return vista(request, *args, **kwargs)
    return envoltura
