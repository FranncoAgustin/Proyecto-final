# owner/views.py

from difflib import SequenceMatcher
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
import re

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Sum, Count, F, DecimalField, ExpressionWrapper
from django.forms import inlineformset_factory
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
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

from .models import SiteCarouselImage, SiteInfoBlock, SiteConfig, BitacoraEvento,VentaRapida

from owner.forms import (
    ProductoVarianteForm,
    ProductoPrecioForm,
    ProductoVarianteFormSet,
    RubroForm,
    SiteCarouselImageFormSet,
    SubRubroForm,
    SiteConfigForm,
    SiteInfoBlockFormSet,
    ProductoDesdeFacturaBulkForm,
    VentaRapidaForm,
)

from ofertas.models import Oferta
from ofertas.forms import OfertaForm
from cupones.models import Cupon
from cupones.forms import CuponForm
from django.core.files.base import ContentFile


User = get_user_model()


# -------------------------------------------------------------------
# Helper de permiso: solo dueño / superuser
# -------------------------------------------------------------------
def _check_owner(user):
    return getattr(user, "is_owner", False) or getattr(user, "is_superuser", False)


def _check_owner_or_403(user):
    if not _check_owner(user):
        raise PermissionDenied


# -------------------------------------------------------------------
# Helper de bitácora
# -------------------------------------------------------------------
def registrar_evento(tipo, titulo, detalle="", user=None, obj=None, extra=None):
    """
    Registra un evento en la bitácora global.

    - tipo: uno de BitacoraEvento.TIPO_CHOICES (ej: "producto_creado")
    - titulo: texto corto que se ve en la lista
    - detalle: texto más largo y 'humano' (opcional)
    - user: request.user o None
    - obj: algún modelo relacionado (ProductoPrecio, Pedido, FacturaProveedor, etc.)
    - extra: dict con datos técnicos (ids, montos, cambios, etc.)
    """
    datos = extra.copy() if extra else {}

    obj_model = ""
    obj_id = ""
    if obj is not None:
        obj_model = obj._meta.label  # "app.Model"
        obj_id = str(getattr(obj, "pk", ""))

    if user is not None and getattr(user, "is_authenticated", False):
        usuario = user
    else:
        usuario = None

    BitacoraEvento.objects.create(
        usuario=usuario,
        tipo=tipo,
        titulo=titulo,
        detalle=detalle or "",
        obj_model=obj_model,
        obj_id=obj_id,
        extra=datos,
    )


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
        - set_tech
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

            registrar_evento(
                tipo="precio_actualizado",
                titulo=f"Técnica masiva aplicada: {label}",
                detalle=f"Se asignó la técnica {label} a {count} producto(s) desde el panel.",
                user=request.user,
                extra={
                    "tech": tech,
                    "cantidad": count,
                    "ids": ids,
                },
            )

            return redirect("home")

        if accion == "activar":
            count = qs.update(activo=True)
            messages.success(request, f"Se dieron de alta {count} producto(s).")

            registrar_evento(
                tipo="producto_editado",
                titulo="Activación masiva de productos",
                detalle=f"Se marcaron como activos {count} producto(s) desde el panel.",
                user=request.user,
                extra={"cantidad": count, "ids": ids},
            )

        elif accion == "desactivar":
            count = qs.update(activo=False)
            messages.warning(request, f"Se dieron de baja {count} producto(s).")

            registrar_evento(
                tipo="producto_editado",
                titulo="Desactivación masiva de productos",
                detalle=f"Se marcaron como inactivos {count} producto(s) desde el panel.",
                user=request.user,
                extra={"cantidad": count, "ids": ids},
            )

        elif accion == "eliminar":
            count = qs.count()
            nombres = [p.nombre_publico or p.sku for p in qs]

            registrar_evento(
                tipo="producto_eliminado",
                titulo=f"Eliminación masiva de {count} producto(s)",
                detalle=", ".join(nombres[:10]) + (" ..." if len(nombres) > 10 else ""),
                user=request.user,
                extra={"cantidad": count, "ids": ids},
            )

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
    s = str(s).strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal(str(fallback))


def _parse_precio_desde_pdf(raw: str | None) -> Decimal:
    if raw is None:
        return Decimal("0")

    txt = str(raw).strip().upper()

    if txt in {"AGOTADO", "AGOTADA", "SIN STOCK", "S/STOCK", "SIN PRECIO", "-", ""}:
        return Decimal("0")

    s = txt.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


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

    original_data = {
        "sku": producto.sku,
        "nombre_publico": producto.nombre_publico,
        "descripcion": getattr(producto, "descripcion", ""),
        "precio": producto.precio,
        "stock": producto.stock,
        "tech": producto.tech,
        "activo": producto.activo,
        "rubro": producto.rubro,
        "subrubro": producto.subrubro,
    }

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "delete_image":
            if producto.imagen:
                producto.imagen.delete(save=False)
                producto.imagen = None
                producto.save(update_fields=["imagen"])

                registrar_evento(
                    tipo="producto_editado",
                    titulo=f"Imagen eliminada: {producto.nombre_publico or producto.sku}",
                    detalle="Se eliminó la imagen principal del producto.",
                    user=request.user,
                    obj=producto,
                    extra={
                        "cambios": {
                            "imagen": {"antes": "con_imagen", "despues": "sin_imagen"}
                        }
                    },
                )

            messages.success(request, "Imagen eliminada.")
            return redirect("owner_producto_editar", pk=producto.pk)

        if action == "toggle_active":
            old_activo = bool(producto.activo)
            producto.activo = not old_activo
            producto.save(update_fields=["activo"])

            registrar_evento(
                tipo="producto_editado",
                titulo=f"Producto {'activado' if producto.activo else 'desactivado'}: {producto.nombre_publico or producto.sku}",
                detalle=f"Campo activo: {old_activo} → {producto.activo}",
                user=request.user,
                obj=producto,
                extra={
                    "cambios": {
                        "activo": {"antes": old_activo, "despues": bool(producto.activo)}
                    }
                },
            )

            messages.success(request, "Estado actualizado.")
            return redirect("owner_producto_editar", pk=producto.pk)

        if action == "delete_product":
            nombre = producto.nombre_publico or producto.sku

            registrar_evento(
                tipo="producto_eliminado",
                titulo=f"Producto eliminado: {nombre}",
                detalle=f"Producto '{nombre}' eliminado desde el panel owner.",
                user=request.user,
                obj=producto,
                extra={"producto_id": producto.pk, "sku": producto.sku},
            )

            producto.delete()
            messages.success(request, "Producto eliminado.")
            return redirect("home")

        vformset = ProductoVarianteFormSet(
            request.POST,
            request.FILES,
            instance=producto,
            prefix="v",
        )

        producto.sku = (request.POST.get("sku") or producto.sku).strip()
        producto.nombre_publico = (request.POST.get("nombre_publico") or producto.nombre_publico).strip()
        producto.descripcion = (request.POST.get("descripcion") or "").strip()
        producto.precio = _parse_decimal(request.POST.get("precio"), fallback=str(producto.precio))
        producto.stock = int(request.POST.get("stock") or producto.stock or 0)
        producto.tech = request.POST.get("tech", "") or ""
        producto.activo = request.POST.get("activo") == "on"

        if request.FILES.get("imagen"):
            producto.imagen = request.FILES["imagen"]

        rubro_nombre = (request.POST.get("rubro_nombre") or "").strip()
        subrubro_nombre = (request.POST.get("subrubro_nombre") or "").strip()

        nombre_prod = (producto.nombre_publico or producto.sku or "").strip()
        tech = producto.tech or ""

        rubro_obj = None
        if not rubro_nombre:
            rubro_obj = _detectar_rubro_auto(nombre_prod, tech)
            if rubro_obj:
                rubro_nombre = rubro_obj.nombre
        else:
            rubro_obj = Rubro.objects.filter(
                nombre__iexact=rubro_nombre,
                activo=True
            ).first()

        producto.rubro = rubro_nombre
        producto.subrubro = subrubro_nombre

        if vformset.is_valid():
            with transaction.atomic():
                producto.save()
                vformset.save()

                # CAMBIO CLAVE:
                # si hay variantes activas, el stock del padre no se suma ni se usa
                if producto.variantes.filter(activo=True).exists():
                    if producto.stock != 0:
                        producto.stock = 0
                        producto.save(update_fields=["stock"])

            cambios = {}
            for field, old_val in original_data.items():
                new_val = getattr(producto, field)
                if new_val != old_val:
                    cambios[field] = {
                        "antes": str(old_val),
                        "despues": str(new_val),
                    }

            detalle_str = "Producto actualizado."
            if cambios:
                partes = []
                for field, diff in cambios.items():
                    partes.append(
                        f"{field}: '{diff['antes']}' → '{diff['despues']}'"
                    )
                detalle_str += " Cambios: " + "; ".join(partes)

            registrar_evento(
                tipo="producto_editado",
                titulo=f"Producto editado: {producto.nombre_publico or producto.sku}",
                detalle=detalle_str,
                user=request.user,
                obj=producto,
                extra={
                    "cambios": cambios,
                    "variantes_modificadas": vformset.has_changed(),
                },
            )

            messages.success(request, "Producto actualizado.")
            return redirect("owner_producto_editar", pk=producto.pk)
        else:
            messages.error(request, "Hay errores en las variantes. Revisá los campos resaltados.")

    else:
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

    registrar_evento(
        tipo="producto_editado",
        titulo=f"Producto {'activado' if producto.activo else 'desactivado'}: {producto.nombre_publico or producto.sku}",
        detalle="Cambio de estado desde acción rápida del panel.",
        user=request.user,
        obj=producto,
        extra={"activo": producto.activo},
    )

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

    registrar_evento(
        tipo="producto_eliminado",
        titulo=f"Producto eliminado definitivamente: {nombre}",
        detalle="El producto fue eliminado desde acción rápida del panel.",
        user=request.user,
        obj=producto,
        extra={"sku": producto.sku},
    )

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

        registrar_evento(
            tipo="producto_editado",
            titulo="Desactivación masiva (modo antiguo)",
            detalle=f"{count} producto(s) marcados como INACTIVOS desde acciones masivas antiguas.",
            user=request.user,
            extra={"cantidad": count, "ids": ids},
        )

    elif accion == "alta":
        count = qs.update(activo=True)
        messages.success(request, f"{count} producto(s) marcados como ACTIVOS.")

        registrar_evento(
            tipo="producto_editado",
            titulo="Activación masiva (modo antiguo)",
            detalle=f"{count} producto(s) marcados como ACTIVOS desde acciones masivas antiguas.",
            user=request.user,
            extra={"cantidad": count, "ids": ids},
        )

    elif accion == "eliminar":
        count = qs.count()
        nombres = [p.nombre_publico or p.sku for p in qs]

        registrar_evento(
            tipo="producto_eliminado",
            titulo=f"Eliminación masiva (modo antiguo) de {count} producto(s)",
            detalle=", ".join(nombres[:10]) + (" ..." if len(nombres) > 10 else ""),
            user=request.user,
            extra={"cantidad": count, "ids": ids},
        )

        qs.delete()
        messages.success(
            request,
            f"{count} producto(s) eliminados: {', '.join(nombres[:5])}"
            + (" ..." if len(nombres) > 5 else "")
        )
    else:
        messages.error(request, "Acción masiva no reconocida.")

    return redirect("home")


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


def _normalizar_palabras(texto: str) -> set[str]:
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
    nombre = getattr(obj_con_nombre, "nombre", "")
    tokens_rubro = _normalizar_palabras(nombre)
    if not tokens_rubro or not tokens_producto:
        return 0.0

    score = 0.0

    STOPWORDS = {"porta", "para", "de", "del", "la", "el", "y", "para", "con"}

    for tp in tokens_producto:
        tp = tp.lower().strip()
        if tp in STOPWORDS:
            continue

        for tr in tokens_rubro:
            tr = tr.lower().strip()
            if tr in STOPWORDS:
                continue

            if tp == tr:
                score += 1.0
            else:
                if len(tp) >= 4 and len(tr) >= 4:
                    sim = SequenceMatcher(None, tp, tr).ratio()
                    if sim >= 0.9:
                        score += sim

    tech_obj = ""
    if hasattr(obj_con_nombre, "tech"):
        tech_obj = obj_con_nombre.tech or ""
    elif hasattr(obj_con_nombre, "rubro") and obj_con_nombre.rubro:
        tech_obj = obj_con_nombre.rubro.tech or ""

    if tech_obj and tech_producto and tech_obj == tech_producto:
        score += 1.0

    return score


def _detectar_rubro_auto(nombre: str, tech: str):
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

        if form.is_valid() and vformset.is_valid():
            producto = form.save(commit=False)

            imagen_file = form.cleaned_data.get("imagen")

            if not (producto.nombre_publico or "").strip():
                producto.nombre_publico = producto.sku

            nombre = (producto.nombre_publico or producto.sku or "").strip()
            tech = producto.tech or ""

            rubro_nombre = (request.POST.get("rubro_nombre") or "").strip()
            subrubro_nombre = (request.POST.get("subrubro_nombre") or "").strip()

            rubro_obj = None
            if not rubro_nombre:
                rubro_obj = _detectar_rubro_auto(nombre, tech)
                if rubro_obj:
                    rubro_nombre = rubro_obj.nombre
            else:
                rubro_obj = Rubro.objects.filter(
                    nombre__iexact=rubro_nombre,
                    activo=True
                ).first()

            producto.rubro = rubro_nombre
            producto.subrubro = subrubro_nombre

            producto.imagen = None
            producto.save()

            if imagen_file:
                producto.imagen = imagen_file
                try:
                    producto.save(update_fields=["imagen"])
                except Exception as e:
                    messages.error(
                        request,
                        f"El producto se creó pero hubo un problema guardando la imagen: {e}"
                    )

            vformset.instance = producto
            vformset.save()

            # CAMBIO CLAVE:
            # si hay variantes activas, el stock del padre no se suma ni se usa
            variantes_activas = producto.variantes.filter(activo=True)
            if variantes_activas.exists() and producto.stock != 0:
                producto.stock = 0
                producto.save(update_fields=["stock"])

            registrar_evento(
                tipo="producto_creado",
                titulo=f"Producto creado: {producto.nombre_publico or producto.sku}",
                detalle="Artículo creado desde el panel.",
                user=request.user,
                obj=producto,
                extra={
                    "sku": producto.sku,
                    "precio": str(producto.precio),
                    "stock": producto.stock,
                    "rubro": producto.rubro,
                    "subrubro": producto.subrubro,
                },
            )

            messages.success(request, "Artículo creado correctamente.")
            return redirect("catalogo")
        else:
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


@login_required
def owner_productos_completar_desde_factura(request):
    if not _check_owner(request.user):
        raise PermissionDenied

    ids = request.session.get("productos_factura_creados_ids", [])
    if not ids:
        messages.warning(request, "No hay productos pendientes para completar desde factura.")
        return redirect("procesar_factura")

    productos = list(ProductoPrecio.objects.filter(pk__in=ids).order_by("id"))

    if not productos:
        request.session.pop("productos_factura_creados_ids", None)
        messages.warning(request, "No se encontraron los productos a completar.")
        return redirect("procesar_factura")

    rubros = Rubro.objects.filter(activo=True).order_by("tech", "orden", "nombre")
    subrubros = (
        SubRubro.objects
        .filter(activo=True)
        .select_related("rubro")
        .order_by("rubro__orden", "orden", "nombre")
    )

    form_rows = []

    if request.method == "POST":
        all_valid = True

        for producto in productos:
            prefix = f"prod_{producto.pk}"
            form = ProductoDesdeFacturaBulkForm(
                request.POST,
                request.FILES,
                instance=producto,
                prefix=prefix,
            )
            vprefix = f"vars_{producto.pk}"
            vformset = ProductoVarianteFormSet(
                request.POST,
                request.FILES,
                instance=producto,
                prefix=vprefix,
            )

            form_rows.append({
                "producto": producto,
                "form": form,
                "prefix": prefix,
                "vformset": vformset,
                "vprefix": vprefix,
            })

            if not form.is_valid() or not vformset.is_valid():
                all_valid = False

        if all_valid:
            with transaction.atomic():
                for row in form_rows:
                    producto = row["producto"]
                    form = row["form"]
                    prefix = row["prefix"]

                    original_data = {
                        "sku": producto.sku,
                        "nombre_publico": producto.nombre_publico,
                        "descripcion": getattr(producto, "descripcion", ""),
                        "precio": producto.precio,
                        "precio_costo": producto.precio_costo,
                        "stock": producto.stock,
                        "tech": producto.tech,
                        "activo": producto.activo,
                        "rubro": producto.rubro,
                        "subrubro": producto.subrubro,
                    }

                    producto_editado = form.save(commit=False)

                    rubro_nombre = (request.POST.get(f"{prefix}-rubro_nombre") or "").strip()
                    subrubro_nombre = (request.POST.get(f"{prefix}-subrubro_nombre") or "").strip()

                    nombre_prod = (producto_editado.nombre_publico or producto_editado.sku or "").strip()
                    tech = producto_editado.tech or ""

                    rubro_obj = None
                    if not rubro_nombre:
                        rubro_obj = _detectar_rubro_auto(nombre_prod, tech)
                        if rubro_obj:
                            rubro_nombre = rubro_obj.nombre
                    else:
                        rubro_obj = Rubro.objects.filter(
                            nombre__iexact=rubro_nombre,
                            activo=True,
                        ).first()

                    producto_editado.rubro = rubro_nombre
                    producto_editado.subrubro = subrubro_nombre

                    producto_editado.save()
                    row["vformset"].instance = producto_editado
                    row["vformset"].save()

                    # CAMBIO CLAVE:
                    # si hay variantes activas, el stock del padre no se suma ni se usa
                    if producto_editado.variantes.filter(activo=True).exists():
                        if producto_editado.stock != 0:
                            producto_editado.stock = 0
                            producto_editado.save(update_fields=["stock"])

                    cambios = {}
                    for field, old_val in original_data.items():
                        new_val = getattr(producto_editado, field)
                        if new_val != old_val:
                            cambios[field] = {
                                "antes": str(old_val),
                                "despues": str(new_val),
                            }

                    registrar_evento(
                        tipo="producto_editado",
                        titulo=f"Producto completado desde factura: {producto_editado.nombre_publico or producto_editado.sku}",
                        detalle="Carga masiva posterior a factura.",
                        user=request.user,
                        obj=producto_editado,
                        extra={
                            "cambios": cambios,
                            "origen": "factura_proveedor_bulk",
                        },
                    )

            request.session.pop("productos_factura_creados_ids", None)
            messages.success(request, "Productos actualizados correctamente.")
            return redirect("home")

        messages.error(request, "Hay errores en uno o más productos. Revisá los campos.")

    else:
        for producto in productos:
            prefix = f"prod_{producto.pk}"
            form = ProductoDesdeFacturaBulkForm(instance=producto, prefix=prefix)
            vprefix = f"vars_{producto.pk}"
            vformset = ProductoVarianteFormSet(instance=producto, prefix=vprefix)

            form_rows.append({
                "producto": producto,
                "form": form,
                "prefix": prefix,
                "vformset": vformset,
                "vprefix": vprefix,
            })

    return render(
        request,
        "owner/productos_completar_desde_factura.html",
        {
            "rows": form_rows,
            "rubros": rubros,
            "subrubros": subrubros,
        },
    )


@require_GET
def owner_api_product_suggest(request):
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"results": []})

    qs = (
        ProductoPrecio.objects
        .filter(Q(sku__icontains=q) | Q(nombre_publico__icontains=q))
        .order_by("nombre_publico")[:20]
    )

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


@login_required
def owner_siteinfo_list(request):
    if not _check_owner(request.user):
        raise PermissionDenied("Solo el dueño puede editar esta sección")

    site_cfg = SiteConfig.get_solo()

    info_qs = SiteInfoBlock.objects.filter(site=site_cfg).order_by("orden", "id")
    carousel_qs = SiteCarouselImage.objects.filter(site=site_cfg).order_by("orden", "id")

    INFO_PREFIX = "info_blocks"
    CAROUSEL_PREFIX = "carousel_images"

    if request.method == "POST":
        formset = SiteInfoBlockFormSet(
            request.POST,
            queryset=info_qs,
            prefix=INFO_PREFIX,
        )

        carousel_formset = SiteCarouselImageFormSet(
            request.POST,
            request.FILES,
            queryset=carousel_qs,
            prefix=CAROUSEL_PREFIX,
        )

        if formset.is_valid() and carousel_formset.is_valid():
            info_instances = formset.save(commit=False)
            for obj in info_instances:
                obj.site = site_cfg
                obj.save()

            for obj in formset.deleted_objects:
                obj.delete()

            carousel_instances = carousel_formset.save(commit=False)
            for obj in carousel_instances:
                obj.site = site_cfg
                obj.save()

            for obj in carousel_formset.deleted_objects:
                obj.delete()

            messages.success(request, "Información del sitio actualizada correctamente.")
            return redirect("owner_siteinfo_list")
        else:
            messages.error(request, "Revisá los errores del formulario.")
    else:
        formset = SiteInfoBlockFormSet(
            queryset=info_qs,
            prefix=INFO_PREFIX,
        )

        carousel_formset = SiteCarouselImageFormSet(
            queryset=carousel_qs,
            prefix=CAROUSEL_PREFIX,
        )

    return render(
        request,
        "owner/owner_info_sitio.html",
        {
            "formset": formset,
            "carousel_formset": carousel_formset,
            "site_cfg": site_cfg,
        },
    )


@login_required
def owner_filtros_panel(request):
    if not _check_owner(request.user):
        raise PermissionDenied

    TECH_CHOICES = [
        ("SUB", "Sublimación"),
        ("LAS", "Grabado láser"),
        ("3D", "Impresión 3D"),
        ("OTR", "Otros"),
    ]

    if request.method == "POST":
        if "add_rubro" in request.POST:
            nombre = (request.POST.get("nombre_rubro") or "").strip()
            tech = (request.POST.get("tech") or "").strip()

            if not nombre or not tech:
                messages.error(request, "Completá el nombre del rubro y la técnica.")
            else:
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

        if "add_subrubro" in request.POST:
            nombre = (request.POST.get("nombre_subrubro") or "").strip()
            rubro_id = request.POST.get("rubro_id")

            if not nombre or not rubro_id:
                messages.error(request, "Elegí un rubro y escribí el nombre del subfiltro.")
            else:
                rubro = get_object_or_404(Rubro, pk=rubro_id)

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

        if "delete_rubro" in request.POST:
            rubro_id = request.POST.get("rubro_id")
            rubro = get_object_or_404(Rubro, pk=rubro_id)
            nombre = rubro.nombre
            rubro.delete()
            messages.success(
                request,
                f"Rubro “{nombre}” y sus subfiltros asociados fueron eliminados."
            )
            return redirect("owner_filtros_panel")

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

    rubros_qs = (
        Rubro.objects
        .prefetch_related("subrubros")
        .order_by("tech", "orden", "nombre")
    )

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
    _check_owner_or_403(request.user)

    nombre = (request.POST.get("nombre") or "").strip()
    tech = (request.POST.get("tech") or "").strip()

    if not nombre:
        return JsonResponse(
            {"ok": False, "error": "El nombre del rubro es obligatorio."},
            status=400,
        )

    rubro, created = Rubro.objects.get_or_create(
        nombre=nombre,
        tech=tech or "",
        defaults={
            "orden": 0,
            "activo": True,
        },
    )

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

        best_sub = None
        best_sub_score = 0.0

        for s in subrubros:
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

            if rubro_actual == rubro_sug_nombre and subrubro_actual == sub_sug_nombre:
                continue

            sugerencias.append({
                "producto": p,
                "rubro": rubro_sug,
                "subrubro": best_sub,
                "score": round(best_sub_score, 2),
            })
            continue

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

            registrar_evento(
                tipo="rubros_asignados",
                titulo="Asignación automática de rubros/subrubros",
                detalle=f"Se actualizaron {aplicadas} producto(s) desde Autorubros.",
                user=request.user,
                extra={"cantidad": aplicadas},
            )
        else:
            messages.info(request, "No se aplicó ningún cambio (ningún producto marcado).")

        return redirect("owner_autorubros")

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


@login_required
def owner_siteconfig_edit(request):
    if not _check_owner(request.user):
        raise PermissionDenied

    cfg = SiteConfig.get_solo()
    if request.method == "POST":
        form = SiteConfigForm(request.POST, instance=cfg)
        if form.is_valid():
            cfg = form.save()
            messages.success(request, "Configuración guardada ✅")

            registrar_evento(
                tipo="siteconfig_edit",
                titulo="Personalización del sitio actualizada",
                detalle="Se modificaron colores, tipografías o textos globales de la tienda.",
                user=request.user,
                obj=cfg,
            )

            return redirect("owner_siteconfig_edit")
    else:
        form = SiteConfigForm(instance=cfg)

    return render(request, "owner/siteconfig_form.html", {"form": form})


@require_GET
@login_required
def owner_api_product_search_for_sale(request):
    if not _check_owner(request.user):
        raise PermissionDenied

    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})

    productos = (
        ProductoPrecio.objects
        .filter(activo=True)
        .filter(Q(nombre_publico__icontains=q) | Q(sku__icontains=q))
        .order_by("nombre_publico", "sku")[:20]
    )

    results = []
    for p in productos:
        variantes = list(
            p.variantes.filter(activo=True).values("id", "nombre", "stock", "precio")
        )

        results.append({
            "id": p.id,
            "sku": p.sku,
            "nombre_publico": p.nombre_publico,
            "precio": str(p.precio),
            "precio_costo": str(p.precio_costo or "0"),
            "stock": p.stock,
            "tiene_variantes": bool(variantes),
            "variantes": [
                {
                    "id": v["id"],
                    "nombre": v["nombre"],
                    "stock": v["stock"],
                    "precio": str(v["precio"]) if v["precio"] is not None else "",
                }
                for v in variantes
            ],
        })

    return JsonResponse({"results": results})


@login_required
def owner_historia_global(request):

    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para ver la bitácora.")

    tipo = (request.GET.get("tipo") or "").strip()
    usuario_id = (request.GET.get("usuario") or "").strip()
    q = (request.GET.get("q") or "").strip()
    desde = (request.GET.get("desde") or "").strip()
    hasta = (request.GET.get("hasta") or "").strip()

    eventos = BitacoraEvento.objects.all().select_related("usuario")

    if tipo:
        eventos = eventos.filter(tipo=tipo)

    if usuario_id:
        eventos = eventos.filter(usuario_id=usuario_id)

    if q:
        eventos = eventos.filter(
            Q(titulo__icontains=q) |
            Q(detalle__icontains=q) |
            Q(extra__icontains=q)
        )

    if desde:
        try:
            dt_desde = datetime.strptime(desde, "%Y-%m-%d")
            dt_desde = timezone.make_aware(dt_desde)
            eventos = eventos.filter(created_at__gte=dt_desde)
        except ValueError:
            pass

    if hasta:
        try:
            dt_hasta = datetime.strptime(hasta, "%Y-%m-%d")
            dt_hasta = timezone.make_aware(dt_hasta + timedelta(days=1))
            eventos = eventos.filter(created_at__lt=dt_hasta)
        except ValueError:
            pass

    eventos = eventos[:500]

    usuarios = User.objects.filter(bitacora_eventos__isnull=False).distinct()
    tipos = BitacoraEvento.TIPO_CHOICES

    return render(
        request,
        "owner/historia_global.html",
        {
            "eventos": eventos,
            "usuarios": usuarios,
            "tipos": tipos,
            "f_tipo": tipo,
            "f_usuario": usuario_id,
            "f_q": q,
            "f_desde": desde,
            "f_hasta": hasta,
        },
    )

@login_required
@login_required
def owner_venta_rapida_create(request):
    if not _check_owner(request.user):
        raise PermissionDenied

    if request.method == "POST":
        form = VentaRapidaForm(request.POST)

        if form.is_valid():
            with transaction.atomic():
                venta = form.save(commit=False)
                producto = venta.producto
                variante = venta.variante

                if variante:
                    stock_disponible = variante.stock or 0
                    costo_unitario = variante.precio if variante.precio is not None else (producto.precio_costo or Decimal("0.00"))
                else:
                    if producto.variantes.filter(activo=True).exists():
                        messages.error(
                            request,
                            "Este producto tiene variantes activas. Elegí una variante para registrar la venta."
                        )
                        return redirect("owner_venta_rapida_create")

                    stock_disponible = producto.stock or 0
                    costo_unitario = producto.precio_costo or Decimal("0.00")

                if stock_disponible < venta.cantidad:
                    messages.error(
                        request,
                        f"No hay stock suficiente. Stock actual: {stock_disponible}."
                    )
                    return redirect("owner_venta_rapida_create")

                venta.subtotal = venta.precio_unitario * venta.cantidad
                venta.costo_unitario = costo_unitario
                venta.usuario = request.user
                venta.save()

                if variante:
                    variante.stock = (variante.stock or 0) - venta.cantidad
                    variante.save(update_fields=["stock"])
                else:
                    producto.stock = (producto.stock or 0) - venta.cantidad
                    producto.save(update_fields=["stock"])

                nombre_log = producto.nombre_publico or producto.sku
                if variante:
                    nombre_log = f"{nombre_log} - {variante.nombre}"

                registrar_evento(
                    tipo="venta_registrada",
                    titulo=f"Venta registrada: {nombre_log}",
                    detalle=(
                        f"Se vendieron {venta.cantidad} unidad(es) a ${venta.precio_unitario} "
                        f"por un total de ${venta.subtotal}. Medio de pago: {venta.get_medio_pago_display()}."
                    ),
                    user=request.user,
                    obj=producto,
                    extra={
                        "venta_id": venta.id,
                        "producto_id": producto.id,
                        "variante_id": variante.id if variante else None,
                        "sku": producto.sku,
                        "cantidad": venta.cantidad,
                        "precio_unitario": str(venta.precio_unitario),
                        "subtotal": str(venta.subtotal),
                        "medio_pago": venta.medio_pago,
                    },
                )

                messages.success(request, "Venta registrada correctamente.")
                return redirect("owner_caja_resumen")
    else:
        form = VentaRapidaForm()

    ultimas_ventas = VentaRapida.objects.select_related("producto", "variante", "usuario")[:10]

    return render(
        request,
        "owner/venta_rapida_form.html",
        {
            "form": form,
            "ultimas_ventas": ultimas_ventas,
        },
    )

@login_required
@login_required
def owner_caja_resumen(request):
    if not _check_owner(request.user):
        raise PermissionDenied

    desde = (request.GET.get("desde") or "").strip()
    hasta = (request.GET.get("hasta") or "").strip()
    medio_pago = (request.GET.get("medio_pago") or "").strip()

    ventas = VentaRapida.objects.select_related("producto", "variante", "usuario").all()

    if desde:
        try:
            dt_desde = datetime.strptime(desde, "%Y-%m-%d")
            dt_desde = timezone.make_aware(dt_desde)
            ventas = ventas.filter(fecha__gte=dt_desde)
        except ValueError:
            pass

    if hasta:
        try:
            dt_hasta = datetime.strptime(hasta, "%Y-%m-%d") + timedelta(days=1)
            dt_hasta = timezone.make_aware(dt_hasta)
            ventas = ventas.filter(fecha__lt=dt_hasta)
        except ValueError:
            pass

    if medio_pago in {"efectivo", "transferencia"}:
        ventas = ventas.filter(medio_pago=medio_pago)

    hoy = timezone.localdate()
    inicio_hoy = timezone.make_aware(datetime.combine(hoy, datetime.min.time()))
    fin_hoy = inicio_hoy + timedelta(days=1)

    ventas_hoy = VentaRapida.objects.filter(fecha__gte=inicio_hoy, fecha__lt=fin_hoy)

    total_hoy = ventas_hoy.aggregate(total=Sum("subtotal"))["total"] or Decimal("0.00")
    cantidad_hoy = ventas_hoy.aggregate(total=Count("id"))["total"] or 0
    unidades_hoy = ventas_hoy.aggregate(total=Sum("cantidad"))["total"] or 0

    total_hoy_efectivo = ventas_hoy.filter(medio_pago="efectivo").aggregate(total=Sum("subtotal"))["total"] or Decimal("0.00")
    total_hoy_transferencia = ventas_hoy.filter(medio_pago="transferencia").aggregate(total=Sum("subtotal"))["total"] or Decimal("0.00")

    total_periodo = ventas.aggregate(total=Sum("subtotal"))["total"] or Decimal("0.00")
    cantidad_periodo = ventas.aggregate(total=Count("id"))["total"] or 0
    unidades_periodo = ventas.aggregate(total=Sum("cantidad"))["total"] or 0

    total_efectivo = ventas.filter(medio_pago="efectivo").aggregate(total=Sum("subtotal"))["total"] or Decimal("0.00")
    total_transferencia = ventas.filter(medio_pago="transferencia").aggregate(total=Sum("subtotal"))["total"] or Decimal("0.00")

    costo_expr = ExpressionWrapper(
        F("cantidad") * F("costo_unitario"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    costo_total_periodo = ventas.aggregate(total=Sum(costo_expr))["total"] or Decimal("0.00")
    ganancia_periodo = total_periodo - costo_total_periodo

    productos_mas_vendidos = (
        ventas.values("producto__id", "producto__nombre_publico", "producto__sku")
        .annotate(
            unidades=Sum("cantidad"),
            total_vendido=Sum("subtotal"),
        )
        .order_by("-unidades", "-total_vendido")[:10]
    )

    variantes_mas_vendidas = (
        ventas.filter(variante__isnull=False)
        .values("variante__id", "variante__nombre", "producto__nombre_publico", "producto__sku")
        .annotate(
            unidades=Sum("cantidad"),
            total_vendido=Sum("subtotal"),
        )
        .order_by("-unidades", "-total_vendido")[:10]
    )

    ventas_recientes = ventas.order_by("-fecha")[:100]

    return render(
        request,
        "owner/caja_resumen.html",
        {
            "ventas": ventas_recientes,
            "desde": desde,
            "hasta": hasta,
            "medio_pago": medio_pago,

            "total_hoy": total_hoy,
            "cantidad_hoy": cantidad_hoy,
            "unidades_hoy": unidades_hoy,
            "total_hoy_efectivo": total_hoy_efectivo,
            "total_hoy_transferencia": total_hoy_transferencia,

            "total_periodo": total_periodo,
            "cantidad_periodo": cantidad_periodo,
            "unidades_periodo": unidades_periodo,
            "total_efectivo": total_efectivo,
            "total_transferencia": total_transferencia,

            "costo_total_periodo": costo_total_periodo,
            "ganancia_periodo": ganancia_periodo,

            "productos_mas_vendidos": productos_mas_vendidos,
            "variantes_mas_vendidas": variantes_mas_vendidas,
        },
    )

@login_required
@require_POST
def owner_venta_rapida_delete(request, pk):
    if not _check_owner(request.user):
        raise PermissionDenied

    venta = get_object_or_404(
        VentaRapida.objects.select_related("producto", "variante"),
        pk=pk
    )
    producto = venta.producto
    variante = venta.variante

    with transaction.atomic():
        if variante:
            variante.stock = (variante.stock or 0) + venta.cantidad
            variante.save(update_fields=["stock"])
        else:
            producto.stock = (producto.stock or 0) + venta.cantidad
            producto.save(update_fields=["stock"])

        nombre_log = producto.nombre_publico or producto.sku
        if variante:
            nombre_log = f"{nombre_log} - {variante.nombre}"

        registrar_evento(
            tipo="venta_eliminada",
            titulo=f"Venta eliminada: {nombre_log}",
            detalle=(
                f"Se eliminó una venta de {venta.cantidad} unidad(es) por ${venta.subtotal}. "
                f"El stock fue restaurado."
            ),
            user=request.user,
            obj=producto,
            extra={
                "venta_id": venta.id,
                "producto_id": producto.id,
                "variante_id": variante.id if variante else None,
                "cantidad": venta.cantidad,
                "subtotal": str(venta.subtotal),
            },
        )

        venta.delete()

    messages.success(request, "Venta eliminada y stock restaurado.")
    return redirect("owner_caja_resumen")