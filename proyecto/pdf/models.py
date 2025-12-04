from django.db import models

class ListaPrecioPDF(models.Model):
    """Modelo para almacenar el archivo PDF subido."""
    nombre = models.CharField(max_length=255)
    archivo_pdf = models.FileField(upload_to='listas_precios/')
    fecha_subida = models.DateTimeField(auto_now_add=True)
    nombre = models.CharField(max_length=255)
    archivo_pdf = models.FileField(upload_to='listas_precios/')
    fecha_subida = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return self.nombre

class ProductoPrecio(models.Model):
    """
    Modelo final para los productos en la base de datos. 
    Usaremos este modelo para guardar los productos extraídos.
    """
    lista_pdf = models.ForeignKey(ListaPrecioPDF, on_delete=models.SET_NULL, null=True, blank=True)
    
    # El nombre extraído del PDF (usado como SKU y para comparación)
    sku = models.CharField(max_length=255, unique=True) 
    
    # El nombre que verán los usuarios finales
    nombre_publico = models.CharField(max_length=255)
    
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    imagen = models.ImageField(upload_to='productos/', null=True, blank=True)
    ultima_actualizacion = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.nombre_publico} (SKU: {self.sku}) - ${self.precio}"
    
class FacturaProveedor(models.Model):
    # Usamos FileField para permitir tanto imágenes como PDFs
    archivo = models.FileField(upload_to='facturas/') 
    nombre_proveedor = models.CharField(max_length=255, blank=True, null=True)
    fecha_factura = models.DateField(null=True, blank=True)
    fecha_subida = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Factura {self.id} - {self.fecha_subida.strftime('%d/%m/%Y')}"

class ItemFactura(models.Model):
    factura = models.ForeignKey(FacturaProveedor, on_delete=models.CASCADE, related_name='items')
    producto = models.CharField(max_length=255)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.cantidad} x {self.producto}"