from django.db import models

class ProductoPrecio(models.Model):
    # ⚠ SIN FK a ListaPrecioPDF acá
    sku = models.CharField(max_length=255, unique=True)
    nombre_publico = models.CharField(max_length=255)
    precio = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return self.nombre_publico
    
class SiteInfoBlock(models.Model):
    """
    Bloques de info que se muestran en el footer tipo acordeón:
    - Quiénes somos
    - Cómo trabajamos
    - Métodos de envío
    - Garantías
    etc.
    """

    CLAVE_CHOICES = [
        ("about", "Quiénes somos"),
        ("work", "Cómo trabajamos"),
        ("shipping", "Métodos de envío"),
        ("warranty", "Garantías"),
        ("other", "Otro"),
    ]

    clave = models.CharField(
        max_length=30,
        choices=CLAVE_CHOICES,
        unique=True,
        help_text="Identificador interno (no se muestra al cliente).",
    )
    titulo = models.CharField(max_length=80)
    contenido = models.TextField(help_text="Texto que se muestra dentro del acordeón.")
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["orden", "titulo"]

    def __str__(self):
        return self.titulo