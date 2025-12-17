# cliente/views.py
from decimal import Decimal

from django import forms
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout, authenticate, login

from cliente.forms import RegistroForm, ProfileForm
from .models import Profile
from pdf.models import ProductoPrecio, ProductoVariante  # tu modelo de productos
from django.utils import timezone
from cupones.models import Cupon
from django.shortcuts import redirect
from ofertas.utils import get_precio_con_oferta

# =========================
# Helpers carrito / favoritos
# =========================

def _get_cart(request):
    return request.session.get("carrito", {})


def _save_cart(request, cart):
    request.session["carrito"] = cart
    request.session.modified = True


def _get_favoritos(request):
    return request.session.get("favoritos", {})


def _save_favoritos(request, favs):
    request.session["favoritos"] = favs
    request.session.modified = True


def _parse_key(item_key: str):
    try:
        if ":" in item_key:
            prod_id, var_id = item_key.split(":")
            return int(prod_id), int(var_id)
        return int(item_key), 0
    except Exception:
        return None, None

# =========================
# VISTAS: CARRITO
# =========================

def ver_carrito(request):
    cart = _get_cart(request)  # ahora cart = {"prodId:varId": qty}
    items = []
    total = Decimal("0.00")

    # =====================
    # Items del carrito
    # =====================
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
            # si la variante no existe, lo tratamos como sin variante
            if not variante:
                var_id = 0

        qty = int(qty)

        precio_data = get_precio_con_oferta(producto)
        precio_unitario = precio_data["precio_final"]
        oferta = precio_data["oferta"]

        subtotal = precio_unitario * qty
        total += subtotal

        items.append({
            "key": item_key,                 # ✅ para actualizar/eliminar
            "producto": producto,
            "variante": variante,            # ✅ para mostrar "Roja"
            "cantidad": qty,
            "precio_original": producto.precio,
            "precio_final": precio_unitario,
            "oferta": oferta,
            "subtotal": subtotal,
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
                descuento_cupon = total * Decimal(cupon.descuento) / Decimal("100")
            else:
                subtotal_filtrado = sum(
                    it["subtotal"]
                    for it in items
                    if it["producto"].tech == cupon.tecnica
                )
                descuento_cupon = subtotal_filtrado * Decimal(cupon.descuento) / Decimal("100")

            total -= descuento_cupon

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
        }
    )

def aplicar_cupon(request):
    if request.method == "POST":
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

        except Cupon.DoesNotExist:
            request.session.pop("cupon_id", None)
            request.session["error_cupon"] = "Cupón inválido o vencido"

    return redirect("ver_carrito")

def agregar_al_carrito(request, pk):
    producto = get_object_or_404(ProductoPrecio, pk=pk)

    # si no mandás variante, queda 0 (sin variante)
    var_id = request.POST.get("variante_id") or request.GET.get("variante_id") or "0"
    try:
        var_id = int(var_id)
    except Exception:
        var_id = 0

    cart = _get_cart(request)

    item_key = f"{producto.id}:{var_id}"  # ✅ clave consistente
    cart[item_key] = int(cart.get(item_key, 0)) + 1

    _save_cart(request, cart)

    messages.success(request, f'"{producto.nombre_publico}" se agregó al carrito.')
    next_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or "ver_carrito"
    return redirect(next_url)


def eliminar_del_carrito(request, item_key):
    cart = _get_cart(request)
    cart.pop(str(item_key), None)
    _save_cart(request, cart)
    return redirect("ver_carrito")


def actualizar_cantidad(request, item_key):
    if request.method == "POST":
        try:
            qty = int(request.POST.get("cantidad", 1))
        except ValueError:
            qty = 1

        cart = _get_cart(request)

        if qty <= 0:
            cart.pop(str(item_key), None)
        else:
            cart[str(item_key)] = qty

        _save_cart(request, cart)

    return redirect("ver_carrito")


def vaciar_carrito(request):
    _save_cart(request, {})
    return redirect("ver_carrito")


# =========================
# VISTAS: FAVORITOS
# =========================

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


def agregar_favorito(request, pk):
    producto = get_object_or_404(ProductoPrecio, pk=pk)

    favs = _get_favoritos(request)
    favs[str(producto.id)] = True
    _save_favoritos(request, favs)

    messages.success(request, f'"{producto.nombre_publico}" se agregó a favoritos.')

    next_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or "mis_favoritos"
    return redirect(next_url)


def eliminar_favorito(request, pk):
    favs = _get_favoritos(request)
    favs.pop(str(pk), None)
    _save_favoritos(request, favs)
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
            messages.success(request, "¡Tus datos se guardaron correctamente! 🎉")
            return redirect("ver_catalogo_completo")
    else:
        form = ProfileForm(instance=profile)

    contexto = {
        "usuario": user,
        "form": form,
    }
    return render(request, "cliente/mi_cuenta.html", contexto)


@login_required
def mis_compras(request):
    """
    Por ahora mostramos un placeholder.
    Cuando tengas el modelo de pedidos/órdenes, acá los listamos.
    """
    compras = []  # TODO: reemplazar por tus pedidos/órdenes reales
    return render(request, "cliente/mis_compras.html", {"compras": compras})


@login_required
def logout_view(request):
    logout(request)
    messages.info(request, "Cerraste sesión correctamente.")
    return redirect("ver_catalogo_completo")


# =========================
# REGISTRO Y LOGIN
# =========================

def registro_view(request):
    # Si ya está logueado, lo mandamos a su cuenta
    if request.user.is_authenticated:
        return redirect("mi_cuenta")
    # Si no, usamos el signup de allauth
    return redirect("account_signup")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("mi_cuenta")
    # Usamos el login de allauth
    return redirect("account_login")