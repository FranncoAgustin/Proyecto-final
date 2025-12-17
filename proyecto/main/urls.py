from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from django.views.generic import RedirectView
from pdf import views as pdf_views

urlpatterns = [
    # =======================
    # HOME PÚBLICA -> CATÁLOGO
    # =======================
    # Cuando entren a "/", los mando al catálogo completo
    path(
        "",
        RedirectView.as_view(pattern_name="ver_catalogo_completo", permanent=False),
        name="home_publica",
    ),

    # Panel de administración de Django
    path("admin/", admin.site.urls),

    # URLs de pdf (detalle producto, etc.)
    path("pdf/", include("pdf.urls")),

    # URLs de cliente (login, registro, mi cuenta, carrito, etc.)
    # /login/, /registro/, /mi-cuenta/, etc.
    path("", include("cliente.urls")),

    # URLs de allauth (Google, etc.)
    path("accounts/", include("allauth.urls")),
    path("login/",    RedirectView.as_view(pattern_name="account_login",  permanent=False), name="login"),
    path("registro/", RedirectView.as_view(pattern_name="account_signup", permanent=False), name="registro"),

    # Catálogo donde se listan todos los productos
    path("catalogo/", pdf_views.mostrar_precios, name="ver_catalogo_completo"),


    # URLs del owner (panel admin, historia ingresos, etc.)
    path("owner/", include("owner.urls")),

    path("integraciones/", include("integraciones.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
