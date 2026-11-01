"""
Usuario de la petición en curso, accesible desde las señales (RF-20).

Las señales de Django (post_save, post_delete) no reciben el request. El
middleware `UsuarioActualMiddleware` guarda el usuario en una variable de
contexto durante la petición, así la bitácora puede registrar quién hizo el
cambio aunque venga de una vista, del admin o de un formulario.
"""

import contextvars

_usuario = contextvars.ContextVar("usuario_actual", default=None)


def obtener_usuario_actual():
    """Usuario autenticado de la petición, o None (comandos, tests, shell)."""
    usuario = _usuario.get()
    if usuario is not None and getattr(usuario, "is_authenticated", False):
        return usuario
    return None


def fijar_usuario_actual(usuario):
    """Devuelve el token para restaurar el valor anterior con reset()."""
    return _usuario.set(usuario)


def restaurar_usuario_actual(token):
    _usuario.reset(token)
