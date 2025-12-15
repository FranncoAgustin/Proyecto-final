from decimal import Decimal
from django.utils import timezone
from .models import Oferta

def get_precio_con_oferta(producto):
    precio_base = producto.precio
    ahora = timezone.now()

    ofertas = (
        Oferta.objects
        .filter(activo=True, fecha_inicio__lte=ahora, fecha_fin__gte=ahora)
    )

    for oferta in ofertas:
        if oferta.aplica_a_producto(producto):
            precio_final = oferta.aplicar_descuento(precio_base)
            return {
                "precio_original": precio_base,
                "precio_final": precio_final.quantize(Decimal("0.01")),
                "oferta": oferta,
            }

    return {
        "precio_original": precio_base,
        "precio_final": precio_base,
        "oferta": None,
    }

