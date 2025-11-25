from django.contrib import admin
from django.urls import path, include
# Importamos las vistas de la aplicación 'pdf' y le damos un alias 'pdf_views'
from pdf import views as pdf_views 

# La línea 'from . import views' causaba conflicto y se elimina si solo necesitas vistas de 'pdf'.
# Si necesitas vistas de la carpeta actual del proyecto (main), usa un alias.

urlpatterns = [
    path('admin/', admin.site.urls),

    # Usa el alias 'pdf_views' para la vista de inicio.
    path('', pdf_views.importar_pdf, name='home'), 

    path('pdf/', include('pdf.urls')),

    # Usa el alias 'pdf_views' para las vistas de catálogo y exportación.
    path('catalogo/', pdf_views.mostrar_precios, name='ver_catalogo_completo'), 

    path('exportar/csv/', pdf_views.exportar_csv_catalogo, name='exportar_csv_catalogo'),
]