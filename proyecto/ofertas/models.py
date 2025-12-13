from django.db import models
from django.utils import timezone

class Oferta(models.Model):
    TECNICA_CHOICES = [
        ("ALL", "Todos"),
        ("SUB", "Sublimación"),
        ("LAS", "Láser"),
        ("3D", "Impresión 3D"),
        ("OTR", "Otro"),
    ]

    nombre = models.CharField(max_length=100)
    tecnica = models.CharField(max_length=3, choices=TECNICA_CHOICES, default="ALL")
    descuento = models.PositiveIntegerField(help_text="Porcentaje de descuento")
    fecha_inicio = models.DateTimeField()
    fecha_fin = models.DateTimeField()
    activa = models.BooleanField(default=True)

    def esta_activa(self):
        ahora = timezone.now()
        return self.activa and self.fecha_inicio <= ahora <= self.fecha_fin

    def __str__(self):
        return f"{self.nombre} ({self.descuento}%)"
