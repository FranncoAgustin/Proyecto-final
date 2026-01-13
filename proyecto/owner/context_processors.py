from .models import SiteInfoBlock
from .models import SiteConfig

def siteinfo_blocks(request):
    """
    Agrega a todos los templates los bloques de info del sitio.
    """
    bloques = SiteInfoBlock.objects.filter(activo=True).order_by("orden", "titulo")
    return {"siteinfo_blocks": bloques}

def site_cfg(request):
    return {"site_cfg": SiteConfig.get_solo()}