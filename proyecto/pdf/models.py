from django.db import models
from django.db.models import Sum
from decimal import Decimal


class ListaPrecioPDF(models.Model):
    """Modelo para almacenar el archivo PDF subido."""
    nombre = models.CharField(max_length=255)
    archivo_pdf = models.FileField(upload_to='listas_precios/')
    fecha_subida = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre


class ProductoPrecio(models.Model):
    """
    Modelo final para los productos en la base de datos.
    Usaremos este modelo para guardar los productos extraídos.
    También lo usamos como catálogo de la tienda en el panel Owner.
    """

    class TechChoices(models.TextChoices):
        SUB = "SUB", "Sublimación"
        LAS = "LAS", "Grabado láser"
        D3 = "3D", "Impresión 3D"
        OTR = "OTR", "Otro"

    class RubroChoices(models.TextChoices):
        MATES = "MATES", "Mates"
        DIJES = "DIJES", "Dijes de acero"
        BOMB = "BOMB", "Bombillas"
        TERM = "TERM", "Termos"
        TAZA = "TAZA", "Tazas"
        LLAV = "LLAV", "Llaveros"
        OTRO = "OTRO", "Otros"

    lista_pdf = models.ForeignKey(
        ListaPrecioPDF,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="productos",
    )

    # El nombre extraído del PDF (usado como SKU y para comparación)
    sku = models.CharField(max_length=255, unique=True)

    # El nombre que verán los usuarios finales
    nombre_publico = models.CharField(max_length=255)

    descripcion = models.TextField(blank=True, default="")

    precio_costo = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    imagen = models.ImageField(upload_to='productos/', null=True, blank=True)

    # Precio de venta actual
    precio = models.DecimalField(max_digits=10, decimal_places=2)

    # Stock actual del producto padre.
    # Se usa solo cuando NO hay variantes activas.
    stock = models.IntegerField(default=0)

    # Técnica principal (Sublimación / Grabado láser / 3D / Otros)
    tech = models.CharField(
        max_length=3,
        choices=TechChoices.choices,
        blank=True,
        default="",
    )

    # Filtros del menú (EDITABLES DESDE EL OWNER)
    rubro = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text="Ej: Mates, Dijes de acero, Tazas, Llaveros..."
    )
    subrubro = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text="Ej: Mate Imperial, Mate Camionero, Dije corazón, etc."
    )

    # Si está activo se puede vender / mostrar
    activo = models.BooleanField(default=True)

    # Fechas
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    ultima_actualizacion = models.DateTimeField(auto_now=True, null=True, blank=True)

    def __str__(self):
        return f"{self.nombre_publico} (SKU: {self.sku}) - ${self.precio}"

    @property
    def tiene_variantes(self) -> bool:
        """
        Devuelve True si el producto tiene al menos una variante activa.
        """
        if not self.pk:
            return False
        return self.variantes.filter(activo=True).exists()

    @property
    def stock_total_variantes(self) -> int:
        """
        Suma del stock de todas las variantes activas.
        Solo informativo / calculado. No se guarda en el producto padre.
        """
        if not self.pk:
            return 0
        return self.variantes.filter(activo=True).aggregate(
            total=Sum("stock")
        )["total"] or 0

    @property
    def stock_disponible(self) -> int:
        """
        Stock real para usar en tienda:
        - si tiene variantes activas -> suma stock de variantes
        - si no -> stock del producto padre
        """
        if self.tiene_variantes:
            return self.stock_total_variantes
        return self.stock

    def normalizar_stock_segun_variantes(self, save=True):
        """
        Si tiene variantes activas, el producto padre no debe manejar stock propio.
        Entonces forzamos stock = 0.
        """
        if self.pk and self.variantes.filter(activo=True).exists() and self.stock != 0:
            self.stock = 0
            if save:
                ProductoPrecio.objects.filter(pk=self.pk).update(stock=0)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Ojo: en este punto ya existe self.pk.
        # Si todavía no hay variantes, no hace nada.
        self.normalizar_stock_segun_variantes(save=True)


class FacturaProveedor(models.Model):
    archivo = models.FileField(upload_to='facturas/')
    nombre_proveedor = models.CharField(max_length=255, blank=True, null=True)
    fecha_factura = models.DateField(null=True, blank=True)
    fecha_subida = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Factura {self.id} - {self.fecha_subida.strftime('%d/%m/%Y')}"


class ItemFactura(models.Model):
    factura = models.ForeignKey(
        FacturaProveedor,
        on_delete=models.CASCADE,
        related_name='items'
    )
    producto = models.CharField(max_length=255)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.cantidad} x {self.producto}"


class ProductoVariante(models.Model):
    producto = models.ForeignKey(
        "ProductoPrecio",
        on_delete=models.CASCADE,
        related_name="variantes",
    )

    nombre = models.CharField(max_length=120)  # ej: Rojo / Azul / Glitter
    descripcion_corta = models.CharField(max_length=255, blank=True, default="")
    imagen = models.ImageField(upload_to="productos/variantes/", null=True, blank=True)

    stock = models.PositiveIntegerField(default=0)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)

    # Precio propio de la variante (opcional)
    precio = models.DecimalField(
        "Precio de la variante",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Si lo dejás vacío, se usa el precio del producto."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["orden", "id"]

    def __str__(self):
        return f"{self.producto.sku} - {self.nombre}"

    def en_stock(self) -> bool:
        return self.stock > 0 and self.activo

    @property
    def precio_final(self):
        """
        Precio efectivo de la variante:
        - si tiene precio propio -> lo usa
        - si no -> usa el precio del producto principal
        """
        if self.precio is not None:
            return self.precio
        return self.producto.precio

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Cada vez que se guarda una variante, normalizamos el stock del padre.
        if self.producto_id:
            self.producto.normalizar_stock_segun_variantes(save=True)

    def delete(self, *args, **kwargs):
        producto = self.producto
        super().delete(*args, **kwargs)
        if producto and producto.pk:
            producto.normalizar_stock_segun_variantes(save=True)


class Factura(models.Model):
    creado = models.DateTimeField(auto_now_add=True)

    # Vendedor (precargado)
    vendedor_nombre = models.CharField(max_length=120, default="Mundo Personalizado")
    vendedor_whatsapp = models.CharField(max_length=50, default="11 5663-7260")
    vendedor_horario = models.CharField(max_length=80, default="9:00 a 20:00")
    vendedor_direccion = models.CharField(max_length=160, default="Virrey del Pino, La Matanza")

    # Cliente
    cliente_nombre = models.CharField(max_length=140)
    cliente_telefono = models.CharField(max_length=60, blank=True)
    cliente_doc = models.CharField(max_length=60, blank=True)  # DNI/CUIL
    cliente_direccion = models.CharField(max_length=180, blank=True)

    # Totales
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    def __str__(self):
        return f"Factura #{self.id} - {self.cliente_nombre}"


class FacturaItem(models.Model):
    factura = models.ForeignKey(Factura, on_delete=models.CASCADE, related_name="items")
    producto_nombre = models.CharField(max_length=200)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    cantidad = models.PositiveIntegerField(default=1)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    def save(self, *args, **kwargs):
        self.subtotal = (self.precio_unitario * self.cantidad)
        super().save(*args, **kwargs)


class Rubro(models.Model):
    """
    Filtro de nivel 1 (Mates, Tazas, Dijes, etc).
    Lo podés asociar a una técnica para que el menú se arme por técnica → rubro.
    """
    nombre = models.CharField(max_length=120)
    tech = models.CharField(
        max_length=3,
        choices=ProductoPrecio.TechChoices.choices,
        blank=True,
        default="",
    )
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["orden", "nombre"]
        unique_together = ("nombre", "tech")

    def __str__(self):
        return self.nombre


class SubRubro(models.Model):
    """
    Filtro de nivel 2 (por ejemplo: Mates imperiales, Mates camioneros, etc).
    """
    rubro = models.ForeignKey(
        Rubro,
        on_delete=models.CASCADE,
        related_name="subrubros",
    )
    nombre = models.CharField(max_length=120)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["orden", "nombre"]
        unique_together = ("rubro", "nombre")

    def __str__(self):
        return f"{self.rubro.nombre} → {self.nombre}"


class PDFBranding(models.Model):
    # Singleton: vas a usar siempre el registro id=1
    watermark = models.ImageField(upload_to="branding/", blank=True, null=True)

    def __str__(self):
        return "PDFBranding"