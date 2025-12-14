# owner/views.py

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import TemplateView

from pdf.models import ItemFactura, ListaPrecioPDF, ProductoPrecio, FacturaProveedor


# -------------------------------------------------------------------
# Helper de permiso: solo dueño / superuser
# -------------------------------------------------------------------
def _check_owner(user):
    return getattr(user, "is_owner", False) or getattr(user, "is_superuser", False)


# -------------------------------------------------------------------
# Panel principal
# -------------------------------------------------------------------
class AdminDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "owner/admin_panel.html"

    def dispatch(self, request, *args, **kwargs):
        if not _check_owner(request.user):
            raise PermissionDenied("No tienes permiso para ver esta página.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        req = self.request

        q = req.GET.get("q", "").strip()
        t = req.GET.get("t", "").strip().lower()
        o = req.GET.get("o", "").strip()
        show_inactive = req.GET.get("show_inactive") == "1"

        qs = ProductoPrecio.objects.all()

        # Activos / inactivos
        if not show_inactive:
            qs = qs.filter(activo=True)

        # Búsqueda por SKU o nombre
        if q:
            from django.db.models import Q

            qs = qs.filter(
                Q(sku__icontains=q) |
                Q(nombre_publico__icontains=q)
            )

        # Filtro por técnica
        tech_map = {
            "sub": "SUB",
            "laser": "LAS",
            "3d": "3D",
            "otr": "OTR",
        }
        if t in tech_map:
            qs = qs.filter(tech=tech_map[t])

        # Orden
        if o == "recientes":
            qs = qs.order_by("-created_at")
        elif o == "antiguos":
            qs = qs.order_by("created_at")
        elif o == "precio_desc":
            qs = qs.order_by("-precio")
        elif o == "precio_asc":
            qs = qs.order_by("precio")
        else:
            qs = qs.order_by("nombre_publico", "sku")

        context["products"] = qs
        context["q"] = q
        context["t"] = t
        context["o"] = o
        context["show_inactive"] = show_inactive

        # Resúmenes
        context["producto_precios_recientes"] = ProductoPrecio.objects.all().order_by(
            "-ultima_actualizacion"
        )[:5]
        context["listas_pdf_recientes"] = ListaPrecioPDF.objects.all().order_by(
            "-fecha_subida"
        )[:5]
        context["facturas_recientes"] = FacturaProveedor.objects.all().order_by(
            "-fecha_subida"
        )[:5]

        context["total_items_facturas"] = ItemFactura.objects.count()
        context["total_productos_precio"] = ProductoPrecio.objects.count()

        return context


# -------------------------------------------------------------------
# Historia de listas / facturas
# -------------------------------------------------------------------
class HistoriaIngresosView(LoginRequiredMixin, TemplateView):
    template_name = "owner/historia_listas.html"

    def dispatch(self, request, *args, **kwargs):
        if not _check_owner(request.user):
            raise PermissionDenied("No tienes permiso para ver esta página.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["listas_pdf"] = ListaPrecioPDF.objects.all().order_by("-fecha_subida")
        context["facturas"] = FacturaProveedor.objects.all().order_by("-fecha_subida")
        context["items_factura"] = ItemFactura.objects.select_related("factura").order_by(
            "-id"
        )
        return context


@login_required
def historia_listas(request):
    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para ver esta página.")

    listas = ListaPrecioPDF.objects.all().order_by("-fecha_subida")
    return render(request, "pdf/historia_listas.html", {"listas": listas})


@login_required
def historia_lista_detalle(request, lista_id):
    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para ver esta página.")

    lista = get_object_or_404(ListaPrecioPDF, pk=lista_id)
    productos = ProductoPrecio.objects.filter(lista_pdf=lista).order_by("nombre_publico", "sku")

    if request.method == "POST":
        for prod in productos:
            prefix = f"prod_{prod.id}_"

            sku = request.POST.get(prefix + "sku", "").strip()
            nombre = request.POST.get(prefix + "nombre", "").strip()
            precio = request.POST.get(prefix + "precio", "").strip()
            stock = request.POST.get(prefix + "stock", "").strip()

            if sku:
                prod.sku = sku
            if nombre:
                prod.nombre_publico = nombre

            if precio:
                try:
                    prod.precio = Decimal(precio.replace(",", "."))
                except Exception:
                    pass

            if stock:
                try:
                    prod.stock = int(stock)
                except Exception:
                    pass

            prod.save()

        messages.success(request, "Cambios guardados correctamente.")
        return redirect("historia_lista_detalle", lista_id=lista.id)

    return render(
        request,
        "pdf/historia_lista_detalle.html",
        {"lista": lista, "productos": productos},
    )


# -------------------------------------------------------------------
# Edición / alta-baja / eliminación desde panel admin
# -------------------------------------------------------------------
@login_required
def owner_producto_editar(request, pk):
    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para hacer esto.")

    producto = get_object_or_404(ProductoPrecio, pk=pk)

    if request.method == "POST":
        sku = request.POST.get("sku", "").strip()
        nombre_publico = request.POST.get("nombre_publico", "").strip()
        precio = request.POST.get("precio", "").strip()
        tech = request.POST.get("tech", "") or ""
        stock = request.POST.get("stock", "").strip()
        activo = request.POST.get("activo") == "on"

        if sku:
            producto.sku = sku
        producto.nombre_publico = nombre_publico or producto.sku

        if precio:
            try:
                producto.precio = Decimal(precio.replace(",", "."))
            except Exception:
                pass

        if stock:
            try:
                producto.stock = int(stock)
            except Exception:
                pass

        producto.tech = tech
        producto.activo = activo
        producto.save()

        messages.success(request, "Producto actualizado correctamente.")
        return redirect("home")

    return render(request, "owner/producto_editar.html", {"producto": producto})


@login_required
def owner_producto_toggle_activo(request, pk):
    if request.method != "POST":
        raise PermissionDenied("Método no permitido.")

    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para hacer esto.")

    producto = get_object_or_404(ProductoPrecio, pk=pk)
    producto.activo = not producto.activo
    producto.save(update_fields=["activo"])

    if producto.activo:
        messages.success(request, f"{producto.nombre_publico} se marcó como ACTIVO.")
    else:
        messages.warning(request, f"{producto.nombre_publico} se marcó como INACTIVO.")

    return redirect("home")


@login_required
def owner_producto_eliminar(request, pk):
    if request.method != "POST":
        raise PermissionDenied("Método no permitido.")

    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para hacer esto.")

    producto = get_object_or_404(ProductoPrecio, pk=pk)
    nombre = producto.nombre_publico or producto.sku
    producto.delete()

    messages.success(request, f"Producto '{nombre}' eliminado definitivamente.")
    return redirect("home")

@login_required
def owner_productos_acciones_masivas(request):
    if request.method != "POST":
        raise PermissionDenied("Método no permitido.")

    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para hacer esto.")

    ids = request.POST.getlist("ids")
    accion = (request.POST.get("accion") or "").strip()

    if not ids:
        messages.warning(request, "No seleccionaste ningún producto.")
        return redirect("home")

    qs = ProductoPrecio.objects.filter(pk__in=ids)

    if accion == "baja":
        count = qs.update(activo=False)
        messages.warning(request, f"{count} producto(s) marcados como INACTIVOS.")
    elif accion == "alta":
        count = qs.update(activo=True)
        messages.success(request, f"{count} producto(s) marcados como ACTIVOS.")
    elif accion == "eliminar":
        count = qs.count()
        nombres = [p.nombre_publico or p.sku for p in qs]
        qs.delete()
        messages.success(
            request,
            f"{count} producto(s) eliminados: {', '.join(nombres[:5])}"
            + (" ..." if len(nombres) > 5 else "")
        )
    else:
        messages.error(request, "Acción masiva no reconocida.")

    return redirect("home")

# ---------- CUPONES ----------
from cupones.models import Cupon
from cupones.forms import CuponForm

def owner_cupon_list(request):
    cupones = Cupon.objects.all().order_by('-creado')
    return render(request, "owner/cupon_list.html", {"cupones": cupones})

def owner_cupon_create(request):
    if request.method == "POST":
        form = CuponForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("owner_cupon_list")
    else:
        form = CuponForm()
    return render(request, "owner/cupon_form.html", {"form": form, "modo": "Crear"})

def owner_cupon_edit(request, cupon_id):
    cupon = get_object_or_404(Cupon, id=cupon_id)
    if request.method == "POST":
        form = CuponForm(request.POST, instance=cupon)
        if form.is_valid():
            form.save()
            return redirect("owner_cupon_list")
    else:
        form = CuponForm(instance=cupon)
    return render(request, "owner/cupon_form.html", {"form": form, "modo": "Editar"})

def owner_cupon_delete(request, cupon_id):
    cupon = get_object_or_404(Cupon, id=cupon_id)
    cupon.delete()
    return redirect("owner_cupon_list")

# ---------- OFERTAS ----------
from ofertas.models import Oferta
from ofertas.forms import OfertaForm

# Lista de ofertas
def owner_oferta_list(request):
    ofertas = Oferta.objects.all()
    return render(request, "owner/oferta_list.html", {"ofertas": ofertas})

# Crear una nueva oferta
def owner_oferta_create(request):
    if request.method == "POST":
        form = OfertaForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("owner_oferta_list")
    else:
        form = OfertaForm()
    return render(request, "owner/oferta_form.html", {"form": form, "modo": "Crear"})

# Editar una oferta existente
def owner_oferta_edit(request, oferta_id):
    oferta = get_object_or_404(Oferta, id=oferta_id)
    if request.method == "POST":
        form = OfertaForm(request.POST, instance=oferta)
        if form.is_valid():
            form.save()
            return redirect("owner_oferta_list")
    else:
        form = OfertaForm(instance=oferta)
    return render(request, "owner/oferta_form.html", {"form": form, "modo": "Editar"})

# Eliminar una oferta
def owner_oferta_delete(request, oferta_id):
    oferta = get_object_or_404(Oferta, id=oferta_id)
    oferta.delete()
    return redirect("owner_oferta_list")