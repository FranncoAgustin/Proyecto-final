import os
import csv
import re
from io import BytesIO

from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.db import IntegrityError, transaction
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone
from django.contrib import messages
from django.db.models import F, Q




from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime
from difflib import SequenceMatcher


from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader


from .forms import ListaPrecioForm, FacturaProveedorForm, ListaPreciosPDFForm, FacturaForm
from .models import ListaPrecioPDF, ProductoPrecio, FacturaProveedor, ItemFactura, ProductoVariante
from .utils import extraer_precios_de_pdf, get_similarity
from .utils_ocr import extraer_datos_factura
from .utils_facturas import extraer_texto_factura_simple, parse_invoice_text
from ofertas.utils import get_precio_con_oferta

# ===================== CATÁLOGO / LISTAS =====================

Q2 = Decimal("0.01")

def _get_cart(request):
    return request.session.get("carrito", {})


def _save_cart(request, cart):
    request.session["carrito"] = cart
    request.session.modified = True


def _make_key(prod_id: int, var_id: int | None):
    var_id = int(var_id or 0)
    return f"{int(prod_id)}:{var_id}"

def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9áéíóúñü\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _score(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()

@require_GET
def api_productos(request):
    q = (request.GET.get("q") or "").strip()
    qs = ProductoPrecio.objects.filter(activo=True)

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
        })
    return JsonResponse({"results": data})

def sugerencias_para(nombre_item: str, productos, top=8):
    # productos: iterable de (id, sku, nombre_publico)
    scored = []
    for pid, sku, nom in productos:
        s = max(_score(nombre_item, nom), _score(nombre_item, sku))
        scored.append((s, pid, sku, nom))
    scored.sort(reverse=True, key=lambda x: x[0])
    return scored[:top]

def _to_decimal(v, default="0"):
    try:
        s = str(v).strip().replace(",", ".")
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal(default)
    
def mostrar_precios(request):
    productos = ProductoPrecio.objects.filter(activo=True).order_by('nombre_publico')

    productos_data = []
    for p in productos:
        data = get_precio_con_oferta(p)
        productos_data.append({
            "producto": p,
            **data
        })

    return render(
        request,
        "pdf/mostrar_precios.html",
        {"productos": productos_data}
    )


def detalle_producto(request, pk):
    producto = get_object_or_404(ProductoPrecio, pk=pk)
    variantes = producto.variantes.all().order_by("orden")

    # Variante principal implícita (producto base)
    variante_principal = {
        "id": 0,
        "nombre": "Principal",
        "imagen": producto.imagen,
        "descripcion_corta": producto.nombre_publico,
        "es_principal": True,
    }

    variantes_ui = [variante_principal]

    for v in variantes:
        variantes_ui.append({
            "id": v.id,
            "nombre": v.nombre,
            "imagen": v.imagen,
            "descripcion_corta": v.descripcion_corta,
            "es_principal": False,
        })

    return render(
        request,
        "pdf/detalle_producto.html",
        {
            "producto": producto,
            "variantes_ui": variantes_ui,
        },
    )

@require_POST
def agregar_al_carrito(request, pk):
    producto = get_object_or_404(ProductoPrecio, pk=pk, activo=True)

    variante_id = request.POST.get("variante_id", "0")
    try:
        variante_id = int(variante_id)
    except ValueError:
        variante_id = 0

    # Validar que la variante pertenece al producto
    if variante_id:
        ok = ProductoVariante.objects.filter(
            pk=variante_id, producto=producto, activo=True
        ).exists()
        if not ok:
            variante_id = 0

    cart = _get_cart(request)
    key = _make_key(producto.id, variante_id)

    cart[key] = cart.get(key, 0) + 1
    _save_cart(request, cart)

    return redirect("detalle_producto", pk=pk)


# --- VISTA PRINCIPAL (Fusiona los 3 pasos: Carga, Previsualización, Confirmación) ---

def verificar_producto_existente(request):
    """
    Endpoint usado por el input editable del template para chequear
    si un SKU ya existe y traer el precio actual.
    """
    nombre = request.GET.get('nombre', '').strip()
    if not nombre:
        return JsonResponse({'existe': False})

    producto = ProductoPrecio.objects.filter(sku=nombre).first()
    if producto:
        return JsonResponse({
            'existe': True,
            'id': producto.id,
            'nombre': producto.nombre_publico,
            'precio_actual': producto.precio,
        })
    return JsonResponse({'existe': False})


# ===================== IMPORTAR LISTA DE PRECIOS (PDF) =====================

def importar_pdf(request):
    """
    Importa / actualiza precios desde un PDF de lista de precios.

    Paso 1 (POST con file): genera 'candidates' y los guarda en sesión.
    Paso 2 (POST con confirm): aplica acciones elegidas y genera 'report'.
    GET: muestra formulario vacío + últimas listas procesadas.
    """

    # Reporte base compatible con el template “pro”
    report = {
        'imported': 0,
        'updated': 0,
        'skipped': 0,
        'usd_to_review': [],      # productos detectados en USD
        'not_found': [],          # productos que no estaban en DB en modo update_only
        'not_seen_active': [],    # productos en DB que no aparecieron en el PDF
        'imported_items': [],
        'updated_items': [],
        'skipped_items': [],
        'parse_errors': [],       # líneas del PDF que no se pudieron interpretar
    }
    msg = ""
    update_only = request.POST.get('update_only') in ('on', 'true', '1')

    # =============== PASO 2: CONFIRMAR E IMPORTAR ===============
    if request.method == 'POST' and request.POST.get('confirm'):
        productos_a_revisar = request.session.pop('productos_a_revisar', [])
        lista_pdf_id = request.session.pop('lista_pdf_id', None)

        if not lista_pdf_id:
            msg = "Error: sesión expirada. Volvé a subir el PDF."
            listas_procesadas = ListaPrecioPDF.objects.all().order_by('-fecha_subida')[:5]
            return render(
                request,
                'pdf/importar_pdf.html',
                {
                    'msg': msg,
                    'report': report,
                    'preview': False,
                    'update_only': False,
                    'listas_procesadas': listas_procesadas,
                },
            )

        lista_pdf = get_object_or_404(ListaPrecioPDF, pk=lista_pdf_id)

        # Para calcular luego qué SKUs no aparecieron en el PDF
        skus_vistos_pdf = []

        for index, producto in enumerate(productos_a_revisar):
            action_key = f'action_{index}'
            accion_valor = (request.POST.get(action_key) or '').strip()

            # Nombre final (editado o original)
            name_key = f'name_{index}'
            nombre_final = request.POST.get(name_key, producto['sku_original']).strip()

            if not nombre_final:
                # Nada que hacer
                continue

            skus_vistos_pdf.append(nombre_final)

            if not accion_valor:
                # Si por algún motivo no vino, lo tratamos como "ignore"
                accion = 'ignore'
                target_id = None
            else:
                parts = accion_valor.split(':', 1)
                accion = parts[0]
                target_id = parts[1] if len(parts) > 1 else None

            sku = nombre_final
            precio_nuevo = Decimal(producto['precio_nuevo'])
            moneda = producto.get('moneda', 'ARS')

            # Búsqueda de producto existente
            producto_existente_db = None
            if target_id:
                try:
                    producto_existente_db = ProductoPrecio.objects.get(pk=target_id)
                except ProductoPrecio.DoesNotExist:
                    producto_existente_db = None

            if not producto_existente_db:
                producto_existente_db = ProductoPrecio.objects.filter(sku=sku).first()

            # Crear base del ítem para el reporte
            item_reporte = {
                'sku': sku,
                'currency': moneda,
                'price': f'{precio_nuevo:.2f}',
            }

            # Si está en USD lo marcamos para revisión
            if moneda == 'USD':
                report['usd_to_review'].append({
                    'sku': sku,
                    'price': f'{precio_nuevo:.2f}',
                })

            # Si el usuario marcó IGNORAR → reporte y seguimos
            if accion == 'ignore':
                report['skipped'] += 1
                report['skipped_items'].append({
                    'reason': 'Ignorado por usuario',
                    'sku': sku,
                })
                continue

            # Si está activo "sólo actualizar" y no existe el producto → lo agregamos a not_found
            if update_only and not producto_existente_db:
                report['skipped'] += 1
                report['not_found'].append(sku)
                report['skipped_items'].append({
                    'reason': 'update_only_sin_existente',
                    'sku': sku,
                })
                continue

            # ========== LÓGICA DE ACTUALIZACIÓN / CREACIÓN ==========
            if producto_existente_db:
                # Ya existe → actualizamos si cambió el precio
                prev_price = producto_existente_db.precio
                changed = (prev_price != precio_nuevo)

                if changed:
                    producto_existente_db.precio = precio_nuevo
                    producto_existente_db.lista_pdf = lista_pdf
                    producto_existente_db.save()

                    report['updated'] += 1
                    item_reporte.update({
                        'prev_price': f'{prev_price:.2f}',
                        'changed': True,
                        'note': 'Precio actualizado',
                    })
                    report['updated_items'].append(item_reporte)
                else:
                    report['skipped'] += 1
                    report['skipped_items'].append({
                        'reason': 'Precio sin cambios',
                        'sku': sku,
                    })
            else:
                # No existe y no estamos en update_only → crear
                try:
                    ProductoPrecio.objects.create(
                        lista_pdf=lista_pdf,
                        sku=sku,
                        nombre_publico=sku,
                        precio=precio_nuevo,
                    )
                except IntegrityError:
                    # En caso de colisión inesperada por unique
                    report['skipped'] += 1
                    report['skipped_items'].append({
                        'reason': 'Error: nombre duplicado en DB',
                        'sku': sku,
                    })
                    continue

                report['imported'] += 1
                item_reporte.update({
                    'note': 'Nuevo producto creado',
                })
                report['imported_items'].append(item_reporte)

        # SKUs existentes en la DB que no aparecieron en el PDF actual
        todos_skus = list(
            ProductoPrecio.objects
            .exclude(sku__isnull=True)
            .exclude(sku__exact='')
            .values_list('sku', flat=True)
        )
        skus_vistos_pdf = set(skus_vistos_pdf)
        report['not_seen_active'] = [
            s for s in todos_skus if s not in skus_vistos_pdf
        ][:200]

        msg = (
            f"PROCESO OK — importados {report['imported']}, "
            f"actualizados {report['updated']}, omitidos {report['skipped']}, "
            f"no encontrados (update_only) {len(report['not_found'])}, "
            f"activos no vistos {len(report['not_seen_active'])}."
        )

        return render(
            request,
            'pdf/importar_pdf.html',
            {
                'msg': msg,
                'report': report,
                'preview': False,
                'update_only': update_only,
            },
        )

    # =============== PASO 1: SUBIR PDF Y PREVIEW ===============
    if request.method == 'POST' and request.FILES.get('file'):
        archivo_pdf = request.FILES['file']

        lista_pdf = ListaPrecioPDF.objects.create(
            nombre=archivo_pdf.name,
            archivo_pdf=archivo_pdf,
        )
        pdf_path = os.path.join(settings.MEDIA_ROOT, lista_pdf.archivo_pdf.name)

        # Nueva versión: items + errores de parseo
        productos_extraidos, parse_errors = extraer_precios_de_pdf(pdf_path)

        candidates = []
        skus_existentes = {p.sku: p for p in ProductoPrecio.objects.all()}
        productos_a_revisar = []

        # Para marcar duplicados dentro del mismo PDF
        contador_nombres = {}

        for item in productos_extraidos:
            sku_original = item['nombre']
            precio_nuevo = item['precio']
            moneda = item.get('moneda', 'ARS')

            # Marcamos productos en USD para revisión
            if moneda == 'USD':
                report['usd_to_review'].append({
                    'sku': sku_original,
                    'price': str(precio_nuevo),
                    'page': item.get('page'),
                })

            contador_nombres[sku_original] = contador_nombres.get(sku_original, 0) + 1

            exact_match = skus_existentes.get(sku_original)
            sug_match = None
            max_similitud = 0

            if not exact_match:
                for existing_sku, existing_product in skus_existentes.items():
                    similitud = get_similarity(sku_original, existing_sku)
                    if similitud > max_similitud and similitud >= 70:
                        max_similitud = similitud
                        sug_match = existing_product

            c = {
                'name': sku_original,
                'price': precio_nuevo,
                'currency': moneda,
                'dup_in_pdf': False,  # lo pisamos luego
                'exact_db_id': exact_match.id if exact_match else None,
                'exact_db_label': exact_match.nombre_publico if exact_match else None,
                'sug_id': sug_match.id if sug_match else None,
                'sug_label': sug_match.nombre_publico if sug_match else None,
                'sug_score': max_similitud,
            }
            candidates.append(c)

            productos_a_revisar.append({
                'sku_original': sku_original,
                'precio_nuevo': str(precio_nuevo),
                'moneda': moneda,
                'coincidencia_id': c['exact_db_id'] or c['sug_id'],
            })

        # Ahora marcamos los duplicados en PDF
        for c in candidates:
            c['dup_in_pdf'] = contador_nombres.get(c['name'], 0) > 1

        # Guardamos en sesión para el paso 2
        request.session['productos_a_revisar'] = productos_a_revisar
        request.session['lista_pdf_id'] = lista_pdf.id

        # Guardamos también errores de parseo para mostrar en el template
        report['parse_errors'] = parse_errors

        return render(
            request,
            'pdf/importar_pdf.html',
            {
                'preview': True,
                'candidates': candidates,
                'update_only': update_only,
                'report': report,
                'msg': msg,
            },
        )

    # =============== GET / FORM VACÍO ===============
    listas_procesadas = ListaPrecioPDF.objects.all().order_by('-fecha_subida')[:5]
    return render(
        request,
        'pdf/importar_pdf.html',
        {
            'msg': msg,
            'report': report,
            'preview': False,
            'update_only': False,
            'listas_procesadas': listas_procesadas,
        },
    )


# ===================== FACTURAS PROVEEDOR =====================

def procesar_factura(request):

    # ======================================================
    # PASO 2 — CONFIRMAR Y GUARDAR
    # ======================================================
    if request.method == "POST" and "confirmar_factura" in request.POST:

        factura_id = request.session.get("factura_id")
        items_sesion = request.session.get("items_factura", [])

        if not factura_id:
            messages.error(request, "Sesión expirada. Volvé a cargar la factura.")
            return redirect("procesar_factura")

        factura = get_object_or_404(FacturaProveedor, pk=factura_id)

        # Fecha editable
        fecha_str = request.POST.get("fecha_factura")
        if fecha_str:
            try:
                factura.fecha_factura = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                factura.save(update_fields=["fecha_factura"])
            except Exception:
                pass

        with transaction.atomic():

            for index, item in enumerate(items_sesion):

                if f"item_{index}_check" not in request.POST:
                    continue

                producto_txt = request.POST.get(
                    f"item_{index}_producto", item["producto"]
                ).strip()

                cantidad = _to_decimal(
                    request.POST.get(f"item_{index}_cantidad", item["cantidad"]), "1"
                )

                precio = _to_decimal(
                    request.POST.get(f"item_{index}_precio", item["precio_unitario"]), "0"
                )

                subtotal = cantidad * precio

                # -------------------------
                # Guardar ítem de factura
                # -------------------------
                ItemFactura.objects.create(
                    factura=factura,
                    producto=producto_txt,
                    cantidad=cantidad,
                    precio_unitario=precio,
                    subtotal=subtotal,
                )

                # -------------------------
                # Vinculación con catálogo
                # -------------------------
                sku_input = (request.POST.get(
                    f"item_{index}_catalogo_sku") or "").strip()

                crear = f"item_{index}_crear_si_no_existe" in request.POST
                upd_stock = f"item_{index}_upd_stock" in request.POST
                upd_precio = f"item_{index}_upd_precio" in request.POST

                # Definir SKU
                if sku_input:
                    sku = sku_input
                elif crear:
                    sku = (
                        producto_txt.lower()
                        .replace(" ", "_")
                        .replace("/", "_")
                        .replace("-", "_")[:50]
                    )
                else:
                    continue

                producto = ProductoPrecio.objects.filter(sku__iexact=sku).first()

                # Crear producto si no existe
                if not producto and crear:
                    producto = ProductoPrecio.objects.create(
                        sku=sku,
                        nombre_publico=producto_txt or sku,
                        precio=precio,   # 👉 costo por ahora
                        stock=0,
                        activo=True,
                    )

                if not producto:
                    continue

                # Actualizar stock
                if upd_stock:
                    ProductoPrecio.objects.filter(pk=producto.pk).update(
                        stock=F("stock") + int(cantidad)
                    )

                # Actualizar costo (precio)
                if upd_precio:
                    producto.precio = precio
                    producto.save(update_fields=["precio"])

        # limpiar sesión UNA SOLA VEZ
        request.session.pop("factura_id", None)
        request.session.pop("items_factura", None)

        messages.success(
            request,
            "Factura guardada y artículos procesados correctamente."
        )
        return redirect("procesar_factura")

    # ======================================================
    # PASO 1 — SUBIR Y ANALIZAR
    # ======================================================
    if request.method == "POST" and "archivo" in request.FILES:
        form = FacturaProveedorForm(request.POST, request.FILES)

        if form.is_valid():
            factura = form.save()
            path = os.path.join(settings.MEDIA_ROOT, factura.archivo.name)

            texto_manual = request.POST.get("texto_manual", "").strip()
            if texto_manual:
                raw_text = texto_manual
                factura_url = None
                es_pdf = False
            else:
                raw_text = extraer_texto_factura_simple(path)
                factura_url = factura.archivo.url
                es_pdf = True

            resultado = parse_invoice_text(raw_text)

            productos = list(
                ProductoPrecio.objects.values("id", "sku", "nombre_publico")
            )

            items = []
            for r in resultado:
                producto_txt = r.get("producto", "")
                cantidad = r.get("cantidad", Decimal("1"))
                precio = r.get("precio_unitario", Decimal("0"))

                items.append({
                    "producto": producto_txt,
                    "cantidad": str(cantidad),
                    "precio_unitario": str(precio),
                    "subtotal": str(cantidad * precio),
                    "suggest": sugerencias_para(producto_txt, productos),
                })

            request.session["factura_id"] = factura.id
            request.session["items_factura"] = [
                {
                    "producto": i["producto"],
                    "cantidad": i["cantidad"],
                    "precio_unitario": i["precio_unitario"],
                    "subtotal": i["subtotal"],
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

    # ======================================================
    # GET — FORMULARIO INICIAL
    # ======================================================
    form = FacturaProveedorForm()
    ultimas = FacturaProveedor.objects.order_by("-fecha_subida")[:5]

    return render(
        request,
        "pdf/procesar_factura.html",
        {"form": form, "ultimas_facturas": ultimas},
    )


def historia_listas(request):
    """
    Historia de ingresos: muestra todas las listas de precios PDF que se importaron,
    ordenadas de más nueva a más vieja.
    Más adelante le sumamos el detalle por lista + edición.
    """
    listas = ListaPrecioPDF.objects.all().order_by('-fecha_subida')
    return render(request, 'pdf/historia_listas.html', {
        'listas': listas,
    })


def _precio_mayorista(precio_unitario: Decimal, coef: Decimal = Decimal("0.90")) -> Decimal:
    # ejemplo: 0.90 = -10%. Cambiá el coeficiente si querés.
    if precio_unitario is None:
        return Decimal("0.00")
    return (precio_unitario * coef).quantize(Q2, rounding=ROUND_HALF_UP)

def _safe_img(img_field, styles, w=1.6*cm, h=1.6*cm):
    try:
        if not img_field:
            return Paragraph("—", styles["Normal"])
        pth = getattr(img_field, "path", None)
        if not pth:
            return Paragraph("—", styles["Normal"])
        im = Image(pth, width=w, height=h)
        im.hAlign = "CENTER"
        return im
    except Exception:
        return Paragraph("—", styles["Normal"])


def _tech_label(tech: str) -> str:
    return {
        "SUB": "Sublimación",
        "LAS": "Grabado láser",
        "3D":  "Impresión 3D",
        "OTR": "Otros",
        "":    "Otros",
        None:  "Otros",
    }.get(tech, "Otros")


def lista_precios_opciones(request):
    """
    Pantalla con opciones (GET) y genera el PDF (POST).
    """
    if request.method == "POST":
        form = ListaPreciosPDFForm(request.POST, request.FILES)
        if form.is_valid():
            tecnica = form.cleaned_data["tecnica"]          # ALL / SUB / LAS / 3D / OTR
            incluir_sku = form.cleaned_data["incluir_sku"]  # bool
            descuento = form.cleaned_data["descuento_mayorista"]  # Decimal
            marca_agua = form.cleaned_data.get("marca_agua")      # InMemoryUploadedFile | None
            instagram_url = form.cleaned_data.get("instagram_url") or ""
            whatsapp_url = form.cleaned_data.get("whatsapp_url") or ""

            # productos
            qs = ProductoPrecio.objects.filter(activo=True)
            if tecnica != "ALL":
                qs = qs.filter(tech=tecnica)
            qs = qs.order_by("tech", "nombre_publico")

            # Agrupar (si ALL => por técnica; si no ALL => solo una sección)
            buckets = {"SUB": [], "LAS": [], "3D": [], "OTR": []}
            if tecnica == "ALL":
                for p in qs:
                    code = p.tech if p.tech in buckets else "OTR"
                    buckets[code].append(p)
                tech_order = ["SUB", "LAS", "3D", "OTR"]
            else:
                # una sola sección
                buckets = {tecnica: list(qs)}
                tech_order = [tecnica]

            # ===== PDF Response =====
            filename = f"lista_precios_{timezone.localdate().strftime('%Y-%m-%d')}.pdf"
            resp = HttpResponse(content_type="application/pdf")
            resp["Content-Disposition"] = f'attachment; filename="{filename}"'

            styles = getSampleStyleSheet()

            # ✅ Ruta del LOGO (ajustá si tu archivo se llama distinto)
            LOGO_PATH = os.path.join(settings.MEDIA_ROOT, "branding", "logo.png")

            # Marca de agua (opcional): la convertimos a ImageReader en memoria
            watermark_reader = None
            if marca_agua:
                try:
                    wm_bytes = marca_agua.read()
                    watermark_reader = ImageReader(BytesIO(wm_bytes))
                except Exception:
                    watermark_reader = None

            def draw_header_and_watermark(canvas, doc_):
                canvas.saveState()

                # =========================
                # MARCA DE AGUA
                # =========================
                if watermark_reader:
                    try:
                        canvas.setFillAlpha(0.08)
                    except Exception:
                        pass

                    page_w, page_h = A4
                    canvas.drawImage(
                        watermark_reader,
                        0, 0,
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

                # =========================
                # FOOTER BOTONES
                # =========================
                page_w, page_h = A4
                y = 0.9 * cm
                btn_w = 5.6 * cm
                btn_h = 1.0 * cm

                canvas.setFont("Helvetica-Bold", 9)

                # ---------- WHATSAPP (IZQUIERDA) ----------
                if whatsapp_url:
                    x = doc_.leftMargin
                    canvas.setFillColorRGB(0.13, 0.75, 0.38)
                    canvas.roundRect(x, y, btn_w, btn_h, 8, fill=1, stroke=0)

                    canvas.setFillColor(colors.white)
                    canvas.drawCentredString(
                        x + btn_w / 2,
                        y + btn_h / 2 - 3,
                        "📱 WhatsApp"
                    )

                    canvas.linkURL(
                        whatsapp_url,
                        (x, y, x + btn_w, y + btn_h),
                        relative=0
                    )

                # ---------- INSTAGRAM (DERECHA) ----------
                if instagram_url:
                    x = page_w - doc_.rightMargin - btn_w
                    canvas.setFillColorRGB(0.86, 0.26, 0.55)
                    canvas.roundRect(x, y, btn_w, btn_h, 8, fill=1, stroke=0)

                    canvas.setFillColor(colors.white)
                    canvas.drawCentredString(
                        x + btn_w / 2,
                        y + btn_h / 2 - 3,
                        "📸 Instagram"
                    )

                    canvas.linkURL(
                        instagram_url,
                        (x, y, x + btn_w, y + btn_h),
                        relative=0
                    )

                # ---------- NÚMERO DE PÁGINA ----------
                canvas.setFillColor(colors.grey)
                canvas.setFont("Helvetica", 8)
                canvas.drawCentredString(
                    page_w / 2,
                    y - 0.35 * cm,
                    f"Página {doc_.page}"
                )

                canvas.restoreState()

            # ✅ Más margen arriba para que la tabla NO tape el logo
            doc = SimpleDocTemplate(
                resp,
                pagesize=A4,
                leftMargin=1.2 * cm,
                rightMargin=1.2 * cm,
                topMargin=3.2 * cm,     # 👈 clave para que no lo tape la tabla
                bottomMargin=1.2 * cm,
                title="Lista de precios",
            )

            story = []

            # =========================
            # ✅ SECCIONES + TABLAS
            # =========================
            for tech_code in tech_order:
                items = buckets.get(tech_code) or []
                if not items:
                    continue

                story.append(Paragraph(_tech_label(tech_code), styles["Heading1"]))
                story.append(Spacer(1, 0.2 * cm))

                # Encabezados según incluir_sku
                if incluir_sku:
                    data = [["Imagen", "Producto", "SKU", "Unitario", "Mayorista"]]
                    colw = [2.0*cm, 8.5*cm, 2.5*cm, 3.0*cm, 3.0*cm]
                else:
                    data = [["Imagen", "Producto", "Unitario", "Mayorista"]]
                    colw = [2.0*cm, 11.0*cm, 3.0*cm, 3.0*cm]

                for p in items:
                    unit = (p.precio or Decimal("0.00")).quantize(Q2)
                    may = _precio_mayorista(unit, descuento)

                    if incluir_sku:
                        data.append([
                            _safe_img(p.imagen, styles),
                            Paragraph(f"<b>{p.nombre_publico}</b>", styles["Normal"]),
                            Paragraph((p.sku or "—"), styles["Normal"]),
                            Paragraph(f"$ {unit:.2f}", styles["Normal"]),
                            Paragraph(f"$ {may:.2f}", styles["Normal"]),
                        ])
                    else:
                        data.append([
                            _safe_img(p.imagen, styles),
                            Paragraph(f"<b>{p.nombre_publico}</b>", styles["Normal"]),
                            Paragraph(f"$ {unit:.2f}", styles["Normal"]),
                            Paragraph(f"$ {may:.2f}", styles["Normal"]),
                        ])

                table = Table(data, colWidths=colw, repeatRows=1)
                table.setStyle(TableStyle([
                    # ❌ SIN FONDOS (TRANSPARENTE)
                    ("GRID",       (0,0), (-1,-1), 0.25, colors.grey),

                    ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
                    ("ALIGN",      (-2,1), (-1,-1), "RIGHT"),

                    ("FONTSIZE",   (0,0), (-1,0), 10),
                    ("FONTSIZE",   (0,1), (-1,-1), 9),

                    ("TOPPADDING", (0,0), (-1,-1), 6),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
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

def factura_crear(request):
    # Defaults vendedor
    initial = {
        "vendedor_nombre": "Mundo Personalizado",
        "vendedor_whatsapp": "11 5663-7260",
        "vendedor_horario": "9:00 a 20:00",
        "vendedor_direccion": "Virrey del Pino, La Matanza",
    }

    if request.method == "POST":
        form = FacturaForm(request.POST)
        if form.is_valid():
            # ====== leer items dinámicos ======
            nombres = request.POST.getlist("item_nombre[]")
            precios = request.POST.getlist("item_precio[]")
            cantidades = request.POST.getlist("item_cantidad[]")

            items = []
            total = Decimal("0.00")

            for nom, pre, cant in zip(nombres, precios, cantidades):
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
                    "precio": precio,
                    "cantidad": qty,
                    "subtotal": subtotal,
                })

            # ====== generar PDF ======
            return _factura_pdf_response(form.cleaned_data, items, total)

    else:
        form = FacturaForm(initial=initial)

    return render(request, "pdf/factura_form.html", {"form": form})

def _factura_pdf_response(data, items, total):
    filename = f"factura_{timezone.localdate().strftime('%Y-%m-%d')}.pdf"
    resp = HttpResponse(content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        resp, pagesize=A4,
        leftMargin=2.0*cm, rightMargin=2.0*cm,
        topMargin=1.8*cm, bottomMargin=1.8*cm
    )

    story = []

    # Logo
    logo_path = os.path.join(settings.MEDIA_ROOT, "branding", "logo.png")

    left = []
    if os.path.exists(logo_path):
        left.append(Image(logo_path, width=2.8*cm, height=2.8*cm))
    else:
        left.append(Paragraph("<b>Mundo Personalizado</b>", styles["Title"]))

    titulo = Paragraph(
        "<para align='center'>"
        "<b>FACTURA SIN VALOR FISCAL</b><br/>"
        f"<font size=9>Fecha: {timezone.localtime().strftime('%d/%m/%Y %H:%M')}</font><br/>"
        f"<font size=9>Validez: {int(data.get('validez_dias') or 7)} días</font>"
        "</para>",
        styles["Normal"]
    )

    vendedor = Paragraph(
        "<para align='right'>"
        f"<b>{data['vendedor_nombre']}</b><br/>"
        f"WhatsApp: {data['vendedor_whatsapp']}<br/>"
        f"Horario: {data['vendedor_horario']}<br/>"
        f"{data['vendedor_direccion']}"
        "</para>",
        styles["Normal"]
    )

    header = Table([[left, titulo, vendedor]], colWidths=[3.2*cm, 7.0*cm, 6.0*cm])
    header.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LINEBELOW", (0,0), (-1,0), 0.75, colors.lightgrey),
        ("BOTTOMPADDING", (0,0), (-1,0), 10),
    ]))
    story.append(header)
    story.append(Spacer(1, 0.5*cm))

    # Cliente (más “cajita”)
    cliente = Table([[
        Paragraph(
            f"<b>Cliente</b><br/>"
            f"Nombre: {data['cliente_nombre']}<br/>"
            f"Tel: {data.get('cliente_telefono') or '—'}<br/>"
            f"DNI/CUIL: {data.get('cliente_doc') or '—'}<br/>"
            f"Dirección: {data.get('cliente_direccion') or '—'}",
            styles["Normal"]
        )
    ]], colWidths=[16.2*cm])

    cliente.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.6, colors.lightgrey),
        ("BACKGROUND", (0,0), (-1,-1), colors.whitesmoke),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(cliente)
    story.append(Spacer(1, 0.5*cm))

    # Items
    table_data = [["Producto", "Cant.", "Unitario", "Subtotal"]]
    for it in items:
        table_data.append([
            Paragraph(f"<b>{it['nombre']}</b>", styles["Normal"]),
            str(it["cantidad"]),
            f"$ {it['precio']:.2f}",
            f"$ {it['subtotal']:.2f}",
        ])

    tabla = Table(table_data, colWidths=[9.5*cm, 1.5*cm, 2.6*cm, 2.6*cm], repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN", (1,1), (-1,-1), "RIGHT"),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(tabla)
    story.append(Spacer(1, 0.5*cm))

    sena = _to_decimal(data.get("sena") or "0", "0").quantize(Q2)
    saldo = (total - sena).quantize(Q2)

    resumen = Table([
        ["Seña:", f"$ {sena:.2f}"],
        ["Total:", f"$ {total.quantize(Q2):.2f}"],
        ["Falta abonar:", f"$ {saldo:.2f}"],
    ], colWidths=[12.0*cm, 4.2*cm])

    resumen.setStyle(TableStyle([
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ("FONTNAME", (0,1), (-1,1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 11),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    story.append(resumen)

    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph(
        "<para align='center'><font size=8 color='#666666'>"
        "Presupuesto / Factura sin valor fiscal. Validez 7 días salvo indicación contraria."
        "</font></para>",
        styles["Normal"]
    ))

    doc.build(story)
    return resp