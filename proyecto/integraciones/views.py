import json
import hmac
import hashlib
import requests
from decimal import Decimal

from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from .models import Pedido, PedidoItem, PagoMP
from .utils import build_cart_summary


MP_API = "https://api.mercadopago.com"


def _abs(request, path):
    return request.build_absolute_uri(path)


def _mp_headers():
    return {
        "Authorization": f"Bearer {settings.MP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


@require_POST
def mp_crear_preferencia(request):
    """
    1) Lee carrito (server-side)
    2) Crea Pedido en DB
    3) Crea preferencia en MP
    4) Redirige a init_point
    """
    items, total, cupon, descuento_cupon = build_cart_summary(request)

    if not items or total <= 0:
        return redirect("ver_carrito")

    # Crear pedido
    pedido = Pedido.objects.create(
        total=total,
        moneda="ARS",
        cupon_codigo=(cupon.codigo if cupon else ""),
        descuento_total=descuento_cupon,
        estado=Pedido.Estado.CREADO,
    )

    # Guardar snapshot de items (con variante en el título y precio FINAL)
    for it in items:
        p = it["producto"]
        v = it.get("variante")

        titulo = p.nombre_publico
        if v:
            titulo = f"{titulo} - {v.nombre}"

        PedidoItem.objects.create(
            pedido=pedido,
            producto_id=p.id,
            sku=p.sku,
            titulo=titulo,  # ✅ con variante
            cantidad=it["cantidad"],
            precio_unitario=it["precio_unitario_final"],  # ✅ final final (oferta+cupón)
            subtotal=it["subtotal_final"],                 # ✅ final final
        )

    back_urls = {
        "success": _abs(request, reverse("mp_success")),
        "pending": _abs(request, reverse("mp_pending")),
        "failure": _abs(request, reverse("mp_failure")),
    }

    notification_url = _abs(request, reverse("mp_webhook"))

    preference_payload = {
        "items": [
            {
                "id": str(it["producto"].id),
                "title": (
                    f'{it["producto"].nombre_publico} - {it["variante"].nombre}'
                    if it.get("variante") else it["producto"].nombre_publico
                ),
                "quantity": it["cantidad"],
                "currency_id": "ARS",
                "unit_price": float(it["precio_unitario_final"]),  # ✅ precio final mostrado en carrito
            }
            for it in items
        ],
        "external_reference": str(pedido.id),
        "back_urls": back_urls,
        "notification_url": notification_url,
        "auto_return": "approved",
    }

    r = requests.post(
        f"{MP_API}/checkout/preferences",
        headers=_mp_headers(),
        data=json.dumps(preference_payload),
        timeout=20,
    )

    if r.status_code not in (200, 201):
        pedido.estado = Pedido.Estado.CANCELADO
        pedido.save(update_fields=["estado"])
        return redirect("ver_carrito")

    data = r.json()
    init_point = data.get("init_point") or data.get("sandbox_init_point", "")
    pref_id = data.get("id", "")

    PagoMP.objects.create(
        pedido=pedido,
        preference_id=pref_id,
        init_point=init_point,
        actualizado_en=timezone.now(),
        raw=data,
    )

    return redirect(init_point)

# ------- RETURNS (solo UX) -------
@require_GET
def mp_success(request):
    return render(request, "checkout/mp_success.html")


@require_GET
def mp_pending(request):
    return render(request, "checkout/mp_pending.html")


@require_GET
def mp_failure(request):
    return render(request, "checkout/mp_failure.html")


# ------- WEBHOOK (la verdad del pago) -------
def _is_valid_signature(request):
    """
    Si configurás secret en MP, te llega x-signature para validar.
    Ojo: MP documenta validación con x-signature (ts + v1). :contentReference[oaicite:1]{index=1}
    Si no tenés secret, devolvemos True y seguís sin firma.
    """
    secret = settings.MP_WEBHOOK_SECRET
    if not secret:
        return True

    x_signature = request.headers.get("x-signature", "")
    x_request_id = request.headers.get("x-request-id", "")

    if not x_signature or not x_request_id:
        return False

    # Formato típico: "ts=...,v1=..."
    parts = dict(kv.split("=", 1) for kv in x_signature.split(",") if "=" in kv)
    ts = parts.get("ts")
    v1 = parts.get("v1")
    if not ts or not v1:
        return False

    # Este string de validación depende del doc de MP (ts + request-id + data.id/topic).
    # Para no romperte el flujo, lo dejamos opcional: si falla, rechazamos.
    # Si querés lo dejamos 100% calcado a tu formato real cuando veamos un webhook real.
    body = request.body.decode("utf-8") if request.body else ""
    manifest = f"id:{x_request_id};ts:{ts};body:{body}"

    digest = hmac.new(
        secret.encode("utf-8"),
        msg=manifest.encode("utf-8"),
        digestmod=hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(digest, v1)


@csrf_exempt
@require_POST
def mp_webhook(request):
    # 1) validar firma (si la usás)
    if not _is_valid_signature(request):
        return HttpResponse(status=401)

    # 2) extraer payment_id (MP puede mandar formatos distintos)
    payment_id = request.GET.get("data.id") or request.GET.get("id")
    topic = request.GET.get("type") or request.GET.get("topic")

    if not payment_id:
        try:
            payload = json.loads(request.body.decode("utf-8"))
            payment_id = payload.get("data", {}).get("id") or payload.get("id")
            topic = payload.get("type") or payload.get("topic")
        except Exception:
            payment_id = None

    # Si no es pago, respondemos 200 igual (MP reintenta si no)
    if not payment_id:
        return HttpResponse(status=200)

    # 3) consultar pago a MP (estado real)
    pr = requests.get(
        f"{MP_API}/v1/payments/{payment_id}",
        headers=_mp_headers(),
        timeout=20,
    )

    if pr.status_code != 200:
        return HttpResponse(status=200)

    pay = pr.json()
    status = pay.get("status", "")
    status_detail = pay.get("status_detail", "")
    external_ref = pay.get("external_reference")  # nuestro pedido.id

    if not external_ref:
        return HttpResponse(status=200)

    pedido = Pedido.objects.filter(id=int(external_ref)).first()
    if not pedido:
        return HttpResponse(status=200)

    pago_mp, _ = PagoMP.objects.get_or_create(pedido=pedido)
    pago_mp.payment_id = str(payment_id)
    pago_mp.status = status
    pago_mp.status_detail = status_detail
    pago_mp.raw = pay
    pago_mp.actualizado_en = timezone.now()
    pago_mp.save()

    # 4) traducir estado a tu pedido (idempotente)
    if status == "approved":
        if pedido.estado != Pedido.Estado.APROBADO:
            pedido.estado = Pedido.Estado.APROBADO
            pedido.save(update_fields=["estado"])
            # acá luego descontamos stock / generamos factura, etc.
    elif status in ("pending", "in_process"):
        if pedido.estado != Pedido.Estado.PENDIENTE:
            pedido.estado = Pedido.Estado.PENDIENTE
            pedido.save(update_fields=["estado"])
    elif status in ("rejected",):
        pedido.estado = Pedido.Estado.RECHAZADO
        pedido.save(update_fields=["estado"])
    elif status in ("cancelled",):
        pedido.estado = Pedido.Estado.CANCELADO
        pedido.save(update_fields=["estado"])

    return HttpResponse(status=200)
