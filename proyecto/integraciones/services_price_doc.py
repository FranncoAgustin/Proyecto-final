# integraciones/services_price_doc.py
import re
import requests
from io import BytesIO
from decimal import Decimal
from bs4 import BeautifulSoup

from django.db import transaction
from django.utils import timezone

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from pdf.models import ProductoPrecio
from pdf.utils import get_similarity

from .models import (
    PriceDocSource,
    PriceDocSnapshot,
    PriceDocItem,
    PriceUpdateCandidate,
)
from .utils_doc_precios import (
    crear_snapshot_desde_doc_json,
    crear_snapshot_desde_docx_bytes,
    crear_snapshot_desde_pdf_bytes,
)

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _build_drive_service(credentials):
    """
    Cliente para Google Drive API.
    """
    return build("drive", "v3", credentials=credentials)


def _build_docs_service(credentials):
    """
    Cliente para Google Docs API.
    """
    return build("docs", "v1", credentials=credentials)


def _download_drive_file_bytes(drive, file_id: str) -> bytes:
    """
    Descarga un archivo de Drive y devuelve su contenido en bytes.
    """
    buf = BytesIO()
    request_download = drive.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(buf, request_download)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    file_bytes = buf.getvalue()
    buf.close()
    return file_bytes


def _build_snapshot_from_source(source: PriceDocSource, drive, docs, mime_type: str) -> PriceDocSnapshot:
    """
    Crea el snapshot según el tipo real del archivo (Para Google Docs/Drive).
    """
    if mime_type == GOOGLE_DOC_MIME:
        doc_json = docs.documents().get(documentId=source.doc_id).execute()
        return crear_snapshot_desde_doc_json(source, doc_json)

    file_bytes = _download_drive_file_bytes(drive, source.doc_id)

    if mime_type == PDF_MIME:
        return crear_snapshot_desde_pdf_bytes(source, file_bytes)

    if mime_type == DOCX_MIME:
        return crear_snapshot_desde_docx_bytes(source, file_bytes)

    if source.tipo == "pdf":
        return crear_snapshot_desde_pdf_bytes(source, file_bytes)

    if source.tipo in {"docx_drive", "otro"}:
        return crear_snapshot_desde_docx_bytes(source, file_bytes)

    raise ValueError(f"Tipo de archivo no soportado. mime_type={mime_type!r}, source.tipo={source.tipo!r}")


def _build_snapshot_from_web_html(source: PriceDocSource) -> PriceDocSnapshot:
    """
    Scraper Multi-Motor Definitivo (Empretienda + WooCommerce).
    Con extracción avanzada de imágenes y auto-descubrimiento de CDN.
    """
    session = requests.Session()
    url_limpia = source.url.split('?')[0] if '?' in source.url else source.url
    base_domain = "/".join(url_limpia.split("/")[:3])
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    }
    
    snapshot = PriceDocSnapshot(source=source)
    snapshot.save() 
    
    items_unicos = {}
    html_content = ""
    
    try:
        resp_html = session.get(url_limpia, headers=headers, timeout=30)
        if resp_html.status_code != 200:
            snapshot.delete()
            return None
        html_content = resp_html.text
        soup_html = BeautifulSoup(html_content, "html.parser")
    except Exception as e:
        print(f"❌ Error cargando HTML: {e}")
        snapshot.delete()
        return None

    es_empretienda = "empretienda" in html_content.lower() or "v4/product" in html_content

    def limpiar_precio(texto):
        limpio = re.sub(r'[^\d,.]', '', texto).strip('.,')
        if not limpio: return Decimal('0')
        if '.' in limpio and ',' in limpio:
            limpio = limpio.replace('.', '').replace(',', '.')
        elif '.' in limpio:
            if len(limpio.split('.')[-1]) == 3: limpio = limpio.replace('.', '')
        elif ',' in limpio:
            if len(limpio.split(',')[-1]) == 3: limpio = limpio.replace(',', '')
            else: limpio = limpio.replace(',', '.')
        try: return Decimal(limpio)
        except: return Decimal('0')

    def obtener_url_imagen(contenedor):
        if not contenedor: return ""
        img_tag = contenedor.find('img')
        if not img_tag: return ""
        url = img_tag.get('data-src') or img_tag.get('data-lazy-src') or img_tag.get('src') or ""
        if url.startswith('//'): return 'https:' + url
        if url.startswith('/'): return base_domain + url
        return url

    if es_empretienda:
        # ---------------------------------------------------------
        # LÓGICA EMPRETIENDA
        # ---------------------------------------------------------
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Referer"] = url_limpia
        csrf_meta = soup_html.find("meta", {"name": "csrf-token"})
        if csrf_meta and csrf_meta.get("content"):
            headers["X-CSRF-TOKEN"] = csrf_meta["content"]
            
        # MAGIA DE CDN: Buscamos dónde guarda Empretienda las fotos de esta tienda
        base_img_url = ""
        match_base_img = re.search(r'(https?://[^\s"\'\,\]\}]+?/)[\w-]+\.(?:jpg|jpeg|png|webp)', html_content, re.I)
        if match_base_img:
            base_img_url = match_base_img.group(1) # Guardamos la ruta base (ej: https://cdn.../fotos/)
            
        precios_tags = soup_html.find_all(class_=re.compile(r'price|precio', re.I))
        for p_tag in precios_tags:
            precio_str = p_tag.get_text(strip=True)
            parent = p_tag.find_parent(['div', 'li', 'article', 'a'])
            if not parent: continue
            
            nombre_tag = parent.find(class_=re.compile(r'name|title|titulo', re.I))
            if not nombre_tag: nombre_tag = parent.find(['h2', 'h3']) 
            if not nombre_tag: continue

            nombre = nombre_tag.get_text(strip=True)
            precio_decimal = limpiar_precio(precio_str)
            imagen_url = obtener_url_imagen(parent)

            if precio_decimal > 0 and nombre:
                items_unicos[nombre] = PriceDocItem(
                    snapshot_id=snapshot.id, art=nombre[:120], producto=nombre,
                    compra=precio_decimal, descripcion=url_limpia, imagen_url=imagen_url[:255]
                )
                
        cat_id = None
        if source.doc_id and source.doc_id.strip().isdigit(): cat_id = source.doc_id.strip()
        else:
            match = re.search(r'filter_categories(?:%5B%5D|\[\])=([\d]{5,})', html_content)
            if match: cat_id = match.group(1)
            else:
                match2 = re.search(r'category_id["\']?\s*[:=]\s*["\']?([\d]{5,})', html_content, re.I)
                if match2: cat_id = match2.group(1)

        if cat_id:
            for page in range(1, 10):
                api_url = f"{base_domain}/v4/product/category?filter_page={page}&filter_order=4&filter_categories%5B%5D={cat_id}"
                try:
                    res = session.get(api_url, headers=headers, timeout=15)
                    if res.status_code != 200: break
                    data = res.json()
                    lista = []
                    if isinstance(data, list): lista = data
                    elif isinstance(data, dict):
                        if isinstance(data.get("data"), list): lista = data.get("data")
                        elif isinstance(data.get("data"), dict) and isinstance(data["data"].get("data"), list): lista = data["data"].get("data")
                    
                    if not lista: break
                    
                    for prod in lista:
                        if not isinstance(prod, dict): continue
                        nombre = prod.get("p_nombre") or prod.get("name") or prod.get("title") or ""
                        precio_decimal = limpiar_precio(str(prod.get("p_precio") or prod.get("price") or 0))

                        # ========================================================
                        # EXTRACCIÓN CON CDN DINÁMICO
                        # ========================================================
                        img_api = ""
                        imagenes_list = prod.get("imagenes", [])
                        if isinstance(imagenes_list, list) and len(imagenes_list) > 0:
                            primera_imagen = imagenes_list[0]
                            if isinstance(primera_imagen, dict):
                                img_filename = primera_imagen.get("i_link", "")
                                if img_filename:
                                    # Armamos la foto perfecta uniendo el CDN + el nombre del archivo
                                    if base_img_url:
                                        img_api = base_img_url + img_filename
                                    else:
                                        img_api = f"{base_domain}/{img_filename}"
                        # ========================================================

                        if precio_decimal > 0 and nombre:
                            if nombre not in items_unicos:
                                items_unicos[nombre] = PriceDocItem(
                                    snapshot_id=snapshot.id, art=nombre[:120], producto=nombre,
                                    compra=precio_decimal, descripcion=url_limpia, imagen_url=img_api[:255]
                                )
                except Exception: break

    else:
        # ---------------------------------------------------------
        # LÓGICA WORDPRESS WOOCOMMERCE
        # ---------------------------------------------------------
        def extraer_filas(sopa, url_origen):
            for tag in sopa(['script', 'style']): tag.decompose()
            filas = sopa.find_all('tr')
            for fila in filas:
                textos_validos = [t for t in fila.stripped_strings if len(t) > 5 and '$' not in t and 'stock' not in t.lower() and 'carrito' not in t.lower() and 'añadir' not in t.lower() and 'comprar' not in t.lower()]
                if not textos_validos: continue
                nombre = textos_validos[0] 
                precios_str = re.findall(r'\$\s*[\d.,]+', fila.get_text())
                if not precios_str: continue
                precio_decimal = limpiar_precio(precios_str[-1])
                imagen_url = obtener_url_imagen(fila)

                if precio_decimal > 0:
                    if nombre not in items_unicos:
                        items_unicos[nombre] = PriceDocItem(
                            snapshot_id=snapshot.id, art=nombre[:120], 
                            producto=nombre, compra=precio_decimal, descripcion=url_origen, imagen_url=imagen_url[:255]
                        )

        extraer_filas(soup_html, url_limpia)
        botones_acordeon = soup_html.find_all(class_=re.compile(r'smg-accordion-header', re.I))
        ajax_url = f"{base_domain}/wp-admin/admin-ajax.php"
        headers_ajax = headers.copy()
        headers_ajax["X-Requested-With"] = "XMLHttpRequest"
        headers_ajax["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        
        for boton in botones_acordeon:
            table_id = boton.get('data-table')
            if table_id:
                payload = {'action': 'smg_ajax_product_table', 'table_id': table_id}
                try:
                    res_ajax = session.post(ajax_url, data=payload, headers=headers_ajax, timeout=20)
                    if res_ajax.status_code == 200: extraer_filas(BeautifulSoup(res_ajax.text, "html.parser"), url_limpia)
                except Exception: continue

    if items_unicos:
        PriceDocItem.objects.bulk_create(items_unicos.values())
        return snapshot
    else:
        snapshot.delete()
        return None


def sync_price_doc_and_build_candidates(source: PriceDocSource, credentials) -> tuple[int, PriceDocSnapshot | None]:
    """
    Sincroniza la lista de precios de una fuente.
    Deriva la lógica si es Web Scraping o si es Google Drive.
    """
    
    # ==========================================
    # 1. OBTENCIÓN DEL ARCHIVO / SCRAPING
    # ==========================================
    if source.tipo == "web_html":
        if not source.url:
            raise ValueError(f"La fuente '{source.nombre}' no tiene una URL configurada.")
        
        # Hacemos scraping y generamos un timestamp como "revisión virtual"
        snapshot_new = _build_snapshot_from_web_html(source)
        revision = timezone.now().isoformat()
    
    else:
        if not source.doc_id or source.doc_id.strip().lower() == "legacy":
            raise ValueError(f"La fuente '{source.nombre}' no tiene un doc_id válido.")

        drive = _build_drive_service(credentials)
        docs = _build_docs_service(credentials)

        meta = drive.files().get(
            fileId=source.doc_id,
            fields="id, name, modifiedTime, headRevisionId, mimeType",
        ).execute()

        revision = meta.get("headRevisionId") or meta.get("modifiedTime") or ""
        mime_type = meta.get("mimeType") or ""

        # Si la revisión es la misma, abortamos (no hubo cambios en el Doc)
        if source.last_revision_id == revision:
            source.last_modified_time = source.last_modified_time or timezone.now()
            source.save(update_fields=["last_modified_time"])
            return 0, None

        snapshot_new = _build_snapshot_from_source(source, drive, docs, mime_type)

    # ==========================================
    # 2. COMPARACIÓN CON SNAPSHOT ANTERIOR
    # ==========================================
    snapshot_old = (
        PriceDocSnapshot.objects
        .filter(source=source)
        .exclude(pk=snapshot_new.pk)
        .order_by("-creado_en")
        .first()
    )

    source.last_modified_time = timezone.now()
    source.last_revision_id = revision
    source.save(update_fields=["last_modified_time", "last_revision_id"])

    if not snapshot_old:
        return 0, snapshot_new

    old_by_art = {item.art.strip(): item for item in snapshot_old.items.all() if (item.art or "").strip()}
    new_by_art = {item.art.strip(): item for item in snapshot_new.items.all() if (item.art or "").strip()}

    cambios = []
    for art, new_item in new_by_art.items():
        old_item = old_by_art.get(art)
        if not old_item or new_item.compra == old_item.compra:
            continue
        cambios.append((art, old_item, new_item))

    # ==========================================
    # 3. GENERACIÓN DE CANDIDATOS (MATCH BD)
    # ==========================================
    skus_db = list(
        ProductoPrecio.objects
        .filter(activo=True)
        .values("id", "sku", "nombre_publico", "precio")
    )

    from decimal import Decimal as _D

    with transaction.atomic():
        count = 0

        for art, old_item, new_item in cambios:
            match_prod = None
            match_sku = ""
            match_score = None
            art_norm = (art or "").strip()

            # Match exacto por SKU / Nombre
            for p in skus_db:
                sku = (p.get("sku") or "").strip()
                if not sku:
                    continue
                if sku.lower() == art_norm.lower():
                    match_prod = ProductoPrecio(id=p["id"])
                    match_sku = sku
                    match_score = _D("100.0")
                    break

            # Fuzzy Match
            if not match_prod:
                best = None
                best_score = 0
                for p in skus_db:
                    sku = (p.get("sku") or "").strip()
                    if not sku: continue

                    score = get_similarity(art_norm, sku)
                    if score > best_score:
                        best_score = score
                        best = p

                if best and best_score >= 90:
                    match_prod = ProductoPrecio(id=best["id"])
                    match_sku = (best.get("sku") or "").strip()
                    match_score = _D(str(best_score))

            cand, _ = PriceUpdateCandidate.objects.get_or_create(
                source=source,
                art=art,
                old_compra=old_item.compra,
                new_compra=new_item.compra,
                defaults={
                    "producto_doc": new_item.producto,
                    "descripcion_doc": new_item.descripcion,
                },
            )

            cand.producto_doc = new_item.producto
            cand.descripcion_doc = new_item.descripcion

            if match_prod:
                cand.producto = ProductoPrecio.objects.get(pk=match_prod.id)
                cand.sku_match = match_sku
                cand.match_score = match_score
                cand.calcular_sugerencia()
            else:
                cand.producto = None
                cand.sku_match = ""
                cand.match_score = None
                cand.venta_actual = None
                cand.venta_sugerida = None
                cand.pct_aumento_venta = None

            cand.save()
            count += 1

    return count, snapshot_new


def sync_all_price_sources(credentials, only_active=True):
    """ Sincroniza todas las fuentes de precios. """
    qs = PriceDocSource.objects.all().order_by("id")

    if only_active and hasattr(PriceDocSource, "activo"):
        qs = qs.filter(activo=True)

    resultados = []
    total_cambios = 0
    procesadas = 0

    for source in qs:
        try:
            cambios, snapshot = sync_price_doc_and_build_candidates(
                source=source,
                credentials=credentials,
            )

            total_cambios += cambios
            procesadas += 1

            resultados.append({
                "source_id": source.id,
                "source_nombre": str(source),
                "ok": True,
                "cambios": cambios,
                "snapshot_id": snapshot.id if snapshot else None,
                "error": None,
            })

        except Exception as e:
            procesadas += 1
            resultados.append({
                "source_id": source.id,
                "source_nombre": str(source),
                "ok": False,
                "cambios": 0,
                "snapshot_id": None,
                "error": str(e),
            })

    return {
        "total_fuentes": qs.count(),
        "procesadas": procesadas,
        "total_cambios": total_cambios,
        "resultados": resultados,
    }


def sync_price_source_by_id(source_id: int, credentials):
    """ Helper para sincronizar una fuente puntual por ID. """
    source = PriceDocSource.objects.get(pk=source_id)
    return sync_price_doc_and_build_candidates(source=source, credentials=credentials)