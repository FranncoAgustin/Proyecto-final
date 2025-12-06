# cliente/views.py
from decimal import Decimal

from django import forms
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout, authenticate, login

from cliente.forms import RegistroForm, ProfileForm
from .models import Profile
from pdf.models import ProductoPrecio  # tu modelo de productos


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


# =========================
# VISTAS: CARRITO
# =========================

def ver_carrito(request):
    cart = _get_cart(request)
    items = []
    total = Decimal("0.00")

    for prod_id, qty in cart.items():
        producto = ProductoPrecio.objects.filter(pk=prod_id).first()
        if not producto:
            continue

        qty = int(qty)
        subtotal = producto.precio * qty
        total += subtotal
        items.append(
            {"producto": producto, "cantidad": qty, "subtotal": subtotal}
        )

    contexto = {"items": items, "total": total}
    return render(request, "cliente/carrito.html", contexto)


def agregar_al_carrito(request, pk):
    producto = get_object_or_404(ProductoPrecio, pk=pk)

    cart = _get_cart(request)
    prod_key = str(producto.id)
    cart[prod_key] = cart.get(prod_key, 0) + 1
    _save_cart(request, cart)

    messages.success(request, f'"{producto.nombre_publico}" se agregó al carrito.')

    next_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or "ver_carrito"
    return redirect(next_url)


def eliminar_del_carrito(request, pk):
    cart = _get_cart(request)
    cart.pop(str(pk), None)
    _save_cart(request, cart)
    return redirect("ver_carrito")


def actualizar_cantidad(request, pk):
    if request.method == "POST":
        try:
            qty = int(request.POST.get("cantidad", 1))
        except ValueError:
            qty = 1

        cart = _get_cart(request)

        if qty <= 0:
            cart.pop(str(pk), None)
        else:
            cart[str(pk)] = qty

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
            messages.success(request, "Tu perfil se actualizó correctamente.")
            return redirect("mi_cuenta")
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
    return redirect("home")


# =========================
# REGISTRO Y LOGIN
# =========================

def registro_view(request):
    if request.user.is_authenticated:
        return redirect("mi_cuenta")

    if request.method == "POST":
        form = RegistroForm(request.POST)
        if form.is_valid():
            user = form.save()
            # logueamos directamente
            login(request, user)
            messages.success(request, "Cuenta creada correctamente.")
            return redirect("mi_cuenta")
    else:
        form = RegistroForm()

    return render(request, "cliente/registro.html", {"form": form})


class LoginForm(forms.Form):
    email = forms.EmailField(label="Email")
    password = forms.CharField(label="Contraseña", widget=forms.PasswordInput)


def login_view(request):
    if request.user.is_authenticated:
        return redirect("mi_cuenta")

    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].lower()
        password = form.cleaned_data["password"]

        user = authenticate(request, username=email, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, "Bienvenido/a de nuevo.")
            return redirect("mi_cuenta")
        else:
            messages.error(request, "Email o contraseña incorrectos.")

    return render(request, "cliente/login.html", {"form": form})
