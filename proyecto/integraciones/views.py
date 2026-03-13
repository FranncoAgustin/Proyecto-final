# integraciones/views.py
from decimal import Decimal
import logging
import os
import requests

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from google.oauth2 import service_account

from owner.models import BitacoraEvento
from pdf.models import ProductoPrecio
from pdf.utils import get_similarity

from .forms import PriceDocSourceForm
from .models import PriceDocSource, PriceDocSnapshot, PriceUpdateCandidate, Q2
from .services_price_doc import (
    sync_all_price_sources,
    sync_price_doc_and_build_candidates,
    sync_price_source_by_id,
)

logger = logging.getLogger(__name__)
INSTAGRAM_CACHE_KEY = "instagram_media_cache"


def _get_google_credentials():
    """
    Carga las credenciales del service account
    y loguea/imprime el email que se está usando.
    """
    key_path = os.path.join(settings.BASE_DIR, "credenciales", "service_account.json")
    scopes = [
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/documents.readonly",
    ]
    credentials = service_account.Credentials.from_service_account_file(
        key_path,
        scopes=scopes,
    )

    sa_email = getattr(credentials, "service_account_email", "desconocido")
    logger.info("SERVICE ACCOUNT EMAIL: %s", sa_email)
    print("SERVICE ACCOUNT EMAIL:", sa_email)

    return credentials


def _build_drive_url_from_doc_id(doc_id: str, tipo: str) -> str:
    """
    Construye una URL útil a partir del doc_id.
    """
    if not doc_id:
        return ""

    if tipo == "google_sheet":
        return f"https://docs.google.com/spreadsheets/d/{doc_id}/edit"

    if tipo == "pdf":
        return f"https://drive.google.com/file/d/{doc_id}/view"

    return f"https://docs.google.com/document/d/{doc_id}/edit"


def _ensure_source_url(source: PriceDocSource):
    """
    Si la fuente no tiene URL pero sí doc_id, la completa.
    """
    if not source.url and source.doc_id:
        source.url = _build_drive_url_from_doc_id(source.doc_id, source.tipo)
        source.save(update_fields=["url"])


def _get_selected_source_or_default(source_id=None):
    """
    Devuelve una fuente puntual o la principal / primera disponible.
    """
    if source_id is not None:
        return get_object_or_404(PriceDocSource, pk=source_id)

    return (
        PriceDocSource.objects.filter(es_principal=True).first()
        or PriceDocSource.objects.filter(activo=True).order_by("orden", "nombre").first()
        or PriceDocSource.objects.order_by("orden", "nombre").first()
    )


def _build_match_result_for_art(art: str, skus_db: list[dict]):
    """
    Devuelve el resultado del match para un ART de la lista contra ProductoPrecio.
    """
    art_norm = (art or "").strip()
    if not art_norm:
        return {
            "producto": None,
            "sku_match": "",
            "match_score": None,
            "estado_match": "sin_match",
        }

    # Match exacto
    for p in skus_db:
        sku = (p.get("sku") or "").strip()
        if not sku:
            continue
        if sku.lower() == art_norm.lower():
            return {
                "producto": p,
                "sku_match": sku,
                "match_score": Decimal("100.00"),
                "estado_match": "exacto",
            }

    # Fuzzy
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
        return {
            "producto": best,
            "sku_match": (best.get("sku") or "").strip(),
            "match_score": Decimal(str(best_score)).quantize(Q2),
            "estado_match": "fuzzy",
        }

    return {
        "producto": None,
        "sku_match": "",
        "match_score": None,
        "estado_match": "sin_match",
    }


@login_required
def price_sources_list(request):
    """
    Lista todas las fuentes de precios.
    """
    sources = PriceDocSource.objects.all().order_by("orden", "nombre")
    return render(
        request,
        "integraciones/price_sources_list.html",
        {
            "sources": sources,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def price_source_create(request):
    """
    Crea una nueva fuente de lista de precios.
    """
    if request.method == "POST":
        form = PriceDocSourceForm(request.POST)
        if form.is_valid():
            source = form.save(commit=False)

            if not source.url and source.doc_id:
                source.url = _build_drive_url_from_doc_id(source.doc_id, source.tipo)

            if request.user.is_authenticated:
                source.creado_por = request.user
                source.actualizado_por = request.user

            source.save()
            messages.success(request, "La fuente de precios se creó correctamente.")
            return redirect("price_sources_list")
    else:
        form = PriceDocSourceForm()

    return render(
        request,
        "integraciones/price_source_form.html",
        {
            "form": form,
            "titulo": "Nueva fuente de precios",
            "source": None,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def price_source_edit(request, pk):
    """
    Edita una fuente existente.
    """
    source = get_object_or_404(PriceDocSource, pk=pk)

    if request.method == "POST":
        form = PriceDocSourceForm(request.POST, instance=source)
        if form.is_valid():
            source = form.save(commit=False)

            if not source.url and source.doc_id:
                source.url = _build_drive_url_from_doc_id(source.doc_id, source.tipo)

            if request.user.is_authenticated:
                source.actualizado_por = request.user

            source.save()
            messages.success(request, "La fuente de precios se actualizó correctamente.")
            return redirect("price_sources_list")
    else:
        form = PriceDocSourceForm(instance=source)

    return render(
        request,
        "integraciones/price_source_form.html",
        {
            "form": form,
            "titulo": f"Editar fuente: {source.nombre}",
            "source": source,
        },
    )


@login_required
@require_http_methods(["POST"])
def price_source_toggle(request, pk):
    """
    Activa o desactiva una fuente.
    """
    source = get_object_or_404(PriceDocSource, pk=pk)
    source.activo = not source.activo

    if request.user.is_authenticated:
        source.actualizado_por = request.user

    source.save(update_fields=["activo", "actualizado_por", "actualizado_en"])
    estado = "activada" if source.activo else "desactivada"
    messages.success(request, f"La fuente '{source.nombre}' fue {estado}.")
    return redirect("price_sources_list")


@login_required
@require_http_methods(["POST"])
def price_source_delete(request, pk):
    """
    Elimina una fuente.
    """
    source = get_object_or_404(PriceDocSource, pk=pk)
    nombre = source.nombre
    source.delete()
    messages.success(request, f"La fuente '{nombre}' fue eliminada.")
    return redirect("price_sources_list")


@login_required
@require_http_methods(["POST"])
def price_source_sync(request, pk):
    """
    Sincroniza una fuente puntual.
    """
    source = get_object_or_404(PriceDocSource, pk=pk)
    credentials = None

    try:
        _ensure_source_url(source)
        credentials = _get_google_credentials()
        cambios, snapshot = sync_price_source_by_id(source.id, credentials)

        source.ultima_revision = timezone.now()
        source.ultimo_estado = "ok"
        source.ultimo_error = ""
        if request.user.is_authenticated:
            source.actualizado_por = request.user
        source.save(update_fields=["ultima_revision", "ultimo_estado", "ultimo_error", "actualizado_por", "actualizado_en"])

        if cambios > 0:
            messages.success(
                request,
                f"Fuente '{source.nombre}' sincronizada. Cambios detectados: {cambios}."
            )
        else:
            hay_snapshots = PriceDocSnapshot.objects.filter(source=source).exists()
            if hay_snapshots:
                messages.info(
                    request,
                    f"Fuente '{source.nombre}' sincronizada sin cambios de precios."
                )
            else:
                messages.info(
                    request,
                    f"Se creó el snapshot inicial de '{source.nombre}'. "
                    "Los cambios se detectarán desde la próxima modificación."
                )

    except Exception as e:
        sa_email = getattr(credentials, "service_account_email", "desconocido") if credentials else "desconocido"

        source.ultima_revision = timezone.now()
        source.ultimo_estado = "error"
        source.ultimo_error = str(e)
        if request.user.is_authenticated:
            source.actualizado_por = request.user
        source.save(update_fields=["ultima_revision", "ultimo_estado", "ultimo_error", "actualizado_por", "actualizado_en"])

        messages.error(
            request,
            f"No se pudo sincronizar '{source.nombre}' "
            f"(service account: {sa_email}): {e}"
        )

    return redirect("price_sources_list")


@login_required
@require_http_methods(["POST"])
def price_sources_sync_all(request):
    """
    Sincroniza todas las fuentes activas.
    """
    credentials = None

    try:
        credentials = _get_google_credentials()
        resultado = sync_all_price_sources(credentials, only_active=True)

        sources_map = {
            s.id: s for s in PriceDocSource.objects.filter(
                id__in=[r["source_id"] for r in resultado["resultados"]]
            )
        }

        ahora = timezone.now()

        for item in resultado["resultados"]:
            source = sources_map.get(item["source_id"])
            if not source:
                continue

            source.ultima_revision = ahora
            if item["ok"]:
                source.ultimo_estado = "ok"
                source.ultimo_error = ""
            else:
                source.ultimo_estado = "error"
                source.ultimo_error = item["error"] or ""

            if request.user.is_authenticated:
                source.actualizado_por = request.user

            source.save(update_fields=["ultima_revision", "ultimo_estado", "ultimo_error", "actualizado_por", "actualizado_en"])

        messages.success(
            request,
            f"Se procesaron {resultado['procesadas']} fuentes. "
            f"Cambios detectados: {resultado['total_cambios']}."
        )

    except Exception as e:
        sa_email = getattr(credentials, "service_account_email", "desconocido") if credentials else "desconocido"
        messages.error(
            request,
            f"No se pudieron sincronizar las fuentes "
            f"(service account: {sa_email}): {e}"
        )

    return redirect("price_sources_list")


@login_required
@require_http_methods(["GET", "POST"])
def gestionar_cambios_doc_precios(request, source_id=None):
    """
    Vista principal para revisar y aplicar cambios detectados.
    Si viene source_id, muestra esa fuente.
    Si no viene, usa la principal o la primera activa.
    """
    source = _get_selected_source_or_default(source_id=source_id)

    if not source:
        messages.warning(
            request,
            "Todavía no hay fuentes de precios cargadas. Primero creá una fuente."
        )
        return redirect("price_sources_list")

    _ensure_source_url(source)

    if request.method == "POST":
        ids_aplicar = [
            int(x) for x in request.POST.getlist("candidato_id") if x.isdigit()
        ]

        candidatos = PriceUpdateCandidate.objects.filter(
            source=source,
            pk__in=ids_aplicar,
            aplicado=False,
            producto__isnull=False,
        )

        aplicados = 0
        detalles_evento = []

        with transaction.atomic():
            for c in candidatos.select_related("producto"):
                prod = c.producto
                if not prod or c.venta_sugerida is None:
                    continue

                precio_anterior = prod.precio or Decimal("0.00")
                prod.precio = c.venta_sugerida.quantize(Q2)
                prod.save(update_fields=["precio"])

                c.aprobado = True
                c.aplicado = True
                c.aplicado_en = timezone.now()
                c.save(update_fields=["aprobado", "aplicado", "aplicado_en"])

                aplicados += 1
                detalles_evento.append({
                    "producto_id": prod.id,
                    "sku": prod.sku,
                    "nombre": prod.nombre_publico,
                    "precio_anterior": str(precio_anterior),
                    "precio_nuevo": str(prod.precio),
                    "old_compra": str(c.old_compra),
                    "new_compra": str(c.new_compra),
                })

        if aplicados > 0:
            BitacoraEvento.objects.create(
                usuario=request.user if request.user.is_authenticated else None,
                tipo="doc_precios_aplicado",
                titulo=f"Actualización de precios desde lista ({aplicados} artículos).",
                detalle=f"Se aplicaron {aplicados} cambios de precio desde '{source.nombre}'.",
                obj_model="integraciones.PriceDocSource",
                obj_id=str(source.pk),
                extra={"items": detalles_evento},
            )

        messages.success(request, f"Se aplicaron {aplicados} cambios de precio.")
        return redirect("gestionar_cambios_doc_precios_source", source_id=source.pk)

    credentials = None
    try:
        credentials = _get_google_credentials()
        n_cambios, snapshot = sync_price_doc_and_build_candidates(source, credentials)

        source.ultima_revision = timezone.now()
        source.ultimo_estado = "ok"
        source.ultimo_error = ""
        if request.user.is_authenticated:
            source.actualizado_por = request.user
        source.save(update_fields=["ultima_revision", "ultimo_estado", "ultimo_error", "actualizado_por", "actualizado_en"])

        if n_cambios > 0:
            messages.info(request, f"Detectados {n_cambios} cambios nuevos en '{source.nombre}'.")
        else:
            hay_snapshots = PriceDocSnapshot.objects.filter(source=source).exists()
            if hay_snapshots:
                messages.info(
                    request,
                    f"Sincronización OK para '{source.nombre}'. "
                    "No se detectaron cambios de precios."
                )
            else:
                messages.info(
                    request,
                    f"Se creó el snapshot inicial de '{source.nombre}'. "
                    "Los cambios se van a detectar desde la próxima modificación."
                )

    except Exception as e:
        sa_email = getattr(credentials, "service_account_email", "desconocido") if credentials else "desconocido"

        source.ultima_revision = timezone.now()
        source.ultimo_estado = "error"
        source.ultimo_error = str(e)
        if request.user.is_authenticated:
            source.actualizado_por = request.user
        source.save(update_fields=["ultima_revision", "ultimo_estado", "ultimo_error", "actualizado_por", "actualizado_en"])

        messages.error(
            request,
            f"No se pudo sincronizar '{source.nombre}' "
            f"(service account: {sa_email}): {e}"
        )

    candidatos = (
        PriceUpdateCandidate.objects
        .filter(source=source, aplicado=False)
        .select_related("producto")
        .order_by("-creado_en")
    )

    sources = PriceDocSource.objects.all().order_by("orden", "nombre")

    return render(
        request,
        "integraciones/gestionar_cambios_doc_precios.html",
        {
            "source": source,
            "sources": sources,
            "candidatos": candidatos,
        },
    )


@login_required
def diagnostico_match_lista(request, source_id=None):
    """
    Muestra el último snapshot de una fuente y cómo matchea cada ART
    contra ProductoPrecio por SKU exacto o fuzzy.
    """
    source = _get_selected_source_or_default(source_id=source_id)

    if not source:
        messages.warning(
            request,
            "Todavía no hay fuentes de precios cargadas. Primero creá una fuente."
        )
        return redirect("price_sources_list")

    _ensure_source_url(source)

    snapshot = (
        PriceDocSnapshot.objects
        .filter(source=source)
        .prefetch_related("items")
        .order_by("-creado_en")
        .first()
    )

    sources = PriceDocSource.objects.all().order_by("orden", "nombre")

    if not snapshot:
        messages.info(
            request,
            f"La fuente '{source.nombre}' todavía no tiene snapshots. Sincronizala primero."
        )
        return render(
            request,
            "integraciones/price_source_match_diagnostico.html",
            {
                "source": source,
                "sources": sources,
                "snapshot": None,
                "rows": [],
                "resumen": {
                    "total_items": 0,
                    "exactos": 0,
                    "fuzzy": 0,
                    "sin_match": 0,
                },
            },
        )

    skus_db = list(
        ProductoPrecio.objects
        .filter(activo=True)
        .values("id", "sku", "nombre_publico", "precio")
    )

    rows = []
    exactos = 0
    fuzzy = 0
    sin_match = 0

    for item in snapshot.items.all():
        match = _build_match_result_for_art(item.art, skus_db)

        if match["estado_match"] == "exacto":
            exactos += 1
        elif match["estado_match"] == "fuzzy":
            fuzzy += 1
        else:
            sin_match += 1

        rows.append({
            "item": item,
            "producto_db": match["producto"],
            "sku_match": match["sku_match"],
            "match_score": match["match_score"],
            "estado_match": match["estado_match"],
        })

    resumen = {
        "total_items": len(rows),
        "exactos": exactos,
        "fuzzy": fuzzy,
        "sin_match": sin_match,
    }

    return render(
        request,
        "integraciones/price_source_match_diagnostico.html",
        {
            "source": source,
            "sources": sources,
            "snapshot": snapshot,
            "rows": rows,
            "resumen": resumen,
        },
    )


def fetch_instagram_media():
    """
    Devuelve una lista de posts recientes de Instagram listos para usar en templates.
    Usa la Instagram Basic Display API con un access token definido en settings.

    Cada ítem de la lista tiene:
    - id
    - image_url
    - permalink
    - caption
    - timestamp
    """
    media = cache.get(INSTAGRAM_CACHE_KEY)
    if media is not None:
        return media

    access_token = getattr(settings, "INSTAGRAM_ACCESS_TOKEN", "")
    limit = getattr(settings, "INSTAGRAM_MEDIA_LIMIT", 8)

    if not access_token:
        logger.warning("INSTAGRAM_ACCESS_TOKEN no configurado")
        return []

    url = "https://graph.instagram.com/me/media"
    params = {
        "fields": "id,caption,media_type,media_url,permalink,thumbnail_url,timestamp",
        "access_token": access_token,
        "limit": limit,
    }

    try:
        resp = requests.get(url, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except Exception as e:
        logger.error("Error al consultar Instagram: %s", e, exc_info=True)
        return []

    media = []
    for item in data:
        media_type = item.get("media_type")
        if media_type == "VIDEO":
            image_url = item.get("thumbnail_url") or item.get("media_url")
        else:
            image_url = item.get("media_url")

        if not image_url:
            continue

        media.append(
            {
                "id": item.get("id"),
                "image_url": image_url,
                "permalink": item.get("permalink"),
                "caption": item.get("caption", ""),
                "timestamp": item.get("timestamp", ""),
            }
        )

    cache_timeout = getattr(settings, "INSTAGRAM_CACHE_SECONDS", 1800)
    cache.set(INSTAGRAM_CACHE_KEY, media, cache_timeout)

    return media
