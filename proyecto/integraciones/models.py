from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.conf import settings
from pdf.models import ProductoPrecio


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

    # para que el webhook no descuente stock dos veces
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

    # Guardar variante elegida (si aplica)
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


Q2 = Decimal("0.01")


class PriceDocSource(models.Model):
    TIPO_CHOICES = [
        ("google_doc", "Google Doc"),
        ("google_sheet", "Google Sheet"),
        ("docx_drive", "DOCX en Drive"),
        ("pdf", "PDF"),
        ("web_html", "Scraping Web"), # <-- ¡Nueva fuente!
        ("otro", "Otro"),
    ]

    nombre = models.CharField(max_length=150)
    url = models.URLField(blank=True, default="")
    doc_id = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        help_text="ID del archivo en Drive (Dejar vacío si es web)"
    )

    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, default="google_doc")
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    es_principal = models.BooleanField(default=False)

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="price_sources_creadas",
    )
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="price_sources_actualizadas",
    )

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    # usados por el sync
    last_revision_id = models.CharField(max_length=255, blank=True, default="")
    last_modified_time = models.DateTimeField(null=True, blank=True)

    # estado informativo para mostrar en panel / front
    ultima_revision = models.DateTimeField(null=True, blank=True)
    ultimo_estado = models.CharField(max_length=50, blank=True, default="")
    ultimo_error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.es_principal:
            PriceDocSource.objects.exclude(pk=self.pk).update(es_principal=False)


class PriceDocSnapshot(models.Model):
    """
    Un snapshot completo de una fuente en un momento dado.
    Se usa para comparar el último contra el anterior.
    """
    source = models.ForeignKey(
        PriceDocSource,
        on_delete=models.CASCADE,
        related_name="snapshots",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Snapshot {self.id} de {self.source} ({self.creado_en})"


class PriceDocItem(models.Model):
    """
    Una fila detectada dentro del snapshot.
    'compra' es el precio del proveedor leído desde el documento.
    """
    snapshot = models.ForeignKey(
        PriceDocSnapshot,
        on_delete=models.CASCADE,
        related_name="items",
    )

    art = models.CharField(max_length=120, db_index=True)
    producto = models.CharField(max_length=255, blank=True, default="")
    descripcion = models.TextField(blank=True, default="")
    compra = models.DecimalField(max_digits=12, decimal_places=2)
    imagen_url = models.URLField(max_length=500, blank=True, null=True)

    def __str__(self):
        return f"{self.art} - {self.compra}"


class PriceUpdateCandidate(models.Model):
    """
    Cambio detectado entre dos snapshots para un ART.
    Guarda el costo viejo/nuevo y una sugerencia de venta.
    """
    source = models.ForeignKey(
        PriceDocSource,
        on_delete=models.CASCADE,
        related_name="candidates",
    )

    art = models.CharField(max_length=120, db_index=True)
    producto_doc = models.CharField(max_length=255, blank=True, default="")
    descripcion_doc = models.TextField(blank=True, default="")

    old_compra = models.DecimalField(max_digits=12, decimal_places=2)
    new_compra = models.DecimalField(max_digits=12, decimal_places=2)

    # Match con ProductoPrecio
    producto = models.ForeignKey(
        ProductoPrecio,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    sku_match = models.CharField(max_length=120, blank=True, default="")
    match_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Venta actual y sugerida
    venta_actual = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    venta_sugerida = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # % de aumento sugerido sobre la venta actual
    pct_aumento_venta = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)

    # Workflow
    aprobado = models.BooleanField(default=False)
    aplicado = models.BooleanField(default=False)
    creado_en = models.DateTimeField(auto_now_add=True)
    aplicado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["source", "art"]),
            models.Index(fields=["aprobado", "aplicado"]),
        ]

    def __str__(self):
        return f"{self.art} ({self.old_compra} → {self.new_compra})"

    def calcular_sugerencia(self):
        """
        Mantiene el mismo factor/margen relativo de venta respecto del costo.
        venta_sugerida = venta_actual * (new_compra / old_compra)
        """
        if not self.producto or not self.old_compra or self.old_compra <= 0:
            self.venta_actual = None
            self.venta_sugerida = None
            self.pct_aumento_venta = None
            return

        venta_actual = self.producto.precio or Decimal("0.00")
        self.venta_actual = venta_actual.quantize(Q2)

        factor_costo = self.new_compra / self.old_compra
        venta_nueva = (venta_actual * factor_costo).quantize(Q2)
        self.venta_sugerida = venta_nueva

        if venta_actual > 0:
            pct = ((venta_nueva / venta_actual) - Decimal("1.0")) * Decimal("100")
            self.pct_aumento_venta = pct.quantize(Q2)
        else:
            self.pct_aumento_venta = None

class ScrapingProveedor(models.Model):
    """
    Proveedor externo del cual obtenemos productos mediante scraping.
    """

    nombre = models.CharField(max_length=150)

    url = models.URLField(
        help_text="URL principal del proveedor."
    )

    activo = models.BooleanField(default=True)

    METODO_CHOICES = [
        ("manual", "Manual"),
        ("html", "HTML"),
        ("api", "API"),
    ]

    metodo = models.CharField(
        max_length=20,
        choices=METODO_CHOICES,
        default="html",
    )

    ultima_actualizacion = models.DateTimeField(
        null=True,
        blank=True,
    )

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class ProductoScrapeado(models.Model):
    """
    Producto obtenido desde un proveedor externo.

    NO guarda historial infinito de precios.
    Solo conserva:
        - precio_actual
        - precio_anterior

    Cuando el proveedor cambia el precio:

        precio_anterior = precio_actual
        precio_actual = nuevo_precio
    """

    proveedor = models.ForeignKey(
        ScrapingProveedor,
        on_delete=models.CASCADE,
        related_name="productos",
    )

    nombre = models.CharField(max_length=255)

    precio_actual = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    precio_anterior = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    imagen_url = models.URLField(
        max_length=1000,
        blank=True,
        default="",
    )

    url_producto = models.URLField(
        max_length=1000,
    )

    disponible = models.BooleanField(
        default=True,
    )

    actualizado_en = models.DateTimeField(
        auto_now=True,
    )

    creado_en = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["nombre"]

        constraints = [
            models.UniqueConstraint(
                fields=["proveedor", "url_producto"],
                name="unique_producto_scrapeado_proveedor_url",
            )
        ]

        indexes = [
            models.Index(fields=["proveedor", "nombre"]),
            models.Index(fields=["disponible"]),
        ]

    def __str__(self):
        return f"{self.nombre} - {self.proveedor}"


class ProductoProveedor(models.Model):
    """
    Relaciona un producto de Mundo Personalizado
    con un producto específico de un proveedor externo.
    """

    producto_scrapeado = models.OneToOneField(
        ProductoScrapeado,
        on_delete=models.CASCADE,
        related_name="vinculo_catalogo",
    )

    producto = models.ForeignKey(
        ProductoPrecio,
        on_delete=models.CASCADE,
        related_name="proveedores_scraping",
    )

    creado_en = models.DateTimeField(
        auto_now_add=True,
    )

    actualizado_en = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["producto_scrapeado", "producto"],
                name="unique_producto_proveedor_scraping",
            )
        ]

    def __str__(self):
        return f"{self.producto} ← {self.producto_scrapeado}"