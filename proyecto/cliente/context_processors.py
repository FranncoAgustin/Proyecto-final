from decimal import Decimal
from pdf.models import ProductoPrecio, ProductoVariante
from ofertas.utils import get_precio_con_oferta

def _parse_item_key(k: str):
    # soporta "59:0" y también "59"
    try:
        if ":" in k:
            a, b = k.split(":", 1)
            return int(a), int(b)
        return int(k), 0
    except Exception:
        return None, None

def carrito_y_favoritos(request):
    carrito = request.session.get("carrito", {}) or {}
    favoritos = request.session.get("favoritos", {}) or {}

    cart_items = []
    cart_total_qty = 0

    for item_key, qty in carrito.items():
        prod_id, var_id = _parse_item_key(str(item_key))
        if not prod_id:
            continue

        producto = ProductoPrecio.objects.filter(pk=prod_id, activo=True).first()
        if not producto:
            continue

        variante = None
        if var_id and var_id != 0:
            variante = ProductoVariante.objects.filter(
                pk=var_id, producto=producto, activo=True
            ).first()

        try:
            qty = int(qty)
        except Exception:
            qty = 1

        # precio con oferta (coherente con tu carrito)
        precio_data = get_precio_con_oferta(producto)
        precio_unit = precio_data["precio_final"]

        subtotal = precio_unit * qty

        cart_items.append({
            "key": f"{prod_id}:{var_id}",   # clave real
            "id": producto.id,
            "nombre": producto.nombre_publico,
            "cantidad": qty,
            "precio": precio_unit,
            "subtotal": subtotal,
            "variante": variante,
        })
        cart_total_qty += qty

    favorites_items = []
    for prod_id in favoritos.keys():
        try:
            pid = int(prod_id)
        except Exception:
            continue

        producto = ProductoPrecio.objects.filter(pk=pid, activo=True).first()
        if not producto:
            continue

        imagen_url = producto.imagen.url if getattr(producto, "imagen", None) else None

        favorites_items.append({
            "id": producto.id,
            "nombre": producto.nombre_publico,
            "imagen_url": imagen_url,
        })

    return {
        "cart_items": cart_items,
        "cart_total_qty": cart_total_qty,
        "favorites_items": favorites_items,
        "favorites_count": len(favorites_items),
    }
