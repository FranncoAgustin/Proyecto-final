from django.urls import path
from . import views

urlpatterns = [
    # Importación de Listas de Precios
    path('importar/', views.importar_pdf, name='importar_pdf'),
    
    # Catálogo
    path('catalogo/', views.mostrar_precios, name='ver_catalogo_completo'),
    path('exportar/csv/', views.exportar_csv_catalogo, name='exportar_csv_catalogo'),
    
    # NOTA: Las rutas 'confirmar/' ya no son necesarias.

    path('detalle/<int:pk>/', views.detalle_producto, name='detalle_producto'),
    path('agregar/<int:pk>/', views.agregar_al_carrito, name='agregar_al_carrito'),

    # Procesamiento de Facturas (OCR)
    path('facturas/procesar/', views.procesar_factura, name='procesar_factura'),
    
    # 🌟 NUEVA RUTA PARA VERIFICACIÓN DINÁMICA 🌟
    # Esta es la ruta que usa el fetch en tu template
    path('api/verificar-producto/', views.verificar_producto_existente, name='verificar_producto'),

    path('historia/', views.historia_listas, name='historia_listas'),

    path("lista-precios.pdf", views.descargar_lista_precios_pdf, name="descargar_lista_precios_pdf"),

]
