from .models import SiteInfoBlock

def siteinfo_blocks(request):
    """
    Agrega a todos los templates los bloques de info del sitio.
    """
    bloques = SiteInfoBlock.objects.filter(activo=True).order_by("orden", "titulo")
    return {"siteinfo_blocks": bloques}
