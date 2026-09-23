import os
import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher
from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.forms import inlineformset_factory, modelformset_factory
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ofertas.utils import get_precio_con_oferta
from owner.forms import ProductoDesdeFacturaBulkForm, ProductoVarianteFormSet
from owner.models import BitacoraEvento, SiteCarouselImage, SiteConfig

from .forms import (
    FacturaForm,
    FacturaProveedorForm,
    ListaPrecioForm,
    ListaPreciosPDFForm,
)
from .models import (
    FacturaProveedor,
    ItemFactura,
    ListaPrecioPDF,
    PDFBranding,
    ProductoPrecio,
    ProductoVariante,
    Rubro,
    SubRubro,
)
from .utils import extraer_precios_de_pdf, get_similarity
from .utils_facturas import (
    extraer_texto_factura_simple,
    parse_invoice_pdf,
    parse_invoice_text,
)

Q2 = Decimal("0.01")


def _check_owner(user):
    return getattr(user, "is_owner", False) or getattr(user, "is_superuser", False)


def _check_owner_or_403(user):
    if not _check_owner(user):
        raise PermissionDenied


# ============================================================
# Helper bitácora
# ============================================================

def registrar_evento(tipo, titulo, detalle="", user=None, obj=None, extra=None):
    """
    Registra un evento en la bitácora global.
    - tipo: uno de BitacoraEvento.TIPO_CHOICES (ej: "producto_creado")
    - titulo: texto corto que se ve en la lista
    - detalle: texto más largo (opcional)
    - user: request.user o None
    - obj: algún modelo relacionado (ProductoPrecio, Pedido, etc.)
    - extra: dict con datos (ids, montos, etc.)
    """
    datos = extra.copy() if extra else {}

    obj_model = ""
    obj_id = ""
    if obj is not None:
        obj_model = obj._meta.label
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


# ============================================================
# STOCK
# ============================================================

def get_stock_disponible(producto, variante_id: int) -> int:
    """
    Devuelve el stock disponible real según variante o producto base.
    variante_id=0 => usa producto.stock
    variante_id!=0 => usa variante.stock
    """
    if int(variante_id) == 0:
        return max(0, int(getattr(producto, "stock", 0) or 0))

    variante = ProductoVariante.objects.filter(
        pk=variante_id,
        producto=producto,
        activo=True,
    ).first()

    if not variante:
        return 0

    return max(0, int(getattr(variante, "stock", 0) or 0))


# ============================================================
# CARRITO (helpers)
# ============================================================

def _get_cart(request):
    return request.session.get("carrito", {})


def _save_cart(request, cart):
    request.session["carrito"] = cart
    request.session.modified = True


def _make_key(prod_id: int, var_id: int | None):
    var_id = int(var_id or 0)
    return f"{int(prod_id)}:{var_id}"


# ============================================================
# BÚSQUEDA / SUGERENCIAS
# ============================================================

@require_GET
def catalogo_suggest(request):
    """
    Sugerencias para el buscador del navbar.
    Devuelve productos del catálogo (ProductoPrecio) con imagen y precio final.
    """
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"results": []})

    productos = (
        ProductoPrecio.objects
        .filter(activo=True)
        .filter(
            Q(nombre_publico__icontains=q) |
            Q(sku__icontains=q)
        )
        .order_by("nombre_publico")[:8]
    )

    results = []
    for p in productos:
        precio_info = get_precio_con_oferta(p)
        precio_final = precio_info.get("precio_final") or Decimal("0.00")

        imagen_url = ""
        if getattr(p, "imagen", None):
            try:
                imagen_url = p.imagen.url
            except Exception:
                imagen_url = ""

        results.append({
            "id": p.id,
            "nombre": p.nombre_publico,
            "precio": float(precio_final),
            "imagen_url": imagen_url,
            "url": reverse("detalle_producto", args=[p.id]),
        })

    return JsonResponse({"results": results})


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9áéíóúñü\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _score(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _normalizar_texto_factura(texto):
    if not texto:
        return ""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"\s+", " ", texto)
    return texto


@require_GET
def api_productos(request):
    q = (request.GET.get("q") or "").strip()

    qs = ProductoPrecio.objects.all()

    if q:
        qs = qs.filter(
            Q(nombre_publico__icontains=q) |
            Q(sku__icontains=q)
        )

    qs = qs.order_by("nombre_publico")[:20]

    data = []
    for p in qs:
        data.append({
            "id": p.id,
            "nombre": p.nombre_publico,
            "sku": p.sku,
            "precio": str((p.precio or Decimal("0.00")).quantize(Q2)),
            "precio_costo": str((p.precio_costo or Decimal("0.00")).quantize(Q2)),
        })

    return JsonResponse({"results": data})


def sugerencias_para(nombre_item: str, productos, top=2):
    """
    productos: lista de dicts con id, sku, nombre_publico, precio, precio_costo
    devuelve sugerencias ordenadas por score descendente
    """
    nombre_item_norm = _norm(nombre_item)
    scored = []

    for p in productos:
        pid = p["id"]
        sku = (p.get("sku") or "").strip()
        nom = (p.get("nombre_publico") or "").strip()
        precio = p.get("precio")
        precio_costo = p.get("precio_costo")

        score_nombre = _score(nombre_item_norm, nom)
        score_sku = _score(nombre_item_norm, sku)

        bonus = 0
        nom_norm = _norm(nom)
        sku_norm = _norm(sku)

        if nombre_item_norm and nombre_item_norm in nom_norm:
            bonus += 0.12
        if nombre_item_norm and nombre_item_norm in sku_norm:
            bonus += 0.08

        palabras_item = set(nombre_item_norm.split())
        palabras_nom = set(nom_norm.split())
        comunes = len(palabras_item & palabras_nom)
        bonus += min(comunes * 0.03, 0.12)

        score_final = max(score_nombre, score_sku) + bonus

        scored.append({
            "score": round(score_final * 100, 1),
            "id": pid,
            "sku": sku,
            "nombre": nom,
            "precio": str(precio) if precio is not None else "0.00",
            "precio_costo": str(precio_costo) if precio_costo is not None else "0.00",
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top]


def _to_decimal(v, default="0"):
    try:
        s = str(v).strip().replace(",", ".")
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _slug_sku_base(texto: str) -> str:
    texto = (texto or "").strip().lower()
    texto = texto.replace("ñ", "n")
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    texto = re.sub(r"_+", "_", texto).strip("_")
    return texto[:60] or "producto_pdf"


def _sku_unico(base: str) -> str:
    sku = base
    n = 2
    while ProductoPrecio.objects.filter(sku__iexact=sku).exists():
        sufijo = f"_{n}"
        sku = f"{base[:60-len(sufijo)]}{sufijo}"
        n += 1
    return sku


# ============================================================
# CATÁLOGO / LISTAS
# ============================================================

def _build_filtros_menu():
    techs = [
        ("LAS", "Grabado láser"),
        ("SUB", "Sublimación"),
        ("3D",  "Impresión 3D"),
        ("OTR", "Otro"),
    ]

    filtros = []

    for tech_key, tech_label in techs:
        base = ProductoPrecio.objects.filter(activo=True, tech=tech_key)
        rubros_data = []

        rubros = Rubro.objects.filter(
            tech=tech_key,
            activo=True,
        ).order_by("orden", "nombre")

        for rubro in rubros:
            qs_r = base.filter(rubro__iexact=rubro.nombre)
            subs_data = []
            for sub in rubro.subrubros.filter(activo=True).order_by("orden", "nombre"):
                qs_sub = qs_r.filter(subrubro__iexact=sub.nombre)
                subs_data.append({
                    "key": sub.nombre,
                    "label": sub.nombre,
                    "count": qs_sub.count(),
                })

            rubros_data.append({
                "key": rubro.nombre,
                "label": rubro.nombre,
                "count": qs_r.count(),
                "subrubros": subs_data,
            })

        filtros.append({
            "key": tech_key,
            "label": tech_label,
            "rubros": rubros_data,
        })

    return filtros


def mostrar_precios(request):
    q = (request.GET.get("q", "") or "").strip()
    tech_filter = (request.GET.get("tech") or "").strip()
    rubro_filter = (request.GET.get("rubro") or "").strip()
    subrubro_filter = (request.GET.get("subrubro") or "").strip()
    producto_id = (request.GET.get("prod") or "").strip()
    per_page_raw = (request.GET.get("per_page") or "28").strip()

    try:
        per_page = int(per_page_raw)
    except ValueError:
        per_page = 20

    if per_page not in (20, 28):
        per_page = 20

    productos_qs = (
        ProductoPrecio.objects
        .filter(activo=True)
        .prefetch_related("variantes")
    )

    if q:
        productos_qs = productos_qs.filter(
            Q(nombre_publico__icontains=q) |
            Q(sku__icontains=q)
        )

    if tech_filter:
        productos_qs = productos_qs.filter(tech=tech_filter)

    if rubro_filter:
        productos_qs = productos_qs.filter(rubro__iexact=rubro_filter)

    if subrubro_filter:
        productos_qs = productos_qs.filter(subrubro__iexact=subrubro_filter)

    if producto_id:
        try:
            productos_qs = productos_qs.filter(pk=int(producto_id))
        except ValueError:
            pass

    productos_lista = []
    for producto in productos_qs:
        precio_data = get_precio_con_oferta(producto)
        stock_principal = get_stock_disponible(producto, 0)

        variantes_activas = [v for v in producto.variantes.all() if v.activo]

        if variantes_activas:
            stock_total_variantes = sum(v.stock for v in variantes_activas)
            sin_stock = stock_total_variantes <= 0
        else:
            sin_stock = stock_principal <= 0

        productos_lista.append({
            "producto": producto,
            "precio_original": producto.precio,
            "precio_final": precio_data["precio_final"],
            "oferta": precio_data["oferta"],
            "sin_stock": sin_stock,
            "stock_principal": stock_principal,
        })

    productos_lista.sort(
        key=lambda x: (
            x["sin_stock"],
            x["producto"].nombre_publico.lower(),
        )
    )

    paginator = Paginator(productos_lista, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    tech_cards = [
        {"value": "", "label": "Todos", "icon": "fa-solid fa-border-all"},
        {"value": "LAS", "label": "Grabado láser", "icon": "fa-solid fa-fire"},
        {"value": "3D", "label": "Impresión 3D", "icon": "fa-solid fa-cube"},
        {"value": "SUB", "label": "Sublimación", "icon": "fa-solid fa-mug-hot"},
        {"value": "OTR", "label": "Otros", "icon": "fa-solid fa-shapes"},
    ]

    context = {
        "productos": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "is_paginated": page_obj.has_other_pages(),
        "per_page": per_page,
        "tech_cards": tech_cards,
        "filtros_menu": _build_filtros_menu(),
        "q": q,
        "tech_actual": tech_filter,
        "rubro_actual": rubro_filter,
        "subrubro_actual": subrubro_filter,
    }

    return render(
        request,
        "pdf/catalogo.html",
        context,
    )


# ============================================================
# DETALLE PRODUCTO + VARIANTES
# ============================================================

def detalle_producto(request, pk):
    producto = get_object_or_404(ProductoPrecio, pk=pk, activo=True)

    site_cfg = SiteConfig.get_solo()
    google_fotos = SiteCarouselImage.objects.filter(
        site=site_cfg,
        activo=True,
    ).order_by("orden", "id")

    precio_data = get_precio_con_oferta(producto)
    precio_principal = precio_data["precio_final"]

    stock_principal = get_stock_disponible(producto, 0)

    variante_principal = {
        "id": 0,
        "nombre": "Principal",
        "imagen": producto.imagen,
        "descripcion_corta": producto.nombre_publico,
        "es_principal": True,
        "stock": stock_principal,
        "precio_final": precio_principal,
    }

    variantes_ui = [variante_principal]
    variantes_qs = producto.variantes.filter(activo=True).order_by("orden", "id")

    for v in variantes_qs:
        precio_var = getattr(v, "precio", None)
        precio_final = precio_principal if precio_var is None else precio_var

        variantes_ui.append({
            "id": v.id,
            "nombre": v.nombre,
            "imagen": v.imagen,
            "descripcion_corta": v.descripcion_corta,
            "es_principal": False,
            "stock": max(0, int(getattr(v, "stock", 0) or 0)),
            "precio_final": precio_final,
        })

    stock_inicial = variantes_ui[0]["stock"]
    precio_inicial = variantes_ui[0]["precio_final"]

    return render(
        request,
        "pdf/detalle_producto.html",
        {
            "producto": producto,
            "variantes_ui": variantes_ui,
            "stock_inicial": stock_inicial,
            "precio_inicial": precio_inicial,
            "oferta": precio_data["oferta"],
            "site_cfg": site_cfg,
            "google_fotos": google_fotos,
        },
    )


# ============================================================
# API CAMBIO DE VARIANTE
# ============================================================

@require_GET
def api_stock_variante(request, pk):
    producto = get_object_or_404(ProductoPrecio, pk=pk, activo=True)
    var_id = request.GET.get("variante_id", "0")
    try:
        var_id = int(var_id)
    except ValueError:
        var_id = 0

    if var_id:
        ok = ProductoVariante.objects.filter(
            pk=var_id,
            producto=producto,
            activo=True,
        ).exists()
        if not ok:
            var_id = 0

    stock = get_stock_disponible(producto, var_id)
    return JsonResponse({"stock": stock})


# ============================================================
# CARRITO (AGREGAR)
# ============================================================

@require_POST
def agregar_al_carrito(request, pk):
    producto = get_object_or_404(ProductoPrecio, pk=pk, activo=True)

    variantes_activas = producto.variantes.filter(activo=True)
    tiene_variantes = variantes_activas.exists()

    variante_id_raw = request.POST.get("variante_id", "").strip()
    try:
        variante_id = int(variante_id_raw) if variante_id_raw else 0
    except (ValueError, TypeError):
        variante_id = 0

    variante = None

    if tiene_variantes:
        if not variante_id:
            messages.error(request, "Tenés que elegir una variante antes de agregar al carrito.")
            return redirect("detalle_producto", pk=pk)

        variante = variantes_activas.filter(pk=variante_id).first()
        if not variante:
            messages.error(request, "La variante seleccionada no es válida.")
            return redirect("detalle_producto", pk=pk)
    else:
        variante_id = 0

    try:
        cantidad = int(request.POST.get("cantidad", 1))
    except (ValueError, TypeError):
        cantidad = 1

    if cantidad < 1:
        cantidad = 1

    stock_disp = get_stock_disponible(producto, variante_id)

    if stock_disp <= 0:
        if tiene_variantes and variante is not None:
            messages.error(request, f"La variante '{variante.nombre}' no tiene stock.")
        else:
            messages.error(request, "Este producto no tiene stock.")
        return redirect("detalle_producto", pk=pk)

    if cantidad > stock_disp:
        cantidad = stock_disp
        messages.warning(request, f"Solo hay {stock_disp} unidades disponibles.")

    cart = _get_cart(request)
    key = _make_key(producto.id, variante_id)

    cart[key] = min(stock_disp, cart.get(key, 0) + cantidad)
    _save_cart(request, cart)

    if tiene_variantes and variante is not None:
        detalle_evento = f"{producto.nombre_publico or producto.sku} - {variante.nombre} x{cantidad}"
    else:
        detalle_evento = f"{producto.nombre_publico or producto.sku} x{cantidad}"

    registrar_evento(
        tipo="carrito_agregar",
        titulo="Producto agregado al carrito",
        detalle=detalle_evento,
        user=getattr(request, "user", None),
        obj=producto,
        extra={
            "producto_id": producto.id,
            "variante_id": variante_id,
            "cantidad": cantidad,
            "en_carrito": cart[key],
        },
    )

    if tiene_variantes and variante is not None:
        messages.success(request, f"Agregaste {producto.nombre_publico or producto.sku} - {variante.nombre} al carrito.")
    else:
        messages.success(request, "Producto agregado al carrito.")

    return redirect("detalle_producto", pk=pk)


# ============================================================
# UTIL: verificar SKU existente (para input editable)
# ============================================================

def verificar_producto_existente(request):
    nombre = request.GET.get("nombre", "").strip()
    if not nombre:
        return JsonResponse({"existe": False})

    producto = ProductoPrecio.objects.filter(sku=nombre).first()
    if producto:
        return JsonResponse({
            "existe": True,
            "id": producto.id,
            "nombre": producto.nombre_publico,
            "precio_actual": producto.precio,
        })
    return JsonResponse({"existe": False})


# ============================================================
# HELPERS PARA PDF LISTA DE PRECIOS
# ============================================================

def _safe_img(img_field, max_w_cm=1.7, max_h_cm=1.7):
    if not img_field:
        return ""

    try:
        path = img_field.path
        if not os.path.exists(path):
            return ""
        img = Image(path, width=max_w_cm * cm, height=max_h_cm * cm)
        img.hAlign = "CENTER"
        return img
    except Exception:
        return ""


class TechHeaderDoc(SimpleDocTemplate):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_tech = ""

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and getattr(flowable.style, "name", "") == "Heading1":
            txt = flowable.getPlainText().strip()
            if txt:
                self.current_tech = txt


def _tech_label(tech: str) -> str:
    return {
        "SUB": "Sublimación",
        "LAS": "Grabado láser",
        "3D":  "Impresión 3D",
        "OTR": "Otros",
        "":    "Otros",
        None:  "Otros",
    }.get(tech, "Otros")


# ============================================================
# IMPORTAR LISTA DE PRECIOS (PDF)
# ============================================================

@login_required
def importar_pdf(request):
    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para hacer esto.")

    report = {
        "imported": 0,
        "updated": 0,
        "skipped": 0,
        "usd_to_review": [],
        "not_found": [],
        "not_seen_active": [],
        "imported_items": [],
        "updated_items": [],
        "skipped_items": [],
        "parse_errors": [],
    }
    msg = ""
    update_only = request.POST.get("update_only") in ("on", "true", "1")

    if request.method == "POST" and request.POST.get("confirm"):
        productos_a_revisar = request.session.pop("productos_a_revisar", [])
        lista_pdf_id = request.session.pop("lista_pdf_id", None)

        if not lista_pdf_id:
            msg = "Error: sesión expirada. Volvé a subir el PDF."
            listas_procesadas = ListaPrecioPDF.objects.all().order_by("-fecha_subida")[:5]
            return render(
                request,
                "pdf/importar_pdf.html",
                {
                    "msg": msg,
                    "report": report,
                    "preview": False,
                    "update_only": False,
                    "listas_procesadas": listas_procesadas,
                },
            )

        lista_pdf = get_object_or_404(ListaPrecioPDF, pk=lista_pdf_id)

        skus_vistos_pdf = []
        productos_pdf_creados_ids = []

        with transaction.atomic():
            for index, producto in enumerate(productos_a_revisar):
                action_key = f"action_{index}"
                accion_valor = (request.POST.get(action_key) or "").strip()

                name_key = f"name_{index}"
                nombre_final = request.POST.get(name_key, producto["sku_original"]).strip()

                if not nombre_final:
                    report["skipped"] += 1
                    report["skipped_items"].append({
                        "reason": "Nombre vacío",
                        "sku": producto["sku_original"],
                    })
                    continue

                skus_vistos_pdf.append(nombre_final)

                if not accion_valor:
                    accion = "ignore"
                    target_id = None
                else:
                    parts = accion_valor.split(":", 1)
                    accion = parts[0]
                    target_id = parts[1] if len(parts) > 1 else None

                precio_nuevo = Decimal(producto["precio_nuevo"])
                moneda = producto.get("moneda", "ARS")

                producto_existente_db = None

                if target_id:
                    try:
                        producto_existente_db = ProductoPrecio.objects.get(pk=target_id)
                    except ProductoPrecio.DoesNotExist:
                        producto_existente_db = None

                if not producto_existente_db:
                    producto_existente_db = ProductoPrecio.objects.filter(
                        Q(sku__iexact=nombre_final) |
                        Q(nombre_publico__iexact=nombre_final)
                    ).first()

                item_reporte = {
                    "sku": nombre_final,
                    "currency": moneda,
                    "price": f"{precio_nuevo:.2f}",
                }

                if moneda == "USD":
                    report["usd_to_review"].append({
                        "sku": nombre_final,
                        "price": f"{precio_nuevo:.2f}",
                    })

                if accion == "ignore":
                    report["skipped"] += 1
                    report["skipped_items"].append({
                        "reason": "Ignorado por usuario",
                        "sku": nombre_final,
                    })
                    continue

                if update_only and not producto_existente_db:
                    report["skipped"] += 1
                    report["not_found"].append(nombre_final)
                    report["skipped_items"].append({
                        "reason": "update_only_sin_existente",
                        "sku": nombre_final,
                    })
                    continue

                if producto_existente_db:
                    prev_price = producto_existente_db.precio
                    changed = (prev_price != precio_nuevo)

                    if changed:
                        producto_existente_db.precio = precio_nuevo
                        producto_existente_db.lista_pdf = lista_pdf
                        producto_existente_db.save(update_fields=["precio", "lista_pdf"])

                        report["updated"] += 1
                        item_reporte.update({
                            "prev_price": f"{prev_price:.2f}",
                            "changed": True,
                            "note": "Precio actualizado",
                        })
                        report["updated_items"].append(item_reporte)
                    else:
                        report["skipped"] += 1
                        report["skipped_items"].append({
                            "reason": "Precio sin cambios",
                            "sku": nombre_final,
                        })

                    continue

                base_sku = _slug_sku_base(nombre_final)
                sku_nuevo = _sku_unico(base_sku)

                try:
                    nuevo = ProductoPrecio.objects.create(
                        lista_pdf=lista_pdf,
                        sku=sku_nuevo,
                        nombre_publico=nombre_final,
                        precio=precio_nuevo,
                        precio_costo=precio_nuevo,
                        descripcion=f"Importado desde PDF: {nombre_final}",
                        stock=0,
                        activo=False,
                    )
                except IntegrityError:
                    report["skipped"] += 1
                    report["skipped_items"].append({
                        "reason": "Error: no se pudo crear el producto",
                        "sku": nombre_final,
                    })
                    continue

                productos_pdf_creados_ids.append(nuevo.id)
                report["imported"] += 1
                item_reporte.update({
                    "sku_temporal": sku_nuevo,
                    "note": "Producto borrador creado para completar",
                })
                report["imported_items"].append(item_reporte)

        todos_skus = list(
            ProductoPrecio.objects
            .exclude(sku__isnull=True)
            .exclude(sku__exact="")
            .values_list("sku", flat=True)
        )
        skus_vistos_pdf = set(skus_vistos_pdf)
        report["not_seen_active"] = [
            s for s in todos_skus if s not in skus_vistos_pdf
        ][:200]

        msg = (
            f"PROCESO OK — borradores creados {report['imported']}, "
            f"actualizados {report['updated']}, omitidos {report['skipped']}, "
            f"no encontrados (update_only) {len(report['not_found'])}, "
            f"activos no vistos {len(report['not_seen_active'])}."
        )

        registrar_evento(
            tipo="lista_precio_importada",
            titulo=f"Lista de precios procesada: {lista_pdf.nombre}",
            detalle=msg,
            user=getattr(request, "user", None),
            obj=lista_pdf,
            extra={
                "lista_id": lista_pdf.id,
                "imported": report["imported"],
                "updated": report["updated"],
                "skipped": report["skipped"],
                "not_found": len(report["not_found"]),
                "not_seen_active": len(report["not_seen_active"]),
                "usd_to_review": len(report["usd_to_review"]),
                "productos_pdf_creados_ids": productos_pdf_creados_ids,
            },
        )

        if productos_pdf_creados_ids:
            request.session["productos_pdf_creados_ids"] = productos_pdf_creados_ids
            messages.success(
                request,
                "Se generaron productos borrador. Ahora completá sus datos.",
            )
            return redirect("owner_productos_completar_desde_pdf")

        return render(
            request,
            "pdf/importar_pdf.html",
            {
                "msg": msg,
                "report": report,
                "preview": False,
                "update_only": update_only,
            },
        )

    if request.method == "POST" and request.FILES.get("file"):
        archivo_pdf = request.FILES["file"]

        lista_pdf = ListaPrecioPDF.objects.create(
            nombre=archivo_pdf.name,
            archivo_pdf=archivo_pdf,
        )
        pdf_path = os.path.join(settings.MEDIA_ROOT, lista_pdf.archivo_pdf.name)

        registrar_evento(
            tipo="lista_precio_subida",
            titulo=f"Lista de precios subida: {lista_pdf.nombre}",
            detalle=f"Archivo: {lista_pdf.archivo_pdf.name}",
            user=getattr(request, "user", None),
            obj=lista_pdf,
            extra={
                "lista_id": lista_pdf.id,
                "archivo": lista_pdf.archivo_pdf.name,
                "update_only": update_only,
            },
        )

        productos_extraidos, parse_errors = extraer_precios_de_pdf(pdf_path)

        candidates = []
        productos_existentes = list(ProductoPrecio.objects.all())
        productos_a_revisar = []
        contador_nombres = {}

        skus_existentes = {}
        nombres_existentes = {}

        for p in productos_existentes:
            if p.sku:
                skus_existentes[p.sku.strip().lower()] = p
            if p.nombre_publico:
                nombres_existentes[p.nombre_publico.strip().lower()] = p

        for item in productos_extraidos:
            sku_original = item["nombre"]
            precio_nuevo = item["precio"]
            moneda = item.get("moneda", "ARS")

            if moneda == "USD":
                report["usd_to_review"].append({
                    "sku": sku_original,
                    "price": str(precio_nuevo),
                    "page": item.get("page"),
                })

            contador_nombres[sku_original] = contador_nombres.get(sku_original, 0) + 1
            clave_pdf = sku_original.strip().lower()

            exact_match = (
                skus_existentes.get(clave_pdf)
                or nombres_existentes.get(clave_pdf)
            )

            sug_match = None
            max_similitud = 0

            if not exact_match:
                for existing_product in productos_existentes:
                    base_comparacion = existing_product.nombre_publico or existing_product.sku or ""
                    similitud = get_similarity(sku_original, base_comparacion)
                    if similitud > max_similitud and similitud >= 70:
                        max_similitud = similitud
                        sug_match = existing_product

            c = {
                "name": sku_original,
                "price": precio_nuevo,
                "currency": moneda,
                "dup_in_pdf": False,
                "exact_db_id": exact_match.id if exact_match else None,
                "exact_db_label": exact_match.nombre_publico if exact_match else None,
                "sug_id": sug_match.id if sug_match else None,
                "sug_label": sug_match.nombre_publico if sug_match else None,
                "sug_score": max_similitud,
            }
            candidates.append(c)

            productos_a_revisar.append({
                "sku_original": sku_original,
                "precio_nuevo": str(precio_nuevo),
                "moneda": moneda,
                "coincidencia_id": c["exact_db_id"] or c["sug_id"],
            })

        for c in candidates:
            c["dup_in_pdf"] = contador_nombres.get(c["name"], 0) > 1

        request.session["productos_a_revisar"] = productos_a_revisar
        request.session["lista_pdf_id"] = lista_pdf.id

        report["parse_errors"] = parse_errors

        return render(
            request,
            "pdf/importar_pdf.html",
            {
                "preview": True,
                "candidates": candidates,
                "update_only": update_only,
                "report": report,
                "msg": msg,
            },
        )

    listas_procesadas = ListaPrecioPDF.objects.all().order_by("-fecha_subida")[:5]
    return render(
        request,
        "pdf/importar_pdf.html",
        {
            "msg": msg,
            "report": report,
            "preview": False,
            "update_only": False,
            "listas_procesadas": listas_procesadas,
        },
    )


@login_required
def owner_productos_completar_desde_pdf(request):
    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para hacer esto.")
    ids = request.session.get("productos_pdf_creados_ids", [])

    if not ids:
        messages.info(request, "No hay productos creados desde PDF para completar.")
        return redirect("importar_pdf")

    productos = list(
        ProductoPrecio.objects.filter(pk__in=ids).order_by("id")
    )

    if not productos:
        request.session.pop("productos_pdf_creados_ids", None)
        messages.info(request, "No se encontraron productos pendientes.")
        return redirect("importar_pdf")

    rubros = Rubro.objects.filter(activo=True).order_by("tech", "orden", "nombre")
    subrubros = SubRubro.objects.filter(activo=True).select_related("rubro").order_by(
        "rubro__nombre", "orden", "nombre"
    )

    rows = []
    todo_ok = True

    if request.method == "POST":
        for producto in productos:
            prefix = f"prod_{producto.id}"
            vprefix = f"vars_{producto.id}"

            form = ProductoDesdeFacturaBulkForm(
                request.POST,
                request.FILES,
                instance=producto,
                prefix=prefix,
            )

            vformset = ProductoVarianteFormSet(
                request.POST,
                request.FILES,
                instance=producto,
                prefix=vprefix,
            )

            rubro_nombre = (request.POST.get(f"{prefix}-rubro_nombre") or "").strip()
            subrubro_nombre = (request.POST.get(f"{prefix}-subrubro_nombre") or "").strip()

            if form.is_valid() and vformset.is_valid():
                obj = form.save(commit=False)
                obj.rubro = rubro_nombre
                obj.subrubro = subrubro_nombre

                if not obj.nombre_publico or not obj.sku:
                    obj.activo = False

                obj.save()
                vformset.save()

                registrar_evento(
                    tipo="producto_actualizado",
                    titulo=f"Producto completado desde PDF: {obj.nombre_publico or obj.sku}",
                    detalle=f"SKU: {obj.sku}",
                    user=getattr(request, "user", None),
                    obj=obj,
                    extra={
                        "producto_id": obj.id,
                        "origen": "importar_pdf",
                    },
                )
            else:
                todo_ok = False

            rows.append({
                "producto": producto,
                "form": form,
                "vformset": vformset,
                "prefix": prefix,
                "vprefix": vprefix,
            })

        if todo_ok:
            request.session.pop("productos_pdf_creados_ids", None)
            messages.success(request, "Se guardaron todos los productos creados desde PDF.")
            return redirect("importar_pdf")

    else:
        for producto in productos:
            prefix = f"prod_{producto.id}"
            vprefix = f"vars_{producto.id}"

            form = ProductoDesdeFacturaBulkForm(
                instance=producto,
                prefix=prefix,
            )

            vformset = ProductoVarianteFormSet(
                instance=producto,
                prefix=vprefix,
            )

            rows.append({
                "producto": producto,
                "form": form,
                "vformset": vformset,
                "prefix": prefix,
                "vprefix": vprefix,
            })

    return render(
        request,
        "owner/productos_completar_desde_pdf.html",
        {
            "rows": rows,
            "rubros": rubros,
            "subrubros": subrubros,
        },
    )


# ============================================================
# FACTURAS PROVEEDOR (OCR + linkeo a catálogo)
# ============================================================

@login_required
def procesar_factura(request):
    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para hacer esto.")

    if request.method == "POST" and "confirmar_factura" in request.POST:
        factura_id = request.session.get("factura_id")
        items_sesion = request.session.get("items_factura", [])

        if not factura_id:
            messages.error(request, "Sesión expirada. Volvé a cargar la factura.")
            return redirect("procesar_factura")

        factura = get_object_or_404(FacturaProveedor, pk=factura_id)

        fecha_str = request.POST.get("fecha_factura")
        if fecha_str:
            try:
                factura.fecha_factura = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                factura.save(update_fields=["fecha_factura"])
            except Exception:
                pass

        items_creados = 0
        productos_creados = 0
        productos_stock_actualizado = 0
        productos_costo_actualizado = 0
        productos_creados_ids = []

        with transaction.atomic():
            for index, item in enumerate(items_sesion):
                if f"item_{index}_check" not in request.POST:
                    continue

                producto_txt = _normalizar_texto_factura(
                    request.POST.get(f"item_{index}_producto", item["producto"])
                )

                cantidad = _to_decimal(
                    request.POST.get(f"item_{index}_cantidad", item["cantidad"]), "1"
                )

                precio = _to_decimal(
                    request.POST.get(f"item_{index}_precio", item["precio_unitario"]), "0"
                )

                subtotal = cantidad * precio

                ItemFactura.objects.create(
                    factura=factura,
                    producto=producto_txt,
                    cantidad=cantidad,
                    precio_unitario=precio,
                    subtotal=subtotal,
                )
                items_creados += 1

                sku_input = _normalizar_texto_factura(
                    request.POST.get(f"item_{index}_catalogo_sku") or ""
                ).replace(" ", "_").replace("/", "_").replace("-", "_")

                crear = f"item_{index}_crear_si_no_existe" in request.POST
                upd_stock = f"item_{index}_upd_stock" in request.POST
                upd_precio = f"item_{index}_upd_precio" in request.POST

                if sku_input:
                    sku = sku_input[:50]
                elif crear:
                    sku = (
                        producto_txt
                        .replace(" ", "_")
                        .replace("/", "_")
                        .replace("-", "_")[:50]
                    )
                else:
                    continue

                producto = ProductoPrecio.objects.filter(sku__iexact=sku).first()

                if not producto and crear:
                    producto = ProductoPrecio.objects.create(
                        sku=sku,
                        nombre_publico=producto_txt or sku,
                        precio=precio,
                        precio_costo=precio,
                        stock=0,
                        activo=False,
                    )
                    productos_creados += 1
                    productos_creados_ids.append(producto.id)

                if not producto:
                    continue

                if upd_stock:
                    ProductoPrecio.objects.filter(pk=producto.pk).update(
                        stock=F("stock") + int(cantidad)
                    )
                    productos_stock_actualizado += 1

                if upd_precio:
                    producto.precio_costo = precio
                    producto.save(update_fields=["precio_costo"])
                    productos_costo_actualizado += 1

        request.session.pop("factura_id", None)
        request.session.pop("items_factura", None)

        registrar_evento(
            tipo="factura_proveedor_confirmada",
            titulo=f"Factura de proveedor procesada (ID {factura.pk})",
            detalle=(
                f"Items: {items_creados}, productos creados: {productos_creados}, "
                f"stock actualizado: {productos_stock_actualizado}, "
                f"costo actualizado: {productos_costo_actualizado}."
            ),
            user=getattr(request, "user", None),
            obj=factura,
            extra={
                "factura_id": factura.pk,
                "items_creados": items_creados,
                "productos_creados": productos_creados,
                "productos_stock_actualizado": productos_stock_actualizado,
                "productos_costo_actualizado": productos_costo_actualizado,
            },
        )

        if productos_creados_ids:
            request.session["productos_factura_creados_ids"] = productos_creados_ids
            messages.success(
                request,
                "Factura guardada. Ahora completá los datos de los productos creados.",
            )
            return redirect("owner_productos_completar_desde_factura")

        messages.success(
            request,
            "Factura guardada y artículos procesados correctamente.",
        )
        return redirect("procesar_factura")

    if request.method == "POST" and "archivo" in request.FILES:
        form = FacturaProveedorForm(request.POST, request.FILES)

        if form.is_valid():
            factura = form.save()
            path = os.path.join(settings.MEDIA_ROOT, factura.archivo.name)

            registrar_evento(
                tipo="factura_proveedor_subida",
                titulo=f"Factura de proveedor subida (ID {factura.pk})",
                detalle="Factura de proveedor cargada para análisis automático.",
                user=getattr(request, "user", None),
                obj=factura,
                extra={
                    "factura_id": factura.pk,
                    "archivo": factura.archivo.name,
                },
            )

            texto_manual = request.POST.get("texto_manual", "").strip()
            if texto_manual:
                raw_text = texto_manual
                factura_url = None
                es_pdf = False
                resultado = parse_invoice_text(raw_text)
            else:
                raw_text = extraer_texto_factura_simple(path)
                factura_url = factura.archivo.url
                es_pdf = True

                resultado = parse_invoice_pdf(path)

                if not resultado:
                    resultado = parse_invoice_text(raw_text)

            productos = list(
                ProductoPrecio.objects.filter(activo=True).values(
                    "id", "sku", "nombre_publico", "precio", "precio_costo"
                )
            )

            items = []
            for r in resultado:
                producto_txt = _normalizar_texto_factura(r.get("producto", ""))
                cantidad = r.get("cantidad", Decimal("1"))
                precio = r.get("precio_unitario", Decimal("0"))

                sugerencias = sugerencias_para(producto_txt, productos, top=2)

                items.append({
                    "producto": producto_txt,
                    "cantidad": str(cantidad),
                    "precio_unitario": str(precio),
                    "subtotal": str(cantidad * precio),
                    "sugerencias": sugerencias,
                    "match_principal": sugerencias[0] if sugerencias else None,
                })

            request.session["factura_id"] = factura.id
            request.session["items_factura"] = [
                {
                    "producto": i["producto"],
                    "cantidad": i["cantidad"],
                    "precio_unitario": i["precio_unitario"],
                    "subtotal": i["subtotal"],
                    "sugerencias": i["sugerencias"],
                    "decision": None,
                }
                for i in items
            ]

            return render(
                request,
                "pdf/procesar_factura.html",
                {
                    "preview": True,
                    "items": items,
                    "productos_livianos": productos,
                    "fecha_detectada": datetime.now().strftime("%Y-%m-%d"),
                    "factura_url": factura_url,
                    "es_pdf": es_pdf,
                    "raw_text": raw_text,
                },
            )

    form = FacturaProveedorForm()
    ultimas = FacturaProveedor.objects.order_by("-fecha_subida")[:5]

    return render(
        request,
        "pdf/procesar_factura.html",
        {"form": form, "ultimas_facturas": ultimas},
    )


# ============================================================
# HISTORIA LISTAS
# ============================================================

@login_required
def historia_listas(request):
    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para hacer esto.")
    listas = ListaPrecioPDF.objects.all().order_by("-fecha_subida")
    return render(
        request,
        "pdf/historia_listas.html",
        {"listas": listas},
    )


# ============================================================
# FACTURA SIMPLE (PDF para cliente)
# ============================================================

@login_required
def factura_crear(request):
    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para hacer esto.")

    initial = {
        "vendedor_nombre": "Mundo Personalizado",
        "vendedor_whatsapp": "11 5663-7260",
        "vendedor_horario": "9:00 a 20:00",
        "vendedor_direccion": "Virrey del Pino, La Matanza",
    }

    if request.method == "POST":
        form = FacturaForm(request.POST)
        if form.is_valid():
            nombres = request.POST.getlist("item_nombre[]")
            precios = request.POST.getlist("item_precio[]")
            cantidades = request.POST.getlist("item_cantidad[]")
            descripciones = request.POST.getlist("item_descripcion[]")

            items = []
            total = Decimal("0.00")

            for nom, pre, cant, desc in zip(nombres, precios, cantidades, descripciones):
                nom = (nom or "").strip()
                if not nom:
                    continue

                precio = _to_decimal(pre, "0").quantize(Q2)
                try:
                    qty = int(cant)
                except ValueError:
                    qty = 1
                if qty <= 0:
                    continue

                subtotal = (precio * qty).quantize(Q2, rounding=ROUND_HALF_UP)
                total += subtotal

                items.append({
                    "nombre": nom,
                    "descripcion": (desc or "").strip(),
                    "precio": precio,
                    "cantidad": qty,
                    "subtotal": subtotal,
                })

            return _factura_pdf_response(request, form.cleaned_data, items, total)

    else:
        form = FacturaForm(initial=initial)

    return render(request, "pdf/factura_form.html", {"form": form})


# ============================================================
# LISTA DE PRECIOS PDF (con marca de agua fija + mayorista)
# ============================================================

def _precio_mayorista(unit: Decimal, descuento_pct: Decimal) -> Decimal:
    """
    descuento_pct: 20 => -20% (20% de descuento)
    """
    try:
        d = Decimal(descuento_pct or "0")
    except Exception:
        d = Decimal("0")

    if d < 0:
        d = Decimal("0")
    if d > 100:
        d = Decimal("100")

    factor = (Decimal("100") - d) / Decimal("100")
    return (unit * factor).quantize(Q2, rounding=ROUND_HALF_UP)


@login_required
def lista_precios_opciones(request):
    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para hacer esto.")

    if request.method == "POST":
        form = ListaPreciosPDFForm(request.POST, request.FILES)
        if form.is_valid():
            tecnica = form.cleaned_data["tecnica"]          # ALL / SUB / LAS / 3D / OTR
            incluir_sku = form.cleaned_data["incluir_sku"]  # bool
            descuento = form.cleaned_data["descuento_mayorista"]  # Decimal
            lista_mayorista = form.cleaned_data.get("lista_mayorista", False)
            incluir_costo = form.cleaned_data.get("incluir_costo", False) # ✅ Nuevo campo

            reemplazar_marca_agua = form.cleaned_data.get("reemplazar_marca_agua", False)
            marca_agua_upload = form.cleaned_data.get("marca_agua")

            instagram_url = form.cleaned_data.get("instagram_url") or ""
            whatsapp_url = form.cleaned_data.get("whatsapp_url") or ""

            # =========================
            # Marca de agua fija (DB)
            # =========================
            branding, _ = PDFBranding.objects.get_or_create(pk=1)

            if reemplazar_marca_agua and marca_agua_upload:
                branding.watermark = marca_agua_upload
                branding.save()

            watermark_reader = None
            if branding.watermark and getattr(branding.watermark, "path", None):
                try:
                    if os.path.exists(branding.watermark.path):
                        watermark_reader = ImageReader(branding.watermark.path)
                except Exception:
                    watermark_reader = None

            # =========================
            # Productos
            # =========================
            qs = ProductoPrecio.objects.filter(activo=True)
            if tecnica != "ALL":
                qs = qs.filter(tech=tecnica)
            qs = qs.order_by("tech", "nombre_publico")

            buckets = {"SUB": [], "LAS": [], "3D": [], "OTR": []}
            if tecnica == "ALL":
                for p in qs:
                    code = p.tech if p.tech in buckets else "OTR"
                    buckets[code].append(p)
                tech_order = ["SUB", "LAS", "3D", "OTR"]
            else:
                buckets = {tecnica: list(qs)}
                tech_order = [tecnica]

            # =========================
            # PDF Response
            # =========================
            filename = f"lista_precios_{timezone.localdate().strftime('%Y-%m-%d')}.pdf"
            resp = HttpResponse(content_type="application/pdf")
            resp["Content-Disposition"] = f'attachment; filename="{filename}"'

            styles = getSampleStyleSheet()

            sku_style = ParagraphStyle(
                "SkuSmall",
                parent=styles["Normal"],
                fontSize=8,
                textColor=colors.grey,
                leading=9,
            )

            def draw_header_and_watermark(canvas, doc_):
                canvas.saveState()

                page_w, page_h = A4

                # Marca de agua
                if watermark_reader:
                    try:
                        canvas.setFillAlpha(0.16)
                    except Exception:
                        pass

                    canvas.drawImage(
                        watermark_reader,
                        0,
                        0,
                        width=page_w,
                        height=page_h,
                        preserveAspectRatio=True,
                        anchor="c",
                        mask="auto",
                    )

                    try:
                        canvas.setFillAlpha(1)
                    except Exception:
                        pass

                # Header técnica
                tech_txt = getattr(doc_, "current_tech", "") or ""
                if tech_txt:
                    canvas.setFont("Helvetica-Bold", 12)
                    canvas.setFillColor(colors.black)
                    canvas.drawString(doc_.leftMargin, page_h - 2.2 * cm, tech_txt)

                    canvas.setStrokeColor(colors.lightgrey)
                    canvas.setLineWidth(0.6)
                    canvas.line(
                        doc_.leftMargin,
                        page_h - 2.35 * cm,
                        page_w - doc_.rightMargin,
                        page_h - 2.35 * cm,
                    )

                # Footer botones
                y = 0.9 * cm
                btn_w = 5.6 * cm
                btn_h = 1.0 * cm

                canvas.setFont("Helvetica-Bold", 9)

                if whatsapp_url:
                    x = doc_.leftMargin
                    canvas.setFillColorRGB(0.13, 0.75, 0.38)
                    canvas.roundRect(x, y, btn_w, btn_h, 8, fill=1, stroke=0)
                    canvas.setFillColor(colors.white)
                    canvas.drawCentredString(x + btn_w / 2, y + btn_h / 2 - 3, "📱 WhatsApp")
                    canvas.linkURL(whatsapp_url, (x, y, x + btn_w, y + btn_h), relative=0)

                if instagram_url:
                    x = page_w - doc_.rightMargin - btn_w
                    canvas.setFillColorRGB(0.86, 0.26, 0.55)
                    canvas.roundRect(x, y, btn_w, btn_h, 8, fill=1, stroke=0)
                    canvas.setFillColor(colors.white)
                    canvas.drawCentredString(x + btn_w / 2, y + btn_h / 2 - 3, "📸 Instagram")
                    canvas.linkURL(instagram_url, (x, y, x + btn_w, y + btn_h), relative=0)

                canvas.setFillColor(colors.grey)
                canvas.setFont("Helvetica", 8)
                canvas.drawCentredString(page_w / 2, y - 0.35 * cm, f"Página {doc_.page}")

                canvas.restoreState()

            doc = TechHeaderDoc(
                resp,
                pagesize=A4,
                leftMargin=1.2 * cm,
                rightMargin=1.2 * cm,
                topMargin=3.0 * cm,
                bottomMargin=3.5 * cm,
                title="Lista de precios",
            )

            story = []

            # =========================
            # Secciones + Tablas
            # =========================
            for tech_code in tech_order:
                items = buckets.get(tech_code) or []
                if not items:
                    continue

                story.append(Paragraph(_tech_label(tech_code), styles["Heading1"]))
                story.append(Spacer(1, 0.15 * cm))

                header_precio = "Mayorista" if lista_mayorista else "Unitario"

                # ✅ Configuración dinámica de columnas según checkbox
                if incluir_costo:
                    data = [["Imagen", "Producto", "Precio Costo", header_precio]]
                    colw = [2.6 * cm, 7.6 * cm, 3.2 * cm, 3.2 * cm]
                    align_cols = (2, 0), (3, -1)  # Alinea derecha a costo y venta
                    img_size = 2.2
                else:
                    data = [["Imagen", "Producto", header_precio]]
                    colw = [3.0 * cm, 9.6 * cm, 4.0 * cm]
                    align_cols = (2, 0), (2, -1)  # Alinea derecha solo a venta
                    img_size = 2.4

                for p in items:
                    unit = (p.precio or Decimal("0.00")).quantize(Q2)
                    may = _precio_mayorista(unit, descuento)
                    precio = may if lista_mayorista else unit

                    nombre_paragraph = Paragraph(
                        f"<b>{p.nombre_publico}</b>",
                        styles["Normal"],
                    )

                    if incluir_sku and (p.sku or "").strip():
                        prod_cell = [
                            nombre_paragraph,
                            Paragraph(f"SKU: {p.sku}", sku_style),
                        ]
                    else:
                        prod_cell = nombre_paragraph

                    precio_paragraph = Paragraph(
                        f"<b>$ {precio:.2f}</b>",
                        styles["Normal"],
                    )

                    # ✅ Armado dinámico de la fila
                    fila = [
                        _safe_img(p.imagen, max_w_cm=img_size, max_h_cm=img_size),
                        prod_cell,
                    ]

                    if incluir_costo:
                        costo = (getattr(p, "precio_costo", None) or Decimal("0.00")).quantize(Q2)
                        costo_paragraph = Paragraph(
                            f"<b>$ {costo:.2f}</b>",
                            styles["Normal"],
                        )
                        fila.append(costo_paragraph)

                    fila.append(precio_paragraph)
                    data.append(fila)

                table = Table(data, colWidths=colw, repeatRows=1)

                table.setStyle(TableStyle([
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("FONTSIZE", (0, 1), (-1, -1), 9),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    
                    # ✅ Alineación dinámica (aplica a las columnas de precios correspondientes)
                    ("ALIGN", align_cols[0], align_cols[1], "RIGHT"),
                    
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (1, 0), (1, -1), 8),
                    ("LEFTPADDING", (0, 0), (0, -1), 4),
                    ("RIGHTPADDING", (0, 0), (0, -1), 4),
                ]))

                story.append(table)
                story.append(PageBreak())

            doc.build(
                story,
                onFirstPage=draw_header_and_watermark,
                onLaterPages=draw_header_and_watermark,
            )

            return resp

    else:
        form = ListaPreciosPDFForm()

    return render(request, "pdf/lista_precios_opciones.html", {"form": form})

# ============================================================
# GENERACIÓN PDF FACTURA (con archivo en bitácora)
# ============================================================

@login_required
def _factura_pdf_response(request, data, items, total):
    if not _check_owner(request.user):
        raise PermissionDenied("No tienes permiso para hacer esto.")

    filename = f"factura_{timezone.localdate().strftime('%Y-%m-%d')}.pdf"

    buffer = BytesIO()

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2.0 * cm,
        rightMargin=2.0 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
    )

    story = []

    def _rl_safe(text):
        return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    logo_path = os.path.join(settings.MEDIA_ROOT, "branding", "logo.png")

    left = []
    if os.path.exists(logo_path):
        left.append(Image(logo_path, width=2.8 * cm, height=2.8 * cm))
    else:
        left.append(Paragraph("<b>Mundo Personalizado</b>", styles["Title"]))

    titulo = Paragraph(
        "<para align='center'>"
        "<b>FACTURA SIN VALOR FISCAL</b><br/>"
        f"<font size=9>Fecha: {timezone.localtime().strftime('%d/%m/%Y %H:%M')}</font><br/>"
        f"<font size=9>Validez: {int(data.get('validez_dias') or 7)} días</font>"
        "</para>",
        styles["Normal"],
    )

    vendedor = Paragraph(
        "<para align='right'>"
        f"<b>{_rl_safe(data['vendedor_nombre'])}</b><br/>"
        f"WhatsApp: {_rl_safe(data['vendedor_whatsapp'])}<br/>"
        f"Horario: {_rl_safe(data['vendedor_horario'])}<br/>"
        f"{_rl_safe(data['vendedor_direccion'])}"
        "</para>",
        styles["Normal"],
    )

    header = Table(
        [[left, titulo, vendedor]],
        colWidths=[3.2 * cm, 7.0 * cm, 6.0 * cm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.lightgrey),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
    ]))
    story.append(header)
    story.append(Spacer(1, 0.5 * cm))

    cliente = Table(
        [[
            Paragraph(
                f"<b>Cliente</b><br/>"
                f"Nombre: {_rl_safe(data['cliente_nombre'])}<br/>"
                f"Tel: {_rl_safe(data.get('cliente_telefono') or '—')}<br/>"
                f"DNI/CUIL: {_rl_safe(data.get('cliente_doc') or '—')}<br/>"
                f"Dirección: {_rl_safe(data.get('cliente_direccion') or '—')}",
                styles["Normal"],
            )
        ]],
        colWidths=[16.2 * cm],
    )

    cliente.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, colors.lightgrey),
        ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(cliente)
    story.append(Spacer(1, 0.5 * cm))

    table_data = [["Producto", "Cant.", "Unitario", "Subtotal"]]

    for it in items:
        nombre_safe = _rl_safe(it["nombre"])
        desc_safe = _rl_safe(it.get("descripcion") or "")

        if desc_safe:
            prod_text = (
                f"<b>{nombre_safe}</b><br/>"
                f"<font size='8' color='#777777'>{desc_safe}</font>"
            )
        else:
            prod_text = f"<b>{nombre_safe}</b>"

        prod_paragraph = Paragraph(prod_text, styles["Normal"])

        table_data.append([
            prod_paragraph,
            str(it["cantidad"]),
            f"$ {it['precio']:.2f}",
            f"$ {it['subtotal']:.2f}",
        ])

    tabla = Table(
        table_data,
        colWidths=[9.5 * cm, 1.5 * cm, 2.6 * cm, 2.6 * cm],
        repeatRows=1,
    )
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tabla)
    story.append(Spacer(1, 0.5 * cm))

    sena = _to_decimal(data.get("sena") or "0", "0").quantize(Q2)
    saldo = (total - sena).quantize(Q2)

    resumen = Table(
        [
            ["Seña:", f"$ {sena:.2f}"],
            ["Total:", f"$ {total.quantize(Q2):.2f}"],
            ["Falta abonar:", f"$ {saldo:.2f}"],
        ],
        colWidths=[12.0 * cm, 4.2 * cm],
    )

    resumen.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(resumen)

    story.append(Spacer(1, 0.4 * cm))
    story.append(
        Paragraph(
            "<para align='center'><font size=8 color='#666666'>"
            "Presupuesto / Factura sin valor fiscal. Validez 7 días salvo indicación contraria."
            "</font></para>",
            styles["Normal"],
        )
    )

    doc.build(story)

    pdf_bytes = buffer.getvalue()
    buffer.close()

    usuario = request.user if request.user.is_authenticated else None

    items_resumen = [
        {
            "nombre": it["nombre"],
            "descripcion": it.get("descripcion") or "",
            "cantidad": it["cantidad"],
            "precio": str(it["precio"]),
            "subtotal": str(it["subtotal"]),
        }
        for it in items
    ]

    extra = {
        "cliente_nombre": data.get("cliente_nombre"),
        "cliente_telefono": data.get("cliente_telefono"),
        "cliente_doc": data.get("cliente_doc"),
        "cliente_direccion": data.get("cliente_direccion"),
        "total": str(total.quantize(Q2)),
        "sena": str(sena),
        "saldo": str(saldo),
        "items": items_resumen,
    }

    evento = BitacoraEvento.objects.create(
        usuario=usuario,
        tipo="factura_pdf_generada",
        titulo=f"Factura PDF generada para {data.get('cliente_nombre') or 'cliente sin nombre'}",
        detalle=f"Total $ {total.quantize(Q2):.2f} - Items: {len(items)}",
        obj_model="",
        obj_id="",
        extra=extra,
    )

    evento.archivo.save(filename, ContentFile(pdf_bytes))

    resp = HttpResponse(content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.write(pdf_bytes)
    return resp