# cliente/context_processors.py
from decimal import Decimal
from pdf.models import ProductoPrecio


def carrito_y_favoritos(request):
    carrito = request.session.get("carrito", {})
    favoritos = request.session.get("favoritos", {})

    cart_items = []
    cart_total_qty = 0

    for prod_id, qty in carrito.items():
        try:
            producto = ProductoPrecio.objects.get(pk=prod_id)
        except ProductoPrecio.DoesNotExist:
            continue

        try:
            qty = int(qty)
        except ValueError:
            qty = 1

        subtotal = producto.precio * qty
        cart_items.append(
            {
                "id": producto.id,
                "nombre": producto.nombre_publico,
                "cantidad": qty,
                "precio": producto.precio,
                "subtotal": subtotal,
            }
        )
        cart_total_qty += qty

    favorites_items = []
    for prod_id in favoritos.keys():
        try:
            producto = ProductoPrecio.objects.get(pk=prod_id)
        except ProductoPrecio.DoesNotExist:
            continue

        imagen_url = None
        if hasattr(producto, "imagen") and producto.imagen:
            imagen_url = producto.imagen.url

        favorites_items.append(
            {
                "id": producto.id,
                "nombre": producto.nombre_publico,
                "imagen_url": imagen_url,
            }
        )

    return {
        "cart_items": cart_items,
        "cart_total_qty": cart_total_qty,
        "favorites_items": favorites_items,
        "favorites_count": len(favorites_items),
    }
