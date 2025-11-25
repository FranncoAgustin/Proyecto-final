from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from .forms import ListaPrecioForm
from .models import ListaPrecioPDF, ProductoPrecio
from .utils import extraer_precios_de_pdf, get_similarity
import os
from django.db import IntegrityError
from decimal import Decimal

# --- Funciones de Utilidad (sin cambios) ---

def mostrar_precios(request):
    """Muestra el catálogo de precios actual de ProductoPrecio."""
    productos = ProductoPrecio.objects.all().order_by('nombre_publico')
    return render(request, 'pdf/mostrar_precios.html', {
        'productos': productos
    })

def exportar_csv_catalogo(request):
    """Exporta el catálogo completo (ProductoPrecio) a CSV."""
    import csv
    from django.http import HttpResponse

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="catalogo_final.csv"'

    writer = csv.writer(response)
    writer.writerow(['SKU', 'Nombre Público', 'Precio', 'Última Actualización'])
    
    for producto in ProductoPrecio.objects.all():
        writer.writerow([producto.sku, producto.nombre_publico, producto.precio, producto.ultima_actualizacion.strftime('%Y-%m-%d %H:%M')])

    return response

# --- VISTA PRINCIPAL (Fusiona los 3 pasos: Carga, Previsualización, Confirmación) ---

def importar_pdf(request):
    """Maneja los tres pasos: 1. Carga, 2. Previsualización/Decisión, 3. Confirmación."""
    
    msg = None
    
    # --- PASO 3: CONFIRMACIÓN Y ESCRITURA EN DB ---
    if request.method == 'POST' and 'confirm' in request.POST:
        
        # Recuperar datos de la sesión
        productos_a_revisar = request.session.pop('productos_a_revisar', [])
        lista_pdf_id = request.session.pop('lista_pdf_id', None)
        
        if not lista_pdf_id:
            msg = "Error: La sesión expiró o la lista no fue cargada correctamente."
            return render(request, 'pdf/importar_pdf.html', {'msg': msg})

        lista_pdf = get_object_or_404(ListaPrecioPDF, pk=lista_pdf_id)
        
        report = {
            'imported': 0,
            'updated': 0,
            'skipped': 0,
            'imported_items': [],
            'updated_items': [],
            'skipped_items': [],
        }

        for index, producto in enumerate(productos_a_revisar):
            
            # El nombre del campo es 'action_[indice]' en el nuevo template
            action_key = f'action_{index}' 
            accion_valor = request.POST.get(action_key)
            
            # Manejo de la acción (apply, ignore, merge:ID)
            accion = accion_valor.split(':')[0]
            target_id = accion_valor.split(':')[1] if ':' in accion_valor else None

            sku = producto['sku_original']
            precio_nuevo = Decimal(producto['precio_nuevo'])
            
            coincidencia_id = producto['coincidencia_id']
            coincidencia_exacta = coincidencia_id is not None
            
            item_reporte = {'sku': sku, 'currency': 'ARS', 'price': precio_nuevo}

            if accion == 'ignore':
                report['skipped'] += 1
                report['skipped_items'].append({'reason': 'Ignorado por usuario', 'sku': sku})
                continue
            
            if accion == 'apply' or accion.startswith('merge'):
                
                final_id = target_id if target_id else coincidencia_id
                
                # 1. ACTUALIZACIÓN / MERGE
                if final_id:
                    try:
                        prod_existente = ProductoPrecio.objects.get(pk=final_id)
                        prev_price = prod_existente.precio
                        
                        # Actualizar solo si hay cambio de precio
                        if prev_price != precio_nuevo:
                            prod_existente.precio = precio_nuevo
                            prod_existente.lista_pdf = lista_pdf
                            prod_existente.save()
                            report['updated'] += 1
                            item_reporte.update({'prev_price': prev_price, 'changed': True, 'note': f'Precio actualizado ({prev_price} -> {precio_nuevo})'})
                            report['updated_items'].append(item_reporte)
                        else:
                             report['skipped'] += 1
                             report['skipped_items'].append({'reason': 'Precio sin cambios', 'sku': sku})

                    except ProductoPrecio.DoesNotExist:
                        # Si se intentó unir pero el ID no existe (caso raro), lo ignoramos.
                        report['skipped'] += 1
                        report['skipped_items'].append({'reason': 'ID de merge no encontrado', 'sku': sku})
                        continue

                # 2. CREACIÓN (si es 'apply' y no hubo coincidencia)
                elif accion == 'apply' and not coincidencia_exacta:
                    try:
                        ProductoPrecio.objects.create(
                            lista_pdf=lista_pdf,
                            sku=sku,
                            nombre_publico=sku,
                            precio=precio_nuevo
                        )
                        report['imported'] += 1
                        item_reporte.update({'note': 'Producto nuevo creado'})
                        report['imported_items'].append(item_reporte)
                    except IntegrityError:
                        report['skipped'] += 1
                        report['skipped_items'].append({'reason': 'Error de unicidad SKU', 'sku': sku})
                        continue
        
        # Después de la confirmación, mostramos el reporte
        return render(request, 'pdf/importar_pdf.html', {'report': report})


    # --- PASO 1 y 2: CARGA Y PREVISUALIZACIÓN ---
    if request.method == 'POST':
        # Nota: El nuevo template usa 'file' y 'update_only' directamente en request.FILES/request.POST
        if 'file' in request.FILES:
            
            # El form de Django ya no es necesario para la carga, pero lo mantenemos si quieres validar
            # Usamos la carga manual para el archivo y el checkbox
            
            archivo_pdf = request.FILES['file']
            update_only = request.POST.get('update_only') == 'on'
            
            # Guardamos el archivo subido
            lista_pdf = ListaPrecioPDF.objects.create(nombre=archivo_pdf.name, archivo_pdf=archivo_pdf)
            pdf_path = os.path.join(settings.MEDIA_ROOT, lista_pdf.archivo_pdf.name)
            
            productos_extraidos = extraer_precios_de_pdf(pdf_path)
            
            # Preparar candidatos (candidates) para el template
            candidates = []
            skus_existentes = {p.sku: p for p in ProductoPrecio.objects.all()}

            for index, item in enumerate(productos_extraidos):
                sku_original = item['nombre']
                precio_nuevo = item['precio']
                
                # Búsqueda de coincidencias
                exact_match = skus_existentes.get(sku_original)
                sug_match = None
                max_similitud = 0
                
                # 2. Búsqueda por similitud (solo si no hay coincidencia exacta)
                if not exact_match:
                    for existing_sku, existing_product in skus_existentes.items():
                        similitud = get_similarity(sku_original, existing_sku)
                        
                        if similitud > max_similitud and similitud >= 70:
                            max_similitud = similitud
                            sug_match = existing_product

                # Prepara el objeto candidato (c) para el template
                c = {
                    'name': sku_original,
                    'price': precio_nuevo,
                    'currency': 'ARS', # Asumimos ARS por defecto
                    'dup_in_pdf': False, # Si no implementamos la detección de duplicados en PDF, lo ponemos en False
                    'exact_db_id': exact_match.id if exact_match else None,
                    'exact_db_label': exact_match.nombre_publico if exact_match else None,
                    'sug_id': sug_match.id if sug_match else None,
                    'sug_label': sug_match.nombre_publico if sug_match else None,
                    'sug_score': max_similitud,
                    'index': index # Usaremos el índice para referenciarlo en el POST
                }
                candidates.append(c)
                
                # 🌟 GUARDAMOS LOS DATOS EN LA SESIÓN PARA EL PASO DE CONFIRMACIÓN 🌟
                # Usamos el índice como clave temporal en la sesión para simplificar el POST
                item_session = {
                    'sku_original': sku_original,
                    'precio_nuevo': str(precio_nuevo),
                    'coincidencia_id': c['exact_db_id'] or c['sug_id'],
                }
                request.session[f'item_{index}'] = item_session
            
            # 🌟 Guardar la lista de candidatos en la sesión, mapeada al índice
            productos_a_revisar = []
            for c in candidates:
                productos_a_revisar.append({'sku_original': c['name'], 'precio_nuevo': str(c['price']), 'coincidencia_id': c['exact_db_id'] or c['sug_id']})
                
            request.session['productos_a_revisar'] = productos_a_revisar
            request.session['lista_pdf_id'] = lista_pdf.id

            # Mostrar la previsualización
            return render(request, 'pdf/importar_pdf.html', {
                'preview': True,
                'candidates': candidates,
                'update_only': update_only,
            })
            
    # Si es GET, simplemente renderiza el formulario de carga
    listas_procesadas = ListaPrecioPDF.objects.all().order_by('-fecha_subida')[:5] 
    
    return render(request, 'pdf/importar_pdf.html', {
        'listas_procesadas': listas_procesadas,
        'update_only': False
    })