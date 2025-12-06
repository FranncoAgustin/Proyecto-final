from django.db import models

class ProductoPrecio(models.Model):
    # ⚠ SIN FK a ListaPrecioPDF acá
    sku = models.CharField(max_length=255, unique=True)
    nombre_publico = models.CharField(max_length=255)
    precio = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return self.nombre_publico