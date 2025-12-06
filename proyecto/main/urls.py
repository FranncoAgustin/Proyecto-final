from django.contrib import admin
from django.urls import path, include

# Importamos las vistas de la app 'pdf' y les damos un alias
from pdf import views as pdf_views 

urlpatterns = [
    # Panel de administración de Django
    path('admin/', admin.site.urls),

    # Página de inicio (usa la vista importar_pdf)
    path('', pdf_views.importar_pdf, name='home'),

    # Incluye las URLs de la app pdf (por ejemplo detalle de producto, carrito, etc.)
    path('pdf/', include('pdf.urls')),    

    # Catálogo donde se listan todos los productos
    path('catalogo/', pdf_views.mostrar_precios, name='ver_catalogo_completo'),

    # Exportación del catálogo a CSV
    path('exportar/csv/', pdf_views.exportar_csv_catalogo, name='exportar_csv_catalogo'),
]

from django.conf import settings
from django.conf.urls.static import static

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
