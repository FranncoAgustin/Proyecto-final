from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone

from pdf.models import ProductoPrecio, ProductoVariante  # ajustá import si están en otra app
from cupones.models import Cupon
from ofertas.utils import get_precio_con_oferta

Q2 = Decimal("0.01")


def _parse_key(item_key: str):
    try:
        prod_id, var_id = item_key.split(":")
        return int(prod_id), int(var_id)
    except Exception:
        return None, None


def build_cart_summary(request):
    cart = request.session.get("carrito", {})  # {"prodId:varId": qty}
    items = []
    total_pre_cupon = Decimal("0.00")

    # 1) Ofertas por producto (precio base puede ser igual para todas las variantes)
    for item_key, qty in cart.items():
        prod_id, var_id = _parse_key(item_key)
        if prod_id is None:
            continue

        producto = ProductoPrecio.objects.filter(pk=prod_id, activo=True).first()
        if not producto:
            continue

        variante = None
        if var_id and var_id != 0:
            variante = ProductoVariante.objects.filter(
                pk=var_id, producto=producto, activo=True
            ).first()
            if not variante:
                var_id = 0
                variante = None

        qty = int(qty)

        precio_data = get_precio_con_oferta(producto)
        precio_unitario_oferta = precio_data["precio_final"]  # Decimal

        subtotal = (precio_unitario_oferta * qty).quantize(Q2, rounding=ROUND_HALF_UP)
        total_pre_cupon += subtotal

        items.append({
            "key": item_key,  # por si querés usarlo
            "producto": producto,
            "variante": variante,  # ✅ para MP title "Producto - Variante"
            "cantidad": qty,
            "precio_unitario_oferta": precio_unitario_oferta.quantize(Q2),
            "subtotal_oferta": subtotal,
        })

    # 2) Cupón (global o por técnica)
    cupon = None
    descuento_cupon = Decimal("0.00")
    cupon_id = request.session.get("cupon_id")

    if cupon_id and items:
        try:
            cupon = Cupon.objects.get(
                id=cupon_id,
                activo=True,
                fecha_inicio__lte=timezone.now(),
                fecha_fin__gte=timezone.now(),
            )

            if cupon.tecnica == "TODAS":
                base_descuento = total_pre_cupon
                elegibles = items
            else:
                elegibles = [it for it in items if it["producto"].tech == cupon.tecnica]
                base_descuento = sum(it["subtotal_oferta"] for it in elegibles)

            if base_descuento > 0:
                descuento_cupon = (base_descuento * Decimal(cupon.descuento) / Decimal("100")).quantize(Q2)

                # 3) Prorrateo del descuento en items elegibles
                restante = descuento_cupon
                total_elegibles = base_descuento

                for i, it in enumerate(elegibles):
                    if i == len(elegibles) - 1:
                        desc_it = restante
                    else:
                        propor = (it["subtotal_oferta"] / total_elegibles)
                        desc_it = (descuento_cupon * propor).quantize(Q2, rounding=ROUND_HALF_UP)
                        restante -= desc_it

                    it["descuento_cupon_item"] = desc_it
            else:
                for it in items:
                    it["descuento_cupon_item"] = Decimal("0.00")

        except Cupon.DoesNotExist:
            request.session.pop("cupon_id", None)

    # si no hay cupón, inicializamos descuento 0
    for it in items:
        it.setdefault("descuento_cupon_item", Decimal("0.00"))

    # 4) Precio final por item (para MP)
    total_final = Decimal("0.00")
    for it in items:
        subtotal_final = (it["subtotal_oferta"] - it["descuento_cupon_item"]).quantize(Q2, rounding=ROUND_HALF_UP)

        # unit_price final por unidad (para MP)
        unit_final = (subtotal_final / Decimal(it["cantidad"])).quantize(Q2, rounding=ROUND_HALF_UP)

        it["subtotal_final"] = subtotal_final
        it["precio_unitario_final"] = unit_final

        total_final += subtotal_final

    return items, total_final, cupon, descuento_cupon
