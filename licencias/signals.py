"""
La auditoría de licencias (alta, modificación y baja, con usuario) vive en la
bitácora única de reportes: ver `reportes/signals.py` (RF-20).

`RegistroBitacora` se conserva solo como historial de lo registrado antes de
unificar la auditoría; ya no se escribe en él.
"""