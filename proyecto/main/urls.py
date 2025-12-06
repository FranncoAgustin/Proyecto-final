from django.contrib import admin
from django.urls import path, include

from django.conf import settings
from django.conf.urls.static import static

from pdf import views as pdf_views
from owner.views import AdminDashboardView

urlpatterns = [
    # Panel de administración de Django
    path('admin/', admin.site.urls),

    # Incluye las URLs de la app pdf (por ejemplo detalle de producto, carrito, etc.)
    path('pdf/', include('pdf.urls')),    

    # Catálogo donde se listan todos los productos
    path('catalogo/', pdf_views.mostrar_precios, name='ver_catalogo_completo'),

    # Exportación del catálogo a CSV
    path('exportar/csv/', pdf_views.exportar_csv_catalogo, name='exportar_csv_catalogo'),

    # 🏠 Home = panel admin
    path('', AdminDashboardView.as_view(), name='home'),

    # URLs del owner (incluye historia_ingresos)
    path('owner/', include('owner.urls')),

    # Atajos
    path('catalogo/', pdf_views.mostrar_precios, name='ver_catalogo_completo_directo'),
    path('exportar/csv/', pdf_views.exportar_csv_catalogo, name='exportar_csv_catalogo_directo'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)




