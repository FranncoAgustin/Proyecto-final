# owner/views.py

from decimal import Decimal,InvalidOperation
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import TemplateView

from pdf.models import ItemFactura, ListaPrecioPDF, ProductoPrecio, FacturaProveedor, ProductoVariante
from owner.forms import ProductoVarianteForm, ProductoPrecioForm, ProductoVarianteFormSet


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


def _parse_decimal(raw, fallback="0"):
    s = (raw if raw is not None else fallback)
    s = str(s).strip().replace(".", "").replace(",", ".")  # 1.234,56 -> 1234.56
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal(str(fallback))
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
        raise PermissionDenied

    producto = get_object_or_404(ProductoPrecio, pk=pk)
    variantes = producto.variantes.all()

    if request.method == "POST":
        action = request.POST.get("action", "")

        # ✅ 1) Eliminar foto
        if action == "delete_image":
            if producto.imagen:
                # borra el archivo del storage y limpia el campo
                producto.imagen.delete(save=False)
                producto.imagen = None
                producto.save(update_fields=["imagen"])
            messages.success(request, "Imagen eliminada.")
            return redirect("owner_producto_editar", pk=producto.pk)

        # ✅ 2) Toggle activo (baja/alta)
        if action == "toggle_active":
            producto.activo = not bool(producto.activo)
            producto.save(update_fields=["activo"])
            messages.success(request, "Estado actualizado.")
            return redirect("owner_producto_editar", pk=producto.pk)

        # ✅ 3) Eliminar producto
        if action == "delete_product":
            producto.delete()
            messages.success(request, "Producto eliminado.")
            return redirect("home")

        # ✅ 4) Guardar cambios (default)
        producto.sku = (request.POST.get("sku") or producto.sku).strip()
        producto.nombre_publico = (request.POST.get("nombre_publico") or producto.nombre_publico).strip()
        producto.precio = _parse_decimal(request.POST.get("precio"), fallback=str(producto.precio))
        producto.stock = int(request.POST.get("stock") or producto.stock or 0)
        producto.tech = request.POST.get("tech", "") or ""
        producto.activo = request.POST.get("activo") == "on"

        if request.FILES.get("imagen"):
            producto.imagen = request.FILES["imagen"]

        producto.save()

        # (tu lógica de nueva variante si la querés mantener)
        nv_nombre = (request.POST.get("nueva_variante_nombre") or "").strip()
        if nv_nombre:
            ProductoVariante.objects.create(
                producto=producto,
                nombre=nv_nombre,
                descripcion_corta=(request.POST.get("nueva_variante_desc") or "").strip(),
                imagen=request.FILES.get("nueva_variante_imagen"),
            )

        messages.success(request, "Producto actualizado.")
        return redirect("owner_producto_editar", pk=producto.pk)

    return render(
        request,
        "owner/producto_editar.html",
        {"producto": producto, "variantes": variantes},
    )

@login_required
def owner_producto_variantes(request, pk):
    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para hacer esto.")

    producto = get_object_or_404(ProductoPrecio, pk=pk)
    variantes = producto.variantes.all().order_by("orden", "id")

    if request.method == "POST":
        form = ProductoVarianteForm(request.POST, request.FILES)
        if form.is_valid():
            v = form.save(commit=False)
            v.producto = producto
            v.save()
            messages.success(request, "Variante creada correctamente.")
            return redirect("owner_producto_variantes", pk=producto.pk)
    else:
        form = ProductoVarianteForm()

    return render(
        request,
        "owner/producto_variantes.html",
        {"producto": producto, "variantes": variantes, "form": form},
    )


@login_required
def owner_variante_editar(request, variante_id):
    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para hacer esto.")

    variante = get_object_or_404(ProductoVariante, pk=variante_id)
    producto = variante.producto

    if request.method == "POST":
        form = ProductoVarianteForm(request.POST, request.FILES, instance=variante)
        if form.is_valid():
            form.save()
            messages.success(request, "Variante actualizada.")
            return redirect("owner_producto_variantes", pk=producto.pk)
    else:
        form = ProductoVarianteForm(instance=variante)

    return render(
        request,
        "owner/variante_form.html",
        {"producto": producto, "variante": variante, "form": form},
    )


@login_required
def owner_variante_eliminar(request, variante_id):
    if request.method != "POST":
        raise PermissionDenied("Método no permitido.")

    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para hacer esto.")

    variante = get_object_or_404(ProductoVariante, pk=variante_id)
    producto_id = variante.producto_id
    variante.delete()

    messages.success(request, "Variante eliminada.")
    return redirect("owner_producto_variantes", pk=producto_id)



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
    cupones = Cupon.objects.all().order_by("-fecha_inicio")
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


@login_required(login_url="/admin/login/")
@transaction.atomic
def owner_producto_create_ui(request):
    """
    Alta de 1 artículo:
    - ProductoPrecio: sku, nombre_publico, imagen, precio, stock, tech, activo
    - Variantes opcionales: ProductoVariante (nombre, imagen, stock, etc.)
    """
    if request.method == "POST":
        form = ProductoPrecioForm(request.POST, request.FILES)
        vformset = ProductoVarianteFormSet(request.POST, request.FILES, prefix="variants")

        if form.is_valid() and vformset.is_valid():
            producto = form.save(commit=False)

            # si no ponen nombre_publico, usar sku
            if not (producto.nombre_publico or "").strip():
                producto.nombre_publico = producto.sku

            producto.save()

            vformset.instance = producto
            vformset.save()

            # Si hay variantes activas, podés setear stock total = suma(stock variantes)
            variantes_activas = producto.variantes.filter(activo=True)
            if variantes_activas.exists():
                total = sum(v.stock or 0 for v in variantes_activas)
                producto.stock = total
                producto.save(update_fields=["stock"])

            messages.success(request, "Artículo creado correctamente.")
            return redirect("owner_producto_create_ui")

    else:
        form = ProductoPrecioForm()
        vformset = ProductoVarianteFormSet(prefix="variants")

    return render(request, "owner/producto_create.html", {"form": form, "vformset": vformset})

@require_GET
def owner_api_product_suggest(request):
    """
    GET ?q=taza
    Devuelve lista corta para typeahead:
    [{id, sku, nombre_publico, precio, tech}, ...]
    """
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"results": []})

    qs = (ProductoPrecio.objects
          .filter(Q(sku__icontains=q) | Q(nombre_publico__icontains=q))
          .order_by("nombre_publico")[:20])

    results = [{
        "id": p.id,
        "sku": p.sku,
        "nombre_publico": p.nombre_publico,
        "precio": f"{p.precio:.2f}",
        "tech": p.tech or "",
    } for p in qs]

    return JsonResponse({"results": results})


@require_GET
def owner_api_product_detail(request, pk: int):
    """
    Devuelve data para autocompletar campos del form.
    """
    p = get_object_or_404(ProductoPrecio, pk=pk)
    return JsonResponse({
        "id": p.id,
        "sku": p.sku,
        "nombre_publico": p.nombre_publico,
        "precio": f"{p.precio:.2f}",
        "stock": p.stock,
        "precio_costo": f"{p.precio_costo:.2f}" if p.precio_costo is not None else "",
        "tech": p.tech or "",
        "activo": bool(p.activo),
        "imagen_url": p.imagen.url if p.imagen else "",
    })