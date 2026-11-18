from .permisos import es_oficial


def rol_usuario(request):
    """Expone {{ es_oficial }} en todas las plantillas"""
    return {'es_oficial': es_oficial(request.user)}
