from .usuario_actual import fijar_usuario_actual, restaurar_usuario_actual


class UsuarioActualMiddleware:
    """Debe ir después de AuthenticationMiddleware en settings.MIDDLEWARE."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = fijar_usuario_actual(getattr(request, "user", None))
        try:
            return self.get_response(request)
        finally:
            restaurar_usuario_actual(token)
