from django.db import models

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
        D3  = "3D",  "Impresión 3D"
        OTR = "OTR", "Otro"

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

    precio_costo = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    imagen = models.ImageField(upload_to='productos/', null=True, blank=True)

    # Precio de venta actual
    precio = models.DecimalField(max_digits=10, decimal_places=2)

    # Stock actual (para tu control interno)
    stock = models.IntegerField(default=0)

    # Técnica principal
    tech = models.CharField(
        max_length=3,
        choices=TechChoices.choices,
        blank=True,
        default="",
    )

    # Si está activo se puede vender / mostrar
    activo = models.BooleanField(default=True)

    # Fechas
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    ultima_actualizacion = models.DateTimeField(auto_now=True, null=True, blank=True)
    def __str__(self):
        return f"{self.nombre_publico} (SKU: {self.sku}) - ${self.precio}"
    
    


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

    stock = models.IntegerField(default=0)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["orden", "id"]

    def __str__(self):
        return f"{self.producto.sku} - {self.nombre}"