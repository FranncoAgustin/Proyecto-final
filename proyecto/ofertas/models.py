from django.db import models
from django.utils import timezone
from pdf.models import ProductoPrecio

class Oferta(models.Model):
    class TipoDescuento(models.TextChoices):
        PORCENTAJE = "PCT", "Porcentaje"
        FIJO = "FIJ", "Monto fijo"

    nombre = models.CharField(max_length=100)

    tipo_descuento = models.CharField(
        max_length=3,
        choices=TipoDescuento.choices,
        default=TipoDescuento.PORCENTAJE,
    )

    valor = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Porcentaje (ej: 20) o monto fijo"
    )

    # Si está vacío → aplica a TODOS
    tecnicas = models.JSONField(
        blank=True,
        null=True,
        help_text="Ej: ['SUB', 'LAS']"
    )

    fecha_inicio = models.DateTimeField()
    fecha_fin = models.DateTimeField()

    activo = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def esta_activa(self):
        ahora = timezone.now()
        return (
            self.activo and
            self.fecha_inicio <= ahora <= self.fecha_fin
        )

    def aplica_a_producto(self, producto: ProductoPrecio):
        if not self.esta_activa():
            return False
        if not self.tecnicas:
            return True
        return producto.tech in self.tecnicas

    def aplicar_descuento(self, precio):
        if self.tipo_descuento == self.TipoDescuento.PORCENTAJE:
            return precio * (1 - self.valor / 100)
        return max(precio - self.valor, 0)

    def __str__(self):
        return self.nombre
