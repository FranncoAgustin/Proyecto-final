from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator

class Cupon(models.Model):
    TECNICA_CHOICES = [
        ("TODAS", "Todas"),
        ("SUB", "Sublimación"),
        ("LAS", "Grabado láser"),
        ("3D", "Impresión 3D"),
        ("OTR", "Otro"),
    ]

    codigo = models.CharField(max_length=50, unique=True)
    descuento = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(100)]
    )

    tecnica = models.CharField(
        max_length=20,
        choices=TECNICA_CHOICES,
        default="TODAS",
    )

    usos_maximos = models.PositiveIntegerField(default=1)
    usos_realizados = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)

    fecha_inicio = models.DateTimeField(default=timezone.now)
    fecha_fin = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.codigo} ({self.descuento}%)"

    def disponible(self):
        if not self.activo:
            return False
        if self.usos_realizados >= self.usos_maximos:
            return False
        if self.fecha_fin and timezone.now() > self.fecha_fin:
            return False
        return True
