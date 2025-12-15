from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.db import IntegrityError
from decimal import Decimal
from datetime import datetime
import os
import csv

from .forms import ListaPrecioForm, FacturaProveedorForm
from .models import ListaPrecioPDF, ProductoPrecio, FacturaProveedor, ItemFactura
from .utils import extraer_precios_de_pdf, get_similarity
from .utils_ocr import extraer_datos_factura
from .utils_facturas import extraer_texto_factura_simple, parse_invoice_text


# ===================== CATÁLOGO / LISTAS =====================

from ofertas.utils import get_precio_con_oferta

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

def exportar_csv_catalogo(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="catalogo_final.csv"'
    writer = csv.writer(response)
    writer.writerow(['SKU', 'Nombre Público', 'Precio', 'Última Actualización'])

    for producto in ProductoPrecio.objects.all():
        writer.writerow([
            producto.sku,
            producto.nombre_publico,
            producto.precio,
            producto.ultima_actualizacion.strftime('%Y-%m-%d %H:%M'),
        ])
    return response


def detalle_producto(request, pk):
    producto = get_object_or_404(ProductoPrecio, pk=pk)
    return render(request, 'pdf/detalle_producto.html', {'producto': producto})


# Carrito simple usando session
def agregar_al_carrito(request, pk):
    producto = get_object_or_404(ProductoPrecio, pk=pk)

    carrito = request.session.get('carrito', {})
    carrito[str(producto.id)] = carrito.get(str(producto.id), 0) + 1

    request.session['carrito'] = carrito
    return redirect('detalle_producto', pk=pk)


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
    # === PASO 2: CONFIRMAR Y GUARDAR ===
    if request.method == 'POST' and 'confirmar_factura' in request.POST:
        factura_id = request.session.get('factura_id')
        items_sesion = request.session.get('items_factura', [])
        fecha_detectada_str = request.POST.get('fecha_factura')

        if not factura_id:
            return redirect('procesar_factura')

        factura = get_object_or_404(FacturaProveedor, pk=factura_id)

        # actualizar fecha si el usuario la cambió
        if fecha_detectada_str:
            try:
                factura.fecha_factura = datetime.strptime(
                    fecha_detectada_str, '%Y-%m-%d'
                ).date()
            except Exception:
                pass
        factura.save()

        count_saved = 0
        for index, item_data in enumerate(items_sesion):
            if request.POST.get(f'item_{index}_check') == 'on':
                prod = request.POST.get(
                    f'item_{index}_producto',
                    item_data['producto']
                )
                cant = request.POST.get(
                    f'item_{index}_cantidad',
                    item_data['cantidad']
                )
                prec = request.POST.get(
                    f'item_{index}_precio',
                    item_data['precio_unitario']
                )
                subtotal = Decimal(cant) * Decimal(prec)

                ItemFactura.objects.create(
                    factura=factura,
                    producto=prod,
                    cantidad=Decimal(cant),
                    precio_unitario=Decimal(prec),
                    subtotal=subtotal,
                )
                count_saved += 1

        # limpiar sesión
        request.session.pop('factura_id', None)
        request.session.pop('items_factura', None)

        msg = f"Factura guardada con éxito. {count_saved} ítems registrados."
        return render(
            request,
            'pdf/procesar_factura.html',
            {
                'msg_success': msg,
                'form': FacturaProveedorForm(),
            }
        )

    # === PASO 1: SUBIR Y ANALIZAR ===
    if request.method == 'POST' and 'archivo' in request.FILES:
        form = FacturaProveedorForm(request.POST, request.FILES)
        if form.is_valid():
            factura = form.save()
            file_path = os.path.join(settings.MEDIA_ROOT, factura.archivo.name)

            # 1) texto manual opcional (pegado por vos)
            texto_manual = (request.POST.get('texto_manual') or "").strip()

            # 2) si no hay texto manual, intentamos leer desde el PDF
            if texto_manual:
                raw_text = texto_manual
                es_pdf = False
            else:
                raw_text = extraer_texto_factura_simple(file_path)
                es_pdf = True

            # 3) parsear el texto para obtener items
            resultado_items = parse_invoice_text(raw_text)

            items_serializables = []
            for item in resultado_items:
                cantidad = item.get('cantidad', Decimal('1'))
                precio = item.get('precio_unitario', Decimal('0'))
                subtotal = item.get('subtotal', cantidad * precio)

                items_serializables.append({
                    'producto': item.get('producto', ''),
                    'cantidad': str(cantidad),
                    'precio_unitario': str(precio),
                    'subtotal': str(subtotal),
                })

            # si no detectamos nada, al menos dejamos el texto crudo para debug
            fecha_str = datetime.now().strftime('%Y-%m-%d')
            request.session['factura_id'] = factura.id
            request.session['items_factura'] = items_serializables

            return render(
                request,
                'pdf/procesar_factura.html',
                {
                    'preview': True,
                    'items': items_serializables,
                    'fecha_detectada': fecha_str,
                    'factura_url': factura.archivo.url,
                    'es_pdf': es_pdf,
                    'raw_text': raw_text,
                },
            )
    else:
        form = FacturaProveedorForm()

    # === GET o POST inválido: mostrar formulario inicial + historial ===
    ultimas = FacturaProveedor.objects.all().order_by('-fecha_subida')[:5]
    return render(
        request,
        'pdf/procesar_factura.html',
        {
            'form': form,
            'ultimas_facturas': ultimas,
        }
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
