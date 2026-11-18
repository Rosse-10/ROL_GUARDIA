from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class ForzarCambioClaveMiddleware:
    """Mientras el cadete use su clave inicial (primer apellido), solo puede ver la
    pantalla de cambio de contraseña o cerrar sesión."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated:
            estudiante = getattr(user, 'estudiante', None)
            if estudiante is not None and estudiante.debe_cambiar_clave:
                permitidas = (reverse('cambiar_clave'), reverse('logout'), settings.STATIC_URL)
                if not request.path.startswith(permitidas):
                    return redirect('cambiar_clave')
        return self.get_response(request)
