import json
import hmac
import hashlib
import requests

from django.contrib import messages
from django.db import transaction
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.db.models import F

from .models import Pedido, PedidoItem, PagoMP
from .utils import build_cart_summary

from pdf.models import ProductoPrecio, ProductoVariante  # 👈 corregido: vienen de pdf.models

MP_API = "https://api.mercadopago.com"


def _mp_headers():
    return {
        "Authorization": f"Bearer {getattr(settings, 'MP_ACCESS_TOKEN', '')}",
        "Content-Type": "application/json",
    }


def _abs_from_site(path: str) -> str:
    base = getattr(settings, "SITE_URL", "http://127.0.0.1:8000").rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def _get_pedido_id_from_mp_return(request):
    pedido_id = (request.GET.get("external_reference") or "").strip()
    return pedido_id or None


def _map_estado_from_mp_return(request, fallback=None):
    cs = (request.GET.get("collection_status") or request.GET.get("status") or "").strip().lower()

    if cs in ("approved",):
        return Pedido.Estado.APROBADO
    if cs in ("pending", "in_process"):
        return Pedido.Estado.PENDIENTE
    if cs in ("rejected", "cancelled", "refunded", "charged_back"):
        return Pedido.Estado.RECHAZADO

    return fallback


def _redirect_post_mp(pedido_id: str | None):
    """
    Después de que MP nos devuelve (success/pending/failure),
    mandamos al usuario a la vista de detalle del pedido, si tenemos id.
    Si no, caemos a la lista de 'mis_compras'.
    """
    if pedido_id:
        try:
            pid = int(pedido_id)
        except ValueError:
            return redirect("mis_compras")
        return redirect("mis_compras_detalle", pedido_id=pid)

    return redirect("mis_compras")


@require_POST
def mp_crear_preferencia(request):
    items, total, cupon, descuento_cupon = build_cart_summary(request)

    if not items or total <= 0:
        messages.warning(request, "Tu carrito está vacío.")
        return redirect("ver_carrito")

    if not getattr(settings, "MP_ACCESS_TOKEN", ""):
        messages.error(request, "Falta MP_ACCESS_TOKEN en el entorno.")
        return redirect("ver_carrito")

    # ==========================
    # URLs absolutas en Render
    # ==========================
    success_url = _abs_from_site(reverse("mp_success"))
    pending_url = _abs_from_site(reverse("mp_pending"))
    failure_url = _abs_from_site(reverse("mp_failure"))
    notification_url = _abs_from_site(reverse("mp_webhook"))

    # DEBUG: ver qué se manda a MP (miralo en logs de Render)
    print("MP back_urls:", {
        "success": success_url,
        "pending": pending_url,
        "failure": failure_url,
        "notification": notification_url,
    })

    # ==========================
    # Crear pedido interno
    # ==========================
    pedido = Pedido.objects.create(
        total=total,
        moneda="ARS",
        cupon_codigo=(cupon.codigo if cupon else ""),
        descuento_total=descuento_cupon,
        estado=Pedido.Estado.CREADO,
        usuario=(request.user if request.user.is_authenticated else None),
    )

    # Guardar items del pedido incluyendo variante_id
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
            titulo=titulo,
            variante_id=(v.id if v else None),
            cantidad=int(it["cantidad"]),
            precio_unitario=it["precio_unitario_final"],
            subtotal=it["subtotal_final"],
        )

    # ==========================
    # Payload para Mercado Pago
    # ==========================
    preference_payload = {
        "items": [
            {
                "id": str(it["producto"].id),
                "title": (
                    f'{it["producto"].nombre_publico} - {it["variante"].nombre}'
                    if it.get("variante") else it["producto"].nombre_publico
                ),
                "quantity": int(it["cantidad"]),
                "currency_id": "ARS",
                "unit_price": float(it["precio_unitario_final"]),
            }
            for it in items
        ],
        "external_reference": str(pedido.id),
        "back_urls": {
            "success": success_url,
            "pending": pending_url,
            "failure": failure_url,
        },
        "notification_url": notification_url,
        # 👇 En Render usamos siempre auto_return
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
        try:
            err = r.json()
        except Exception:
            err = {"raw": r.text}

        print("MP ERROR:", err)
        messages.error(request, f"Mercado Pago respondió {r.status_code}: {err}")
        return redirect("ver_carrito")

    data = r.json()
    init_point = data.get("init_point") or data.get("sandbox_init_point")
    pref_id = data.get("id", "")

    if not init_point:
        pedido.estado = Pedido.Estado.CANCELADO
        pedido.save(update_fields=["estado"])
        messages.error(request, "Mercado Pago no devolvió init_point.")
        return redirect("ver_carrito")

    PagoMP.objects.create(
        pedido=pedido,
        preference_id=pref_id,
        init_point=init_point,
        actualizado_en=timezone.now(),
        raw=data,
    )

    return redirect(init_point)


# ===========================
# MP returns -> redirigir a Mis compras / Detalle
# ===========================

@require_GET
def mp_success(request):
    pedido_id = _get_pedido_id_from_mp_return(request)
    estado = _map_estado_from_mp_return(request, fallback=Pedido.Estado.PENDIENTE)

    if pedido_id:
        Pedido.objects.filter(id=pedido_id).update(estado=estado)

    return redirect(f"{reverse('mis_compras')}?pedido={pedido_id or ''}")


@require_GET
def mp_pending(request):
    pedido_id = _get_pedido_id_from_mp_return(request)

    if pedido_id:
        Pedido.objects.filter(id=pedido_id).update(estado=Pedido.Estado.PENDIENTE)

    return _redirect_post_mp(pedido_id)


@require_GET
def mp_failure(request):
    pedido_id = _get_pedido_id_from_mp_return(request)
    estado = _map_estado_from_mp_return(request, fallback=Pedido.Estado.RECHAZADO)

    if pedido_id:
        Pedido.objects.filter(id=pedido_id).update(estado=estado)

    return _redirect_post_mp(pedido_id)


def _is_valid_signature(request, data_id: str | None) -> bool:
    secret = (getattr(settings, "MP_WEBHOOK_SECRET", "") or "").strip()
    if not secret:
        return True

    if not data_id:
        return False

    x_signature = request.headers.get("x-signature") or request.headers.get("X-Signature") or ""
    x_request_id = request.headers.get("x-request-id") or request.headers.get("X-Request-Id") or ""

    # si no vienen headers, no bloqueamos
    if not x_signature or not x_request_id:
        return True

    parts = {}
    for kv in x_signature.split(","):
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        parts[k.strip()] = v.strip()

    ts = parts.get("ts", "")
    v1 = parts.get("v1", "")
    if not ts or not v1:
        return False

    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
    digest = hmac.new(
        secret.encode("utf-8"),
        msg=manifest.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(digest, v1)


@csrf_exempt
@require_POST
def mp_webhook(request):
    data_id = request.GET.get("data.id") or request.GET.get("id")
    topic = request.GET.get("type") or request.GET.get("topic")

    if not data_id:
        try:
            payload = json.loads(request.body.decode("utf-8"))
            data_id = payload.get("data", {}).get("id") or payload.get("id")
            topic = payload.get("type") or payload.get("topic") or topic
        except Exception:
            return HttpResponse(status=200)

    if not data_id:
        return HttpResponse(status=200)

    if not _is_valid_signature(request, str(data_id)):
        return HttpResponse(status=401)

    # Resolver payment_id real
    if topic == "merchant_order":
        mo = requests.get(
            f"{MP_API}/merchant_orders/{data_id}",
            headers=_mp_headers(),
            timeout=20,
        )
        if mo.status_code != 200:
            return HttpResponse(status=200)

        mo_data = mo.json()
        payments = mo_data.get("payments") or []
        payment_id = next((str(p.get("id")) for p in payments if p.get("id")), None)
        if not payment_id:
            return HttpResponse(status=200)
    else:
        payment_id = str(data_id)

    # Consultar pago real
    pr = requests.get(
        f"{MP_API}/v1/payments/{payment_id}",
        headers=_mp_headers(),
        timeout=20,
    )
    if pr.status_code != 200:
        return HttpResponse(status=200)

    pay = pr.json()
    status = (pay.get("status") or "").lower()

    pedido_id = str(pay.get("external_reference") or "").strip()
    if not pedido_id:
        return HttpResponse(status=200)

    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().filter(id=pedido_id).first()
        if not pedido:
            return HttpResponse(status=200)

        # Guardar info de pago
        pago_mp = getattr(pedido, "pago_mp", None)
        if pago_mp:
            pago_mp.payment_id = payment_id
            pago_mp.status = status or ""
            pago_mp.status_detail = (pay.get("status_detail") or "")[:255]
            pago_mp.raw = pay
            pago_mp.actualizado_en = timezone.now()
            pago_mp.save(update_fields=["payment_id", "status", "status_detail", "raw", "actualizado_en"])

        # Estado del pedido
        if status == "approved":
            pedido.estado = Pedido.Estado.APROBADO
        elif status in ("pending", "in_process"):
            pedido.estado = Pedido.Estado.PENDIENTE
            pedido.save(update_fields=["estado"])
            return HttpResponse(status=200)
        else:
            pedido.estado = Pedido.Estado.RECHAZADO
            pedido.save(update_fields=["estado"])
            return HttpResponse(status=200)

        # Descontar stock 1 sola vez
        if pedido.stock_descontado:
            pedido.save(update_fields=["estado"])
            return HttpResponse(status=200)

        items = PedidoItem.objects.select_for_update().filter(pedido=pedido)

        for it in items:
            qty = int(it.cantidad)

            if it.variante_id:
                ProductoVariante.objects.filter(
                    id=it.variante_id,
                    stock__gte=qty,
                    activo=True,
                ).update(stock=F("stock") - qty)
            else:
                ProductoPrecio.objects.filter(
                    id=it.producto_id,
                    stock__gte=qty,
                    activo=True,
                ).update(stock=F("stock") - qty)

        pedido.stock_descontado = True
        pedido.save(update_fields=["estado", "stock_descontado"])

    return HttpResponse(status=200)
