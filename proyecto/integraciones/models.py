from django.db import models
from django.utils import timezone
from django.conf import settings


class Pedido(models.Model):
    class Estado(models.TextChoices):
        CREADO = "CREADO", "Creado"
        PENDIENTE = "PENDIENTE", "Pendiente"
        APROBADO = "APROBADO", "Aprobado"
        RECHAZADO = "RECHAZADO", "Rechazado"
        CANCELADO = "CANCELADO", "Cancelado"
        SIN_FINALIZAR = "SIN_FINALIZAR", "Sin finalizar"

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pedidos",
    )

    creado_en = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.CREADO,
    )

    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    moneda = models.CharField(max_length=10, default="ARS")

    cupon_codigo = models.CharField(max_length=50, blank=True, default="")
    descuento_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ✅ para que el webhook no descuente stock dos veces
    stock_descontado = models.BooleanField(default=False)

    def __str__(self):
        return f"Pedido #{self.id} - {self.estado} - ${self.total}"


class PedidoItem(models.Model):
    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.CASCADE,
        related_name="items",
    )

    # snapshot
    producto_id = models.IntegerField()
    sku = models.CharField(max_length=255)
    titulo = models.CharField(max_length=255)

    # ✅ Guardar variante elegida (si aplica)
    variante_id = models.IntegerField(null=True, blank=True)

    cantidad = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.titulo} x {self.cantidad}"


class PagoMP(models.Model):
    pedido = models.OneToOneField(
        Pedido,
        on_delete=models.CASCADE,
        related_name="pago_mp",
    )

    preference_id = models.CharField(max_length=255, blank=True, default="")
    init_point = models.URLField(blank=True, default="")

    payment_id = models.CharField(max_length=50, blank=True, default="")
    status = models.CharField(max_length=50, blank=True, default="")
    status_detail = models.CharField(max_length=255, blank=True, default="")
    raw = models.JSONField(default=dict, blank=True)

    actualizado_en = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"MP Pedido #{self.pedido_id} - {self.status}"
