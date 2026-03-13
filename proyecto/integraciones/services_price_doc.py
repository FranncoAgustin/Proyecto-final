# integraciones/services_price_doc.py
from io import BytesIO

from django.db import transaction
from django.utils import timezone

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from pdf.models import ProductoPrecio
from pdf.utils import get_similarity

from .models import (
    PriceDocSource,
    PriceDocSnapshot,
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
    (Solo se usa si el archivo es un documento de Google nativo).
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


def _build_snapshot_from_source(
    source: PriceDocSource,
    drive,
    docs,
    mime_type: str,
) -> PriceDocSnapshot:
    """
    Crea el snapshot según el tipo real del archivo.
    """
    if mime_type == GOOGLE_DOC_MIME:
        doc_json = docs.documents().get(documentId=source.doc_id).execute()
        return crear_snapshot_desde_doc_json(source, doc_json)

    file_bytes = _download_drive_file_bytes(drive, source.doc_id)

    if mime_type == PDF_MIME:
        return crear_snapshot_desde_pdf_bytes(source, file_bytes)

    if mime_type == DOCX_MIME:
        return crear_snapshot_desde_docx_bytes(source, file_bytes)

    # Fallback:
    # si el tipo no vino bien pero en el modelo el usuario marcó pdf/docx,
    # intentamos según source.tipo
    if source.tipo == "pdf":
        return crear_snapshot_desde_pdf_bytes(source, file_bytes)

    if source.tipo in {"docx_drive", "otro"}:
        return crear_snapshot_desde_docx_bytes(source, file_bytes)

    raise ValueError(
        f"Tipo de archivo no soportado. mime_type={mime_type!r}, source.tipo={source.tipo!r}"
    )


def sync_price_doc_and_build_candidates(
    source: PriceDocSource,
    credentials,
) -> tuple[int, PriceDocSnapshot | None]:
    """
    Sincroniza la lista de precios de una fuente.

    La fuente puede ser:
    - Google Doc nativo
    - DOCX subido a Drive
    - PDF subido a Drive

    Flujo:
    - Consulta metadata en Drive
    - Si la revisión no cambió -> devuelve (0, None)
    - Si cambió:
        - crea snapshot nuevo
        - compara con snapshot anterior
        - genera/actualiza candidatos de cambio
        - devuelve (cantidad_cambios, snapshot_nuevo)
    """
    if not source.doc_id or source.doc_id.strip().lower() == "legacy":
        raise ValueError(
            f"La fuente '{source.nombre}' no tiene un doc_id válido."
        )

    drive = _build_drive_service(credentials)
    docs = _build_docs_service(credentials)

    # 1) Metadata del archivo
    meta = drive.files().get(
        fileId=source.doc_id,
        fields="id, name, modifiedTime, headRevisionId, mimeType",
    ).execute()

    revision = meta.get("headRevisionId") or meta.get("modifiedTime") or ""
    mime_type = meta.get("mimeType") or ""

    # Si la revisión es la misma, no hacemos nada
    if source.last_revision_id == revision:
        source.last_modified_time = source.last_modified_time or timezone.now()
        source.save(update_fields=["last_modified_time"])
        return 0, None

    # 2) Crear snapshot nuevo según el tipo de archivo
    snapshot_new = _build_snapshot_from_source(
        source=source,
        drive=drive,
        docs=docs,
        mime_type=mime_type,
    )

    # 3) Buscar snapshot anterior
    snapshot_old = (
        PriceDocSnapshot.objects
        .filter(source=source)
        .exclude(pk=snapshot_new.pk)
        .order_by("-creado_en")
        .first()
    )

    # Actualizar metadata en la fuente
    source.last_modified_time = timezone.now()
    source.last_revision_id = revision
    source.save(update_fields=["last_modified_time", "last_revision_id"])

    # Primera sincronización: no hay comparación todavía
    if not snapshot_old:
        return 0, snapshot_new

    # 4) Armar diccionarios ART -> item
    old_by_art = {}
    for item in snapshot_old.items.all():
        art = (item.art or "").strip()
        if art:
            old_by_art[art] = item

    new_by_art = {}
    for item in snapshot_new.items.all():
        art = (item.art or "").strip()
        if art:
            new_by_art[art] = item

    cambios = []

    # Solo nos interesan ART que siguen existiendo y cambiaron compra
    for art, new_item in new_by_art.items():
        old_item = old_by_art.get(art)
        if not old_item:
            continue

        if new_item.compra == old_item.compra:
            continue

        cambios.append((art, old_item, new_item))

    # 5) Traer productos activos para match
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

            # Match exacto por SKU
            for p in skus_db:
                sku = (p.get("sku") or "").strip()
                if not sku:
                    continue

                if sku.lower() == art_norm.lower():
                    match_prod = ProductoPrecio(id=p["id"])
                    match_sku = sku
                    match_score = _D("100.0")
                    break

            # Si no hubo match exacto, fuzzy >= 90
            if not match_prod:
                best = None
                best_score = 0

                for p in skus_db:
                    sku = (p.get("sku") or "").strip()
                    if not sku:
                        continue

                    score = get_similarity(art_norm, sku)
                    if score > best_score:
                        best_score = score
                        best = p

                if best and best_score >= 90:
                    match_prod = ProductoPrecio(id=best["id"])
                    match_sku = (best.get("sku") or "").strip()
                    match_score = _D(str(best_score))

            # Crear o actualizar candidato
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

            # Siempre refrescamos datos del documento
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
    """
    Sincroniza todas las fuentes de precios.

    Devuelve:
    {
        "total_fuentes": int,
        "procesadas": int,
        "total_cambios": int,
        "resultados": [
            {
                "source_id": ...,
                "source_nombre": ...,
                "ok": True/False,
                "cambios": int,
                "snapshot_id": int|None,
                "error": str|None,
            }
        ]
    }
    """
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
    """
    Helper para sincronizar una fuente puntual por ID.
    """
    source = PriceDocSource.objects.get(pk=source_id)
    return sync_price_doc_and_build_candidates(source=source, credentials=credentials)