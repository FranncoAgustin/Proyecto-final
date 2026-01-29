# integraciones/views.py
import logging
import requests

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

INSTAGRAM_CACHE_KEY = "instagram_media_cache"


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
    # Primero probamos cache para no pegarle todo el tiempo a Instagram
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
        # Para videos usamos el thumbnail si existe
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

    # Cacheamos un rato para no sobrecargar la API
    cache_timeout = getattr(settings, "INSTAGRAM_CACHE_SECONDS", 1800)
    cache.set(INSTAGRAM_CACHE_KEY, media, cache_timeout)

    return media
