from integraciones.views import fetch_instagram_media

def instagram_feed(request):
    """
    Agrega 'instagram_media' al contexto de todos los templates.
    """
    return {
        "instagram_media": fetch_instagram_media()
    }