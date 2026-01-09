# owner/views.py

from difflib import SequenceMatcher
from decimal import Decimal, InvalidOperation
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
import re
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import TemplateView

from pdf.models import (
    ItemFactura,
    ListaPrecioPDF,
    ProductoPrecio,
    FacturaProveedor,
    ProductoVariante,
    Rubro,
    SubRubro,
)

from .models import SiteInfoBlock  # arriba, con el resto de imports
from django import forms

from owner.forms import (
    ProductoVarianteForm,
    ProductoPrecioForm,
    ProductoVarianteFormSet,
    RubroForm,
    SubRubroForm,
)

from ofertas.models import Oferta
from ofertas.forms import OfertaForm
from cupones.models import Cupon
from cupones.forms import CuponForm


# -------------------------------------------------------------------
# Helper de permiso: solo dueño / superuser
# -------------------------------------------------------------------
def _check_owner(user):
    return getattr(user, "is_owner", False) or getattr(user, "is_superuser", False)


def _check_owner_or_403(user):
    if not _check_owner(user):
        raise PermissionDenied


# -------------------------------------------------------------------
# Panel principal
# -------------------------------------------------------------------
class AdminDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "owner/admin_panel.html"

    def dispatch(self, request, *args, **kwargs):
        if not _check_owner(request.user):
            raise PermissionDenied("No tienes permiso para ver esta página.")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """
        Acciones masivas del panel:
        - activar
        - desactivar
        - eliminar
        - set_tech  (NUEVO)
        """
        if not _check_owner(request.user):
            raise PermissionDenied("No tienes permiso para hacer esto.")

        accion = (request.POST.get("bulkAccion") or "").strip()
        ids = request.POST.getlist("ids")

        if not accion or not ids:
            messages.warning(request, "No seleccionaste acción masiva o productos.")
            return redirect("home")

        qs = ProductoPrecio.objects.filter(pk__in=ids)
        if not qs.exists():
            messages.warning(request, "No se encontraron productos.")
            return redirect("home")

        # =========================
        # ✅ NUEVO: asignar técnica
        # =========================
        if accion == "set_tech":
            tech = (request.POST.get("bulkTech") or "").strip().upper()
            TECH_VALIDOS = {"SUB", "LAS", "3D", "OTR"}

            if tech not in TECH_VALIDOS:
                messages.error(request, "Elegí una técnica válida.")
                return redirect("home")

            count = qs.update(tech=tech)
            label = {
                "SUB": "Sublimación",
                "LAS": "Grabado láser",
                "3D": "Impresión 3D",
                "OTR": "Otro",
            }[tech]

            messages.success(
                request,
                f"Técnica '{label}' asignada a {count} producto(s)."
            )
            return redirect("home")

        # =========================
        # Acciones existentes
        # =========================
        if accion == "activar":
            count = qs.update(activo=True)
            messages.success(request, f"Se dieron de alta {count} producto(s).")

        elif accion == "desactivar":
            count = qs.update(activo=False)
            messages.warning(request, f"Se dieron de baja {count} producto(s).")

        elif accion == "eliminar":
            count = qs.count()
            nombres = [p.nombre_publico or p.sku for p in qs]
            qs.delete()
            messages.success(
                request,
                f"Se eliminaron {count} producto(s): "
                + ", ".join(nombres[:5])
                + (" ..." if len(nombres) > 5 else "")
            )
        else:
            messages.error(request, "Acción masiva no reconocida.")

        return redirect("home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        req = self.request

        q = req.GET.get("q", "").strip()
        t = req.GET.get("t", "").strip().lower()
        o = req.GET.get("o", "").strip()
        show_inactive = req.GET.get("show_inactive") == "1"

        qs = ProductoPrecio._base_manager.all()

        if not show_inactive:
            qs = qs.filter(activo=True)

        if q:
            qs = qs.filter(Q(sku__icontains=q) | Q(nombre_publico__icontains=q))

        tech_map = {
            "sub": "SUB",
            "laser": "LAS",
            "3d": "3D",
            "otr": "OTR",
        }
        if t in tech_map:
            qs = qs.filter(tech=tech_map[t])

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

        context.update({
            "products": qs,
            "q": q,
            "t": t,
            "o": o,
            "show_inactive": show_inactive,
            "total_productos_precio": ProductoPrecio._base_manager.count(),
        })

        context["producto_precios_recientes"] = (
            ProductoPrecio._base_manager.all()
            .order_by("-ultima_actualizacion")[:5]
        )
        context["listas_pdf_recientes"] = ListaPrecioPDF.objects.all().order_by("-fecha_subida")[:5]
        context["facturas_recientes"] = FacturaProveedor.objects.all().order_by("-fecha_subida")[:5]
        context["total_items_facturas"] = ItemFactura.objects.count()

        return context


def _parse_decimal(raw, fallback="0"):
    s = (raw if raw is not None else fallback)
    s = str(s).strip().replace(".", "").replace(",", ".")  # 1.234,56 -> 1234.56
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal(str(fallback))


def _parse_precio_desde_pdf(raw: str | None) -> Decimal:
    """
    Interpreta la columna de precio del PDF.

    - 'AGOTADO', 'AGOTADA', 'SIN STOCK', 'S/STOCK', '-', vacío, etc. → 0
      (y después vos decidís si esos productos los marcás como activo=False o stock=0)
    - cualquier número con puntos y comas → lo parsea a Decimal
    """
    if raw is None:
        return Decimal("0")

    txt = str(raw).strip().upper()

    # Palabras que indican que el proveedor no tiene stock / sin precio
    if txt in {"AGOTADO", "AGOTADA", "SIN STOCK", "S/STOCK", "SIN PRECIO", "-", ""}:
        return Decimal("0")

    # Si llega acá, intentamos parsear como número normal
    # Ej: "1.234,56" → 1234.56
    s = txt.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        # Si igual no se puede leer, devolvemos 0 para no saltear el producto
        return Decimal("0")


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

    rubros = Rubro.objects.filter(activo=True).order_by("tech", "orden", "nombre")
    subrubros = (
        SubRubro.objects
        .filter(activo=True)
        .select_related("rubro")
        .order_by("rubro__orden", "orden", "nombre")
    )

    if request.method == "POST":
        action = request.POST.get("action", "")

        # ====================
        # Acciones rápidas
        # ====================
        if action == "delete_image":
            if producto.imagen:
                producto.imagen.delete(save=False)
                producto.imagen = None
                producto.save(update_fields=["imagen"])
            messages.success(request, "Imagen eliminada.")
            return redirect("owner_producto_editar", pk=producto.pk)

        if action == "toggle_active":
            producto.activo = not bool(producto.activo)
            producto.save(update_fields=["activo"])
            messages.success(request, "Estado actualizado.")
            return redirect("owner_producto_editar", pk=producto.pk)

        if action == "delete_product":
            producto.delete()
            messages.success(request, "Producto eliminado.")
            return redirect("home")

        # ====================
        # Guardar producto + variantes
        # ====================
        # Inline formset de variantes
        vformset = ProductoVarianteFormSet(
            request.POST,
            request.FILES,
            instance=producto,
            prefix="v",
        )

        # --- Actualizamos el producto igual que antes ---
        producto.sku = (request.POST.get("sku") or producto.sku).strip()
        producto.nombre_publico = (request.POST.get("nombre_publico") or producto.nombre_publico).strip()
        producto.precio = _parse_decimal(request.POST.get("precio"), fallback=str(producto.precio))
        producto.stock = int(request.POST.get("stock") or producto.stock or 0)
        producto.tech = request.POST.get("tech", "") or ""
        producto.activo = request.POST.get("activo") == "on"

        if request.FILES.get("imagen"):
            producto.imagen = request.FILES["imagen"]

        # 🔹 Rubro / Subrubro desde el formulario
        rubro_nombre = (request.POST.get("rubro_nombre") or "").strip()
        subrubro_nombre = (request.POST.get("subrubro_nombre") or "").strip()

        nombre = (producto.nombre_publico or producto.sku or "").strip()
        tech = producto.tech or ""

        rubro_obj = None
        if not rubro_nombre:
            # Intentar detectarlo automáticamente
            rubro_obj = _detectar_rubro_auto(nombre, tech)
            if rubro_obj:
                rubro_nombre = rubro_obj.nombre
        else:
            rubro_obj = Rubro.objects.filter(
                nombre__iexact=rubro_nombre,
                activo=True
            ).first()

        # Guardamos siempre rubro y subrubro (subrubro puede quedar vacío)
        producto.rubro = rubro_nombre
        producto.subrubro = subrubro_nombre

        if vformset.is_valid():
            with transaction.atomic():
                # Primero guardamos el producto
                producto.save()

                # Luego las variantes
                vformset.save()

                # Si hay variantes, recalculamos stock como suma
                variantes_qs = producto.variantes.all()
                if variantes_qs.exists():
                    total_stock = sum((v.stock or 0) for v in variantes_qs)
                    producto.stock = total_stock
                    producto.save(update_fields=["stock"])

            messages.success(request, "Producto actualizado.")
            return redirect("owner_producto_editar", pk=producto.pk)
        else:
            messages.error(request, "Hay errores en las variantes. Revisá los campos resaltados.")

    else:
        # GET
        vformset = ProductoVarianteFormSet(
            instance=producto,
            prefix="v",
        )

    variantes = producto.variantes.all()

    return render(
        request,
        "owner/producto_editar.html",
        {
            "producto": producto,
            "variantes": variantes,
            "rubros": rubros,
            "subrubros": subrubros,
            "vformset": vformset,
        },
    )


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
    """
    Versión antigua basada en 'accion' + 'ids'.
    La podés seguir usando desde otros templates si querés.
    """
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

def owner_oferta_list(request):
    ofertas = Oferta.objects.all()
    return render(request, "owner/oferta_list.html", {"ofertas": ofertas})


def owner_oferta_create(request):
    if request.method == "POST":
        form = OfertaForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("owner_oferta_list")
    else:
        form = OfertaForm()
    return render(request, "owner/oferta_form.html", {"form": form, "modo": "Crear"})


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


def owner_oferta_delete(request, oferta_id):
    oferta = get_object_or_404(Oferta, id=oferta_id)
    oferta.delete()
    return redirect("owner_oferta_list")


# ---------- Helpers de rubros / autorubros ----------
def _normalizar_palabras(texto: str) -> set[str]:
    """
    Devuelve un set de 'tokens base' para comparar:
    - minúsculas
    - sin signos
    - si termina en 's' y tiene al menos 4 letras → le saco la 's' (mates -> mate, tazas -> taza)
    """
    if not texto:
        return set()

    tokens = re.findall(r"\w+", texto.lower())
    base_tokens = []
    for t in tokens:
        if len(t) > 3 and t.endswith("s"):
            base_tokens.append(t[:-1])
        else:
            base_tokens.append(t)
    return set(base_tokens)


def _score_rubro_para_producto(tokens_producto: set[str], obj_con_nombre, tech_producto: str) -> float:
    """
    Calcula un score de similitud entre:
      - palabras del nombre del producto (tokens_producto)
      - nombre del rubro/subrubro (obj_con_nombre.nombre)
    Usa:
      - +1 por coincidencia exacta
      - +ratio (0.8–1.0) por coincidencias aproximadas (chop ~ chopp)
      - +1 extra si coincide la técnica (si obj_con_nombre tiene .rubro.tech o .tech)
    """
    nombre = getattr(obj_con_nombre, "nombre", "")
    tokens_rubro = _normalizar_palabras(nombre)
    if not tokens_rubro or not tokens_producto:
        return 0.0

    score = 0.0

    for tp in tokens_producto:
        for tr in tokens_rubro:
            if tp == tr:
                score += 1.0
            else:
                sim = SequenceMatcher(None, tp, tr).ratio()
                if sim >= 0.8:
                    score += sim

    # Miramos técnica en Rubro o en Rubro asociado
    tech_obj = ""
    if hasattr(obj_con_nombre, "tech"):
        tech_obj = obj_con_nombre.tech or ""
    elif hasattr(obj_con_nombre, "rubro") and obj_con_nombre.rubro:
        tech_obj = obj_con_nombre.rubro.tech or ""

    if tech_obj and tech_producto and tech_obj == tech_producto:
        score += 1.0

    return score


def _detectar_rubro_auto(nombre: str, tech: str):
    """
    Intenta detectar un Rubro automáticamente en base al nombre del producto
    y la técnica. Devuelve un objeto Rubro o None.
    """
    if not nombre:
        return None

    tokens_producto = _normalizar_palabras(nombre)
    if not tokens_producto:
        return None

    qs = Rubro.objects.filter(activo=True)
    if tech:
        qs = qs.filter(tech=tech)

    mejor_rubro = None
    mejor_score = 0.0

    for r in qs:
        score = _score_rubro_para_producto(tokens_producto, r, tech)
        if score > mejor_score:
            mejor_score = score
            mejor_rubro = r

    if mejor_rubro and mejor_score >= 1.0:
        return mejor_rubro
    return None


def owner_producto_create_ui(request):
    """
    Alta de 1 artículo:
    - ProductoPrecio: sku, nombre_publico, imagen, precio, stock, tech, activo, rubro, subrubro
    - Variantes opcionales: ProductoVariante (nombre, imagen, stock, etc.)
    """
    rubros = Rubro.objects.filter(activo=True).order_by("tech", "orden", "nombre")
    subrubros = (
        SubRubro.objects
        .filter(activo=True)
        .select_related("rubro")
        .order_by("rubro__orden", "orden", "nombre")
    )

    if request.method == "POST":
        form = ProductoPrecioForm(request.POST, request.FILES)
        vformset = ProductoVarianteFormSet(request.POST, request.FILES, prefix="variants")

        # 💡 IMPORTANTE: validamos primero
        if form.is_valid() and vformset.is_valid():
            # No guardamos todavía en DB
            producto = form.save(commit=False)

            # Guardamos aparte la imagen para asignarla DESPUÉS del primer save()
            imagen_file = form.cleaned_data.get("imagen")

            # si no ponen nombre_publico, usar sku
            if not (producto.nombre_publico or "").strip():
                producto.nombre_publico = producto.sku

            nombre = (producto.nombre_publico or producto.sku or "").strip()
            tech = producto.tech or ""

            rubro_nombre = (request.POST.get("rubro_nombre") or "").strip()
            subrubro_nombre = (request.POST.get("subrubro_nombre") or "").strip()

            rubro_obj = None
            # 🔹 Si NO eligieron rubro en el select → intentamos adivinarlo
            if not rubro_nombre:
                rubro_obj = _detectar_rubro_auto(nombre, tech)
                if rubro_obj:
                    rubro_nombre = rubro_obj.nombre
            else:
                rubro_obj = Rubro.objects.filter(
                    nombre__iexact=rubro_nombre,
                    activo=True
                ).first()

            # Guardamos siempre rubro y subrubro (subrubro puede quedar vacío)
            producto.rubro = rubro_nombre
            producto.subrubro = subrubro_nombre

            # ⚠️ Primer save SIN imagen (para que ya tenga ID)
            #    Si tu upload_to usa el ID, esto evita que explote
            producto.imagen = None
            producto.save()

            # 🔁 Ahora sí: asignamos imagen y guardamos SOLO ese campo
            if imagen_file:
                producto.imagen = imagen_file
                try:
                    producto.save(update_fields=["imagen"])
                except Exception as e:
                    # No tiramos todo por la borda si la imagen falla:
                    # el producto queda creado y mostramos el error
                    messages.error(
                        request,
                        f"El producto se creó pero hubo un problema guardando la imagen: {e}"
                    )

            # ===== Variantes =====
            vformset.instance = producto
            vformset.save()

            # Si hay variantes activas, recalculamos stock
            variantes_activas = producto.variantes.filter(activo=True)
            if variantes_activas.exists():
                total = sum(v.stock or 0 for v in variantes_activas)
                producto.stock = total
                producto.save(update_fields=["stock"])

            messages.success(request, "Artículo creado correctamente.")
            return redirect("catalogo")
        else:
            # Si algo falla, mostramos errores (por si el problema viene por validación)
            messages.error(request, "Hay errores en el formulario o en las variantes. Revisá los campos.")
    else:
        form = ProductoPrecioForm()
        vformset = ProductoVarianteFormSet(prefix="variants")

    return render(
        request,
        "owner/producto_create.html",
        {
            "form": form,
            "vformset": vformset,
            "rubros": rubros,
            "subrubros": subrubros,
        },
    )


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


@login_required
def owner_rubros_list(request):
    rubros = Rubro.objects.all()
    return render(request, "owner/rubros_list.html", {"rubros": rubros})


@login_required
def owner_rubro_create(request):
    if request.method == "POST":
        form = RubroForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Rubro creado correctamente.")
            return redirect("owner_rubros_list")
    else:
        form = RubroForm()
    return render(request, "owner/rubro_form.html", {"form": form})


@login_required
def owner_subrubro_create(request):
    if request.method == "POST":
        form = SubRubroForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Sub-rubro creado correctamente.")
            return redirect("owner_rubros_list")
    else:
        form = SubRubroForm()
    return render(request, "owner/subrubro_form.html", {"form": form})

class SiteInfoBlockForm(forms.ModelForm):
    class Meta:
        model = SiteInfoBlock
        fields = ["clave", "titulo", "contenido", "orden", "activo"]
        widgets = {
            "contenido": forms.Textarea(attrs={"rows": 4}),
        }


@login_required
def owner_siteinfo_list(request):
    """
    Pantalla simple para editar los bloques de info que aparecen en el footer.
    """
    if not _check_owner(request.user):
        raise PermissionDenied

    bloques = SiteInfoBlock.objects.all().order_by("orden", "titulo")

    if request.method == "POST":
        forms_list = []
        ok = True

        for bloque in bloques:
            form = SiteInfoBlockForm(
                request.POST,
                prefix=f"b{bloque.id}",
                instance=bloque,
            )
            forms_list.append(form)
            if not form.is_valid():
                ok = False

        # Permitimos agregar un bloque nuevo (opcional)
        nuevo_form = SiteInfoBlockForm(
            request.POST,
            prefix="nuevo",
        )
        if nuevo_form.has_changed():
            if nuevo_form.is_valid():
                nuevo_form.save()
            else:
                ok = False

        if ok:
            for form in forms_list:
                form.save()
            messages.success(request, "Información del sitio actualizada.")
            return redirect("owner_siteinfo_list")
        else:
            messages.error(request, "Revisá los errores en los bloques.")

    else:
        forms_list = [
            SiteInfoBlockForm(prefix=f"b{b.id}", instance=b) for b in bloques
        ]
        nuevo_form = SiteInfoBlockForm(prefix="nuevo")

    data = list(zip(bloques, forms_list))

    return render(
        request,
        "owner/siteinfo_list.html",
        {
            "bloques_forms": data,
            "nuevo_form": nuevo_form,
        },
    )


@login_required
def owner_filtros_panel(request):
    """
    Panel para administrar Rubros y Subrubros desde el front owner.
    - Alta de Rubro (con técnica)
    - Alta de Subrubro asociado a un Rubro
    - Edición y eliminación de Rubro y SubRubro
    - Listado agrupado por técnica con accordion
    """

    if not _check_owner(request.user):
        raise PermissionDenied

    TECH_CHOICES = [
        ("SUB", "Sublimación"),
        ("LAS", "Grabado láser"),
        ("3D",  "Impresión 3D"),
        ("OTR", "Otros"),
    ]

    # =====================



    # POST: acciones
    # =====================
    if request.method == "POST":
        # ---- Crear rubro ----
        if "add_rubro" in request.POST:
            nombre = (request.POST.get("nombre_rubro") or "").strip()
            tech = (request.POST.get("tech") or "").strip()  # SUB / LAS / 3D / OTR

            if not nombre or not tech:
                messages.error(request, "Completá el nombre del rubro y la técnica.")
            else:
                # Evitar duplicados por nombre + técnica
                existe = Rubro.objects.filter(
                    nombre__iexact=nombre,
                    tech=tech,
                ).exists()
                if existe:
                    messages.warning(
                        request,
                        f"Ya existe un rubro “{nombre}” para la técnica seleccionada."
                    )
                else:
                    Rubro.objects.create(nombre=nombre, tech=tech, activo=True)
                    messages.success(request, f"Rubro “{nombre}” creado correctamente.")

            return redirect("owner_filtros_panel")

        # ---- Crear subrubro ----
        if "add_subrubro" in request.POST:
            nombre = (request.POST.get("nombre_subrubro") or "").strip()
            rubro_id = request.POST.get("rubro_id")

            if not nombre or not rubro_id:
                messages.error(request, "Elegí un rubro y escribí el nombre del subfiltro.")
            else:
                rubro = get_object_or_404(Rubro, pk=rubro_id)

                # Evitar duplicados por rubro + nombre
                existe = SubRubro.objects.filter(
                    rubro=rubro,
                    nombre__iexact=nombre,
                ).exists()
                if existe:
                    messages.warning(
                        request,
                        f"Ya existe el subfiltro “{nombre}” dentro de “{rubro.nombre}”."
                    )
                else:
                    SubRubro.objects.create(rubro=rubro, nombre=nombre, activo=True)
                    messages.success(
                        request,
                        f"Subfiltro “{nombre}” agregado al rubro “{rubro.nombre}”.",
                    )

            return redirect("owner_filtros_panel")

        # ---- Editar rubro ----
        if "edit_rubro" in request.POST:
            rubro_id = request.POST.get("rubro_id")
            rubro = get_object_or_404(Rubro, pk=rubro_id)

            nuevo_nombre = (request.POST.get("nuevo_nombre_rubro") or "").strip()
            nueva_tech = (request.POST.get("nuevo_tech") or "").strip()

            if not nuevo_nombre or not nueva_tech:
                messages.error(request, "Completá el nombre y la técnica del rubro.")
            else:
                existe = Rubro.objects.filter(
                    nombre__iexact=nuevo_nombre,
                    tech=nueva_tech,
                ).exclude(pk=rubro.id).exists()
                if existe:
                    messages.warning(
                        request,
                        f"Ya existe un rubro “{nuevo_nombre}” para esa técnica."
                    )
                else:
                    rubro.nombre = nuevo_nombre
                    rubro.tech = nueva_tech
                    rubro.save(update_fields=["nombre", "tech"])
                    messages.success(request, "Rubro actualizado correctamente.")

            return redirect("owner_filtros_panel")

        # ---- Eliminar rubro ----
        if "delete_rubro" in request.POST:
            rubro_id = request.POST.get("rubro_id")
            rubro = get_object_or_404(Rubro, pk=rubro_id)
            nombre = rubro.nombre
            rubro.delete()  # borra también sus subrubros por on_delete=CASCADE
            messages.success(
                request,
                f"Rubro “{nombre}” y sus subfiltros asociados fueron eliminados."
            )
            return redirect("owner_filtros_panel")

        # ---- Editar subrubro ----
        if "edit_subrubro" in request.POST:
            sub_id = request.POST.get("subrubro_id")
            sub = get_object_or_404(SubRubro, pk=sub_id)
            nuevo_nombre = (request.POST.get("nuevo_nombre_subrubro") or "").strip()

            if not nuevo_nombre:
                messages.error(request, "Completá el nombre del subfiltro.")
            else:
                existe = SubRubro.objects.filter(
                    rubro=sub.rubro,
                    nombre__iexact=nuevo_nombre,
                ).exclude(pk=sub.id).exists()
                if existe:
                    messages.warning(
                        request,
                        f"Ya existe el subfiltro “{nuevo_nombre}” dentro de “{sub.rubro.nombre}”."
                    )
                else:
                    sub.nombre = nuevo_nombre
                    sub.save(update_fields=["nombre"])
                    messages.success(request, "Subfiltro actualizado correctamente.")

            return redirect("owner_filtros_panel")

        # ---- Eliminar subrubro ----
        if "delete_subrubro" in request.POST:
            sub_id = request.POST.get("subrubro_id")
            sub = get_object_or_404(SubRubro, pk=sub_id)
            nombre = sub.nombre
            rubro_nombre = sub.rubro.nombre
            sub.delete()
            messages.success(
                request,
                f"Subfiltro “{nombre}” eliminado del rubro “{rubro_nombre}”."
            )
            return redirect("owner_filtros_panel")

    # =====================
    # GET: listar rubros + subrubros
    # =====================
    rubros_qs = (
        Rubro.objects
        .prefetch_related("subrubros")
        .order_by("tech", "orden", "nombre")
    )

    # Agrupar rubros por técnica para el accordion
    rubros_por_tech = []
    rubros_list = list(rubros_qs)
    for code, label in TECH_CHOICES:
        rubros_filtrados = [r for r in rubros_list if r.tech == code]
        rubros_por_tech.append({
            "code": code,
            "label": label,
            "rubros": rubros_filtrados,
        })

    return render(
        request,
        "owner/filtros_panel.html",
        {
            "rubros_por_tech": rubros_por_tech,
            "TECH_CHOICES": TECH_CHOICES,
        },
    )


@require_POST
def owner_api_rubro_create(request):
    """
    Crea un Rubro rápidamente desde crear/editar producto.
    Espera: nombre, tech
    Devuelve JSON con datos del rubro creado o error.
    """
    _check_owner_or_403(request.user)

    nombre = (request.POST.get("nombre") or "").strip()
    tech = (request.POST.get("tech") or "").strip()

    if not nombre:
        return JsonResponse({"ok": False, "error": "El nombre del rubro es obligatorio."}, status=400)

    # Opcional: si no mandás tech, lo dejamos vacío
    rubro, created = Rubro.objects.get_or_create(
        nombre=nombre,
        defaults={
            "tech": tech or "",
            "orden": 0,
            "activo": True,
        },
    )

    # Si ya existía pero sin técnica y ahora tenemos, podríamos actualizarla
    if not created and tech and not rubro.tech:
        rubro.tech = tech
        rubro.save(update_fields=["tech"])

    return JsonResponse({
        "ok": True,
        "rubro": {
            "id": rubro.id,
            "nombre": rubro.nombre,
            "tech": rubro.tech,
        }
    })


@require_POST
def owner_api_subrubro_create(request):
    """
    Crea un SubRubro rápidamente desde crear/editar producto.
    Espera: rubro_id, nombre
    """
    _check_owner_or_403(request.user)

    rubro_id = request.POST.get("rubro_id")
    nombre = (request.POST.get("nombre") or "").strip()

    if not rubro_id:
        return JsonResponse({"ok": False, "error": "Falta rubro padre."}, status=400)

    if not nombre:
        return JsonResponse({"ok": False, "error": "El nombre del sub-filtro es obligatorio."}, status=400)

    try:
        rubro = Rubro.objects.get(pk=int(rubro_id), activo=True)
    except (Rubro.DoesNotExist, ValueError):
        return JsonResponse({"ok": False, "error": "El rubro seleccionado no existe."}, status=400)

    sub, created = SubRubro.objects.get_or_create(
        rubro=rubro,
        nombre=nombre,
        defaults={
            "orden": 0,
            "activo": True,
        }
    )

    return JsonResponse({
        "ok": True,
        "subrubro": {
            "id": sub.id,
            "nombre": sub.nombre,
            "rubro_id": rubro.id,
            "rubro_nombre": rubro.nombre,
        }
    })


def _build_sugerencias_rubros():
    """
    Devuelve una lista de sugerencias de rubro/subrubro para productos activos:

    [
      {
        "producto": <ProductoPrecio>,
        "rubro": <Rubro>,
        "subrubro": <SubRubro> | None,
        "score": 2.7,
      },
      ...
    ]
    """

    productos = ProductoPrecio.objects.filter(activo=True)

    rubros = list(Rubro.objects.filter(activo=True))
    subrubros = list(
        SubRubro.objects.filter(activo=True).select_related("rubro")
    )

    sugerencias = []

    for p in productos:
        nombre = (p.nombre_publico or p.sku or "").strip()
        tokens_p = _normalizar_palabras(nombre)
        if not tokens_p:
            continue

        tech_p = p.tech or ""
        rubro_actual = (p.rubro or "").strip().lower()
        subrubro_actual = (p.subrubro or "").strip().lower()

        # 1) Intentar matchear SUBRUBROS primero
        best_sub = None
        best_sub_score = 0.0

        for s in subrubros:
            # respetar técnica si ambas están definidas
            if tech_p and s.rubro.tech and s.rubro.tech != tech_p:
                continue

            score = _score_rubro_para_producto(tokens_p, s, tech_p)
            if score > best_sub_score:
                best_sub_score = score
                best_sub = s

        if best_sub and best_sub_score >= 1.0:
            rubro_sug = best_sub.rubro
            rubro_sug_nombre = (rubro_sug.nombre or "").strip().lower()
            sub_sug_nombre = (best_sub.nombre or "").strip().lower()

            # Si ya tiene exactamente ese rubro + ese subfiltro, no lo sugerimos
            if rubro_actual == rubro_sug_nombre and subrubro_actual == sub_sug_nombre:
                continue

            sugerencias.append({
                "producto": p,
                "rubro": rubro_sug,
                "subrubro": best_sub,
                "score": round(best_sub_score, 2),
            })
            continue  # ya tenemos una buena sugerencia por subrubro

        # 2) Si no hay buen subrubro, probamos RUBROS
        best_rubro = None
        best_rubro_score = 0.0

        for r in rubros:
            if tech_p and r.tech and r.tech != tech_p:
                continue

            score = _score_rubro_para_producto(tokens_p, r, tech_p)
            if score > best_rubro_score:
                best_rubro_score = score
                best_rubro = r

        if best_rubro and best_rubro_score >= 1.0:
            rubro_sug_nombre = (best_rubro.nombre or "").strip().lower()

            # Si ya tiene ese rubro (aunque subrubro distinto), no sugerimos nada
            if rubro_actual == rubro_sug_nombre:
                continue

            sugerencias.append({
                "producto": p,
                "rubro": best_rubro,
                "subrubro": None,
                "score": round(best_rubro_score, 2),
            })

    sugerencias.sort(
        key=lambda s: (-s["score"], s["producto"].nombre_publico.lower())
    )
    return sugerencias


def owner_autorubros(request):
    """
    Pantalla para sugerir rubros a productos basados en el nombre.
    - Muestra sugerencia de rubro/subrubro
    - Permite cambiar rubro y elegir subfiltro por cada producto
    - Aplica solo a los que marcás (checkbox)
    """

    if not _check_owner(request.user):
        raise PermissionDenied

    if request.method == "POST":
        asignaciones = request.POST.getlist("aplicar")
        aplicadas = 0

        for pid_str in asignaciones:
            try:
                pid = int(pid_str)
            except ValueError:
                continue

            rubro_nombre = (request.POST.get(f"rubro_{pid}") or "").strip()
            subrubro_nombre = (request.POST.get(f"subrubro_{pid}") or "").strip()

            update_fields = {
                "rubro": rubro_nombre,
                "subrubro": subrubro_nombre,
            }

            ProductoPrecio.objects.filter(pk=pid).update(**update_fields)
            aplicadas += 1

        if aplicadas:
            messages.success(request, f"Se actualizaron {aplicadas} producto(s).")
        else:
            messages.info(request, "No se aplicó ningún cambio (ningún producto marcado).")

        return redirect("owner_autorubros")

    # GET
    sugerencias = _build_sugerencias_rubros()

    rubros = Rubro.objects.filter(activo=True).order_by("tech", "orden", "nombre")
    subrubros = (
        SubRubro.objects
        .filter(activo=True)
        .select_related("rubro")
        .order_by("rubro__orden", "orden", "nombre")
    )

    return render(
        request,
        "owner/autorubros.html",
        {
            "sugerencias": sugerencias,
            "rubros": rubros,
            "subrubros": subrubros,
        },
    )
