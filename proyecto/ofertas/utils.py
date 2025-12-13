from django.utils import timezone
from .models import Oferta

def aplicar_oferta(producto):
    ahora = timezone.now()

    ofertas = Oferta.objects.filter(
        activa=True,
        fecha_inicio__lte=ahora,
        fecha_fin__gte=ahora,
    )

    for oferta in ofertas:
        if oferta.tecnica == "ALL" or oferta.tecnica == producto.tech:
            descuento = oferta.descuento
            precio_final = producto.precio * (100 - descuento) / 100
            return round(precio_final, 2), oferta

    return producto.precio, None
