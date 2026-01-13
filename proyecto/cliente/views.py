# cliente/views.py
from decimal import Decimal
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone
from django.urls import reverse

from cliente.forms import ProfileForm
from .models import StockHold
from pdf.models import ProductoPrecio, ProductoVariante
from cupones.models import Cupon
from ofertas.utils import get_precio_con_oferta
from pdf.views import get_stock_disponible, registrar_evento  # helper stock + bitácora
from integraciones.models import Pedido, PedidoItem


# =========================
# Helpers FAVORITOS
# =========================

def _get_favoritos(request):
    return request.session.get("favoritos", {})


def _save_favoritos(request, favs):
    request.session["favoritos"] = favs
    request.session.modified = True


# =========================
# Helpers CARRITO / STOCK HOLD
# =========================

Q2 = Decimal("0.01")
HOLD_MINUTES = 30


def _get_cart(request):
    return request.session.get("carrito", {})


def _save_cart(request, cart):
    request.session["carrito"] = cart
    request.session.modified = True


def _make_key(prod_id: int, var_id: int | None):
    var_id = int(var_id or 0)
    return f"{int(prod_id)}:{var_id}"


def _parse_key(item_key: str):
    try:
        a, b = str(item_key).split(":")
        return int(a), int(b)
    except Exception:
        return None, 0


def _ensure_session(request) -> str:
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def cleanup_expired_holds():
    StockHold.objects.filter(expires_at__lte=timezone.now()).delete()


def _get_variante_or_none(producto: ProductoPrecio, var_id: int):
    if not var_id:
        return None
    return ProductoVariante.objects.filter(pk=var_id, producto=producto, activo=True).first()


def get_stock_disponible_efectivo(producto: ProductoPrecio, var_id: int) -> int:
    """
    stock real - reservas vigentes (de TODOS los carritos)
    """
    stock_real = int(get_stock_disponible(producto, var_id))

    reservas = (
        StockHold.objects.filter(
            producto=producto,
            variante_id=(var_id if var_id != 0 else None),
            expires_at__gt=timezone.now(),
        )
        .aggregate(total=Sum("cantidad"))["total"]
        or 0
    )

    return max(0, stock_real - int(reservas))


# =========================
# VISTAS: CARRITO
# =========================

def ver_carrito(request):
    cleanup_expired_holds()

    cart = _get_cart(request)
    items = []
    total = Decimal("0.00")

    for item_key, qty in cart.items():
        prod_id, var_id = _parse_key(item_key)
        if prod_id is None:
            continue

        producto = ProductoPrecio.objects.filter(pk=prod_id, activo=True).first()
        if not producto:
            continue

        variante = _get_variante_or_none(producto, var_id)
        if var_id != 0 and not variante:
            # variante inválida -> lo tratamos como principal
            var_id = 0

        qty = max(0, int(qty))

        # precio
        precio_data = get_precio_con_oferta(producto)
        precio_unitario = precio_data["precio_final"]
        oferta = precio_data["oferta"]

        subtotal = (precio_unitario * qty).quantize(Q2)
        total += subtotal

        # imagen para el carrito: prioridad variante, sino producto
        imagen_url = None
        if variante and getattr(variante, "imagen", None):
            imagen_url = variante.imagen.url
        elif getattr(producto, "imagen", None):
            imagen_url = producto.imagen.url

        # stock efectivo “ahora”
        stock_efectivo = get_stock_disponible_efectivo(producto, var_id)

        items.append({
            "key": item_key,
            "producto": producto,
            "variante": variante,
            "cantidad": qty,
            "precio_original": producto.precio,
            "precio_final": precio_unitario,
            "oferta": oferta,
            "subtotal": subtotal,
            "imagen_url": imagen_url,
            "stock_efectivo": stock_efectivo,
        })

    # =====================
    # CUPÓN
    # =====================
    cupon = None
    descuento_cupon = Decimal("0.00")
    cupon_id = request.session.get("cupon_id")

    if cupon_id:
        try:
            cupon = Cupon.objects.get(
                id=cupon_id,
                activo=True,
                fecha_inicio__lte=timezone.now(),
                fecha_fin__gte=timezone.now(),
            )

            if cupon.tecnica == "TODAS":
                descuento_cupon = (total * Decimal(cupon.descuento) / Decimal("100")).quantize(Q2)
            else:
                subtotal_filtrado = sum(
                    it["subtotal"]
                    for it in items
                    if it["producto"].tech == cupon.tecnica
                )
                descuento_cupon = (subtotal_filtrado * Decimal(cupon.descuento) / Decimal("100")).quantize(Q2)

            total = (total - descuento_cupon).quantize(Q2)

        except Cupon.DoesNotExist:
            request.session.pop("cupon_id", None)
            request.session["error_cupon"] = "Cupón inválido o vencido"

    return render(
        request,
        "cliente/carrito.html",
        {
            "items": items,
            "total": total,
            "cupon": cupon,
            "descuento_cupon": descuento_cupon,
            "error_cupon": request.session.pop("error_cupon", None),
            "hold_minutes": HOLD_MINUTES,
        }
    )


@require_POST
def aplicar_cupon(request):
    codigo = request.POST.get("codigo", "").strip()

    try:
        cupon = Cupon.objects.get(
            codigo__iexact=codigo,
            activo=True,
            fecha_inicio__lte=timezone.now(),
            fecha_fin__gte=timezone.now(),
        )
        request.session["cupon_id"] = cupon.id
        request.session.pop("error_cupon", None)

        # Bitácora: cupón aplicado
        registrar_evento(
            tipo="cupon_aplicado",
            titulo=f"Cupón aplicado: {cupon.codigo}",
            detalle=f"Descuento: {cupon.descuento}% - Técnica: {cupon.tecnica}",
            user=getattr(request, "user", None),
            extra={
                "cupon_id": cupon.id,
                "codigo": cupon.codigo,
                "descuento": str(cupon.descuento),
                "tecnica": cupon.tecnica,
            },
        )

    except Cupon.DoesNotExist:
        request.session.pop("cupon_id", None)
        request.session["error_cupon"] = "Cupón inválido o vencido"

        registrar_evento(
            tipo="cupon_invalido",
            titulo="Intento de aplicar cupón inválido",
            detalle=f"Código ingresado: {codigo}",
            user=getattr(request, "user", None),
            extra={"codigo": codigo},
        )

    return redirect("ver_carrito")


@require_POST
def agregar_al_carrito(request, pk):
    """
    Ahora obliga a estar logueado.
    Si no está autenticado, redirige al login con ?next=<página anterior>.
    """
    if not request.user.is_authenticated:
        messages.info(
            request,
            "Para agregar productos al carrito necesitás iniciar sesión o registrarte."
        )
        login_url = getattr(settings, "LOGIN_URL", "/accounts/login/")
        next_url = (
            request.GET.get("next")
            or request.META.get("HTTP_REFERER")
            or reverse("detalle_producto", args=[pk])
        )
        return redirect(f"{login_url}?next={quote(next_url)}")

    cleanup_expired_holds()

    producto = get_object_or_404(ProductoPrecio, pk=pk, activo=True)

    var_id = request.POST.get("variante_id") or request.GET.get("variante_id") or "0"
    try:
        var_id = int(var_id)
    except Exception:
        var_id = 0

    variante = _get_variante_or_none(producto, var_id)
    if var_id != 0 and not variante:
        var_id = 0
        variante = None

    try:
        cantidad = int(request.POST.get("cantidad", 1))
    except ValueError:
        cantidad = 1
    cantidad = max(1, cantidad)

    session_key = _ensure_session(request)

    # disponible para este carrito = stock_efectivo + lo que YA tiene reservado este mismo carrito
    mi_hold_qty = (
        StockHold.objects.filter(
            session_key=session_key,
            producto=producto,
            variante=variante,
            expires_at__gt=timezone.now(),
        ).aggregate(total=Sum("cantidad"))["total"] or 0
    )

    disp_efectivo = get_stock_disponible_efectivo(producto, var_id)
    disp_para_mi = int(disp_efectivo) + int(mi_hold_qty)

    if disp_para_mi <= 0:
        messages.error(request, "Sin stock disponible para esa opción.")
        registrar_evento(
            tipo="carrito_agregar_sin_stock",
            titulo="Intento de agregar al carrito sin stock",
            detalle=f"{producto.nombre_publico} (variante {var_id})",
            user=getattr(request, "user", None),
            obj=producto,
            extra={
                "producto_id": producto.id,
                "variante_id": var_id,
                "cantidad_solicitada": cantidad,
                "stock_efectivo": int(disp_efectivo),
                "mi_hold_qty": int(mi_hold_qty),
            },
        )
        return redirect(request.GET.get("next") or "detalle_producto", pk=pk)

    if cantidad > disp_para_mi:
        cantidad = disp_para_mi
        messages.warning(request, f"Solo hay {disp_para_mi} unidades disponibles. Se ajustó la cantidad.")

    # 1) carrito sesión (cap)
    cart = _get_cart(request)
    item_key = _make_key(producto.id, var_id)
    actual = int(cart.get(item_key, 0))
    nuevo = min(disp_para_mi, actual + cantidad)
    cart[item_key] = nuevo
    _save_cart(request, cart)

    # 2) hold (reservar) -> guardamos EXACTO lo mismo que el carrito para ese item
    expires = timezone.now() + timedelta(minutes=HOLD_MINUTES)

    hold, _created = StockHold.objects.get_or_create(
        session_key=session_key,
        producto=producto,
        variante=variante,
        defaults={
            "cantidad": 0,
            "expires_at": expires,
            "user": request.user if request.user.is_authenticated else None,
        },
    )
    hold.cantidad = nuevo
    hold.expires_at = expires
    if request.user.is_authenticated and hold.user_id is None:
        hold.user = request.user
    hold.save()

    # Bitácora: producto agregado al carrito
    registrar_evento(
        tipo="carrito_agregar",
        titulo="Producto agregado al carrito",
        detalle=f"{producto.nombre_publico} x{cantidad} (total item: {nuevo})",
        user=getattr(request, "user", None),
        obj=producto,
        extra={
            "producto_id": producto.id,
            "variante_id": var_id,
            "cantidad_agregada": cantidad,
            "cantidad_total_item": nuevo,
            "stock_efectivo": int(disp_efectivo),
            "mi_hold_qty": int(mi_hold_qty),
            "session_key": session_key,
        },
    )

    messages.success(request, f'"{producto.nombre_publico}" se agregó al carrito. (Reservado {HOLD_MINUTES} min)')
    next_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or "ver_carrito"
    return redirect(next_url)


def eliminar_del_carrito(request, item_key):
    cleanup_expired_holds()

    cart = _get_cart(request)
    qty_anterior = cart.get(str(item_key), 0)
    cart.pop(str(item_key), None)
    _save_cart(request, cart)

    # borrar hold correspondiente
    prod_id, var_id = _parse_key(item_key)
    producto = None
    if prod_id is not None:
        producto = ProductoPrecio.objects.filter(pk=prod_id).first()
        if producto:
            variante = _get_variante_or_none(producto, var_id)
            session_key = _ensure_session(request)
            StockHold.objects.filter(
                session_key=session_key,
                producto=producto,
                variante=variante,
            ).delete()

            # Bitácora: ítem eliminado del carrito
            registrar_evento(
                tipo="carrito_eliminar",
                titulo="Producto eliminado del carrito",
                detalle=f"{producto.nombre_publico} (key={item_key})",
                user=getattr(request, "user", None),
                obj=producto,
                extra={
                    "producto_id": producto.id,
                    "variante_id": var_id,
                    "cantidad_eliminada": int(qty_anterior),
                    "session_key": session_key,
                },
            )

    return redirect("ver_carrito")


@require_POST
def actualizar_cantidad(request, item_key):
    cleanup_expired_holds()

    try:
        qty = int(request.POST.get("cantidad", 1))
    except ValueError:
        qty = 1

    prod_id, var_id = _parse_key(item_key)
    if prod_id is None:
        return redirect("ver_carrito")

    producto = ProductoPrecio.objects.filter(pk=prod_id, activo=True).first()
    if not producto:
        return redirect("ver_carrito")

    variante = _get_variante_or_none(producto, var_id)
    if var_id != 0 and not variante:
        var_id = 0
        variante = None

    cart = _get_cart(request)
    session_key = _ensure_session(request)
    qty_anterior = int(cart.get(str(item_key), 0))

    if qty <= 0:
        cart.pop(str(item_key), None)
        _save_cart(request, cart)
        StockHold.objects.filter(
            session_key=session_key,
            producto=producto,
            variante=variante,
        ).delete()

        registrar_evento(
            tipo="carrito_eliminar",
            titulo="Producto eliminado del carrito (cantidad 0)",
            detalle=f"{producto.nombre_publico} (key={item_key})",
            user=getattr(request, "user", None),
            obj=producto,
            extra={
                "producto_id": producto.id,
                "variante_id": var_id,
                "cantidad_anterior": qty_anterior,
                "session_key": session_key,
            },
        )
        return redirect("ver_carrito")

    # limite = stock efectivo + lo reservado por mí
    mi_hold_qty = (
        StockHold.objects.filter(
            session_key=session_key,
            producto=producto,
            variante=variante,
            expires_at__gt=timezone.now(),
        ).aggregate(total=Sum("cantidad"))["total"] or 0
    )

    disp_efectivo = get_stock_disponible_efectivo(producto, var_id)
    max_para_mi = int(disp_efectivo) + int(mi_hold_qty)

    if max_para_mi <= 0:
        cart.pop(str(item_key), None)
        _save_cart(request, cart)
        StockHold.objects.filter(session_key=session_key, producto=producto, variante=variante).delete()
        messages.error(request, "Ese producto quedó sin stock.")

        registrar_evento(
            tipo="carrito_sin_stock",
            titulo="Producto quitado del carrito por falta de stock",
            detalle=f"{producto.nombre_publico} (key={item_key})",
            user=getattr(request, "user", None),
            obj=producto,
            extra={
                "producto_id": producto.id,
                "variante_id": var_id,
                "cantidad_anterior": qty_anterior,
                "session_key": session_key,
            },
        )
        return redirect("ver_carrito")

    if qty > max_para_mi:
        qty = max_para_mi
        messages.warning(request, f"Se ajustó la cantidad al máximo disponible: {max_para_mi}")

    cart[str(item_key)] = qty
    _save_cart(request, cart)

    expires = timezone.now() + timedelta(minutes=HOLD_MINUTES)
    hold, _created = StockHold.objects.get_or_create(
        session_key=session_key,
        producto=producto,
        variante=variante,
        defaults={
            "cantidad": qty,
            "expires_at": expires,
            "user": request.user if request.user.is_authenticated else None,
        },
    )
    hold.cantidad = qty
    hold.expires_at = expires
    if request.user.is_authenticated and hold.user_id is None:
        hold.user = request.user
    hold.save()

    registrar_evento(
        tipo="carrito_actualizar",
        titulo="Cantidad de producto actualizada en carrito",
        detalle=f"{producto.nombre_publico}: {qty_anterior} → {qty}",
        user=getattr(request, "user", None),
        obj=producto,
        extra={
            "producto_id": producto.id,
            "variante_id": var_id,
            "cantidad_anterior": qty_anterior,
            "cantidad_nueva": qty,
            "max_para_mi": max_para_mi,
            "session_key": session_key,
        },
    )

    return redirect("ver_carrito")


def vaciar_carrito(request):
    cleanup_expired_holds()

    cart = _get_cart(request)
    tamaño_anterior = len(cart)
    _save_cart(request, {})

    # borrar todos los holds de esta sesión
    session_key = _ensure_session(request)
    StockHold.objects.filter(session_key=session_key).delete()

    registrar_evento(
        tipo="carrito_vaciar",
        titulo="Carrito vaciado",
        detalle=f"Items previos: {tamaño_anterior}",
        user=getattr(request, "user", None),
        extra={
            "items_previos": tamaño_anterior,
            "session_key": session_key,
        },
    )

    return redirect("ver_carrito")


# =========================
# VISTAS: FAVORITOS
# =========================

@login_required
def mis_favoritos(request):
    favs = _get_favoritos(request)
    items = []

    for prod_id in favs.keys():
        producto = ProductoPrecio.objects.filter(pk=prod_id).first()
        if not producto:
            continue

        imagen_url = None
        if hasattr(producto, "imagen") and producto.imagen:
            imagen_url = producto.imagen.url

        items.append(
            {
                "producto": producto,
                "imagen_url": imagen_url,
            }
        )

    return render(request, "cliente/favoritos.html", {"items": items})


@login_required
def agregar_favorito(request, pk):
    producto = get_object_or_404(ProductoPrecio, pk=pk)

    favs = _get_favoritos(request)
    favs[str(producto.id)] = True
    _save_favoritos(request, favs)

    registrar_evento(
        tipo="favorito_agregar",
        titulo="Producto agregado a favoritos",
        detalle=producto.nombre_publico,
        user=getattr(request, "user", None),
        obj=producto,
        extra={"producto_id": producto.id},
    )

    messages.success(request, f'"{producto.nombre_publico}" se agregó a favoritos.')

    next_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or "mis_favoritos"
    return redirect(next_url)


@login_required
def eliminar_favorito(request, pk):
    favs = _get_favoritos(request)
    estaba = pk in favs or str(pk) in favs
    favs.pop(str(pk), None)
    _save_favoritos(request, favs)

    if estaba:
        registrar_evento(
            tipo="favorito_eliminar",
            titulo="Producto eliminado de favoritos",
            detalle=f"Producto ID {pk}",
            user=getattr(request, "user", None),
            extra={"producto_id": pk},
        )

    next_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or "mis_favoritos"
    return redirect(next_url)


# =========================
# VISTAS: MI CUENTA / MIS COMPRAS / LOGOUT
# =========================

@login_required
def mi_cuenta(request):
    user = request.user
    profile = user.profile

    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()

            registrar_evento(
                tipo="perfil_actualizado",
                titulo="Perfil de usuario actualizado",
                detalle=f"Usuario: {user.username} / {user.email}",
                user=user,
                obj=profile,
                extra={"user_id": user.id},
            )

            messages.success(request, "¡Tus datos se guardaron correctamente! 🎉")
            return redirect("catalogo")
    else:
        form = ProfileForm(instance=profile)

    contexto = {
        "usuario": user,
        "form": form,
    }
    return render(request, "cliente/mi_cuenta.html", contexto)


CANCELAR_DESPUES_MIN = 30


def _ensure_session_key(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def _expire_pedidos_queryset(qs):
    """
    Marca como SIN_FINALIZAR pedidos CREADO/PENDIENTE viejos (sin cron).
    """
    minutes = int(getattr(settings, "MP_EXPIRE_MINUTES", 60))  # configurable
    cutoff = timezone.now() - timedelta(minutes=minutes)

    qs.filter(
        estado__in=[Pedido.Estado.CREADO, Pedido.Estado.PENDIENTE],
        creado_en__lt=cutoff,
    ).update(estado=Pedido.Estado.SIN_FINALIZAR)


@login_required
@require_GET
def mis_compras(request):
    qs = (
        Pedido.objects
        .filter(usuario=request.user)
        .order_by("-creado_en")
        .prefetch_related("items")
        .select_related("pago_mp")
    )

    # Expirar "creados" viejos
    _expire_pedidos_queryset(qs)

    return render(request, "cliente/mis_compras.html", {"pedidos": qs})


@login_required
@require_GET
def mis_compras_detalle(request, pedido_id: int):
    pedido = get_object_or_404(Pedido, id=pedido_id, usuario=request.user)
    items = PedidoItem.objects.filter(pedido=pedido).order_by("id")

    registrar_evento(
        tipo="pedido_ver_detalle",
        titulo=f"Vista detalle pedido #{pedido.id}",
        detalle=f"Estado: {pedido.estado}",
        user=request.user,
        obj=pedido,
        extra={"pedido_id": pedido.id, "estado": pedido.estado},
    )

    return render(request, "cliente/mis_compras_detalle.html", {"pedido": pedido, "items": items})


@login_required
@require_POST
def pedido_continuar_pago(request, pedido_id: int):
    pedido = get_object_or_404(Pedido, id=pedido_id, usuario=request.user)

    # Solo tiene sentido continuar si no está cerrado
    if pedido.estado in [Pedido.Estado.APROBADO, Pedido.Estado.CANCELADO, Pedido.Estado.RECHAZADO, Pedido.Estado.SIN_FINALIZAR]:
        messages.warning(request, "Este pedido no se puede continuar.")

        registrar_evento(
            tipo="pedido_continuar_no_permitido",
            titulo=f"No se puede continuar pago de pedido #{pedido.id}",
            detalle=f"Estado: {pedido.estado}",
            user=request.user,
            obj=pedido,
            extra={"pedido_id": pedido.id, "estado": pedido.estado},
        )

        return redirect("mis_compras")

    pago = getattr(pedido, "pago_mp", None)
    if not pago or not pago.init_point:
        messages.error(request, "No encontramos el link de pago para este pedido.")

        registrar_evento(
            tipo="pedido_continuar_sin_link",
            titulo=f"Pedido sin link de pago #{pedido.id}",
            detalle="Mercado Pago init_point no disponible.",
            user=request.user,
            obj=pedido,
            extra={"pedido_id": pedido.id},
        )

        return redirect("mis_compras")

    registrar_evento(
        tipo="pedido_continuar_pago",
        titulo=f"Continuar pago pedido #{pedido.id}",
        detalle="Redirección a Mercado Pago.",
        user=request.user,
        obj=pedido,
        extra={"pedido_id": pedido.id, "init_point": pago.init_point},
    )

    return redirect(pago.init_point)


@login_required
@require_POST
def pedido_cancelar(request, pedido_id: int):
    pedido = get_object_or_404(Pedido, id=pedido_id, usuario=request.user)

    # Cancelable solo si todavía no se aprobó
    if pedido.estado == Pedido.Estado.APROBADO:
        messages.warning(request, "Un pedido aprobado no se puede cancelar desde acá.")

        registrar_evento(
            tipo="pedido_cancelar_no_permitido",
            titulo=f"Intento de cancelar pedido aprobado #{pedido.id}",
            detalle="El pedido ya está aprobado.",
            user=request.user,
            obj=pedido,
            extra={"pedido_id": pedido.id, "estado": pedido.estado},
        )

        return redirect("mis_compras")

    pedido.estado = Pedido.Estado.CANCELADO
    pedido.save(update_fields=["estado"])

    registrar_evento(
        tipo="pedido_cancelar",
        titulo=f"Pedido #{pedido.id} cancelado por el cliente",
        detalle="Estado cambiado a CANCELADO.",
        user=request.user,
        obj=pedido,
        extra={"pedido_id": pedido.id},
    )

    messages.success(request, f"Pedido #{pedido.id} cancelado.")
    return redirect("mis_compras")


@login_required
@require_POST
def pedido_eliminar(request, pedido_id: int):
    pedido = get_object_or_404(Pedido, id=pedido_id, usuario=request.user)

    # Por seguridad: permitir borrar solo si está CREADO o SIN_FINALIZAR (evita perder historial real)
    if pedido.estado not in [Pedido.Estado.CREADO, Pedido.Estado.SIN_FINALIZAR]:
        messages.warning(request, "Solo podés eliminar pedidos no finalizados.")

        registrar_evento(
            tipo="pedido_eliminar_no_permitido",
            titulo=f"Intento de eliminar pedido #{pedido.id} con estado {pedido.estado}",
            detalle="Solo se permiten pedidos CREADO o SIN_FINALIZAR.",
            user=request.user,
            obj=pedido,
            extra={"pedido_id": pedido.id, "estado": pedido.estado},
        )

        return redirect("mis_compras")

    pedido_id_val = pedido.id
    estado_prev = pedido.estado
    pedido.delete()

    registrar_evento(
        tipo="pedido_eliminar",
        titulo=f"Pedido #{pedido_id_val} eliminado por el cliente",
        detalle=f"Estado previo: {estado_prev}",
        user=request.user,
        extra={"pedido_id": pedido_id_val, "estado_previo": estado_prev},
    )

    messages.success(request, f"Pedido #{pedido_id_val} eliminado.")
    return redirect("mis_compras")


@login_required
def logout_view(request):
    usuario = request.user if request.user.is_authenticated else None

    registrar_evento(
        tipo="logout",
        titulo="Usuario cerró sesión",
        detalle=f"Usuario: {usuario.username if usuario else 'anónimo'}",
        user=usuario,
        extra={"user_id": getattr(usuario, "id", None)},
    )

    logout(request)
    messages.info(request, "Cerraste sesión correctamente.")
    return redirect("catalogo")


# =========================
# REGISTRO Y LOGIN (redirección a allauth)
# =========================

def registro_view(request):
    # Si ya está logueado, lo mandamos a su cuenta
    if request.user.is_authenticated:
        return redirect("mi_cuenta")
    # signup de allauth
    return redirect("account_signup")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("mi_cuenta")
    # login de allauth
    return redirect("account_login")
