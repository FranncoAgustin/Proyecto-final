from django.urls import path
from . import views

urlpatterns = [
    # Paso 1, 2 y 3: Carga, Previsualización y Reporte (Todo en una URL)
    path('importar/', views.importar_pdf, name='importar_pdf'),
    
    # Catálogo final (Muestra el modelo ProductoPrecio)
    path('catalogo/', views.mostrar_precios, name='ver_catalogo_completo'),
    
    # Exportación del catálogo completo
    path('exportar/csv/', views.exportar_csv_catalogo, name='exportar_csv_catalogo'),
    
    # NOTA: Las rutas 'confirmar/' ya no son necesarias.

    path('detalle/<int:pk>/', views.detalle_producto, name='detalle_producto'),
    path('agregar/<int:pk>/', views.agregar_al_carrito, name='agregar_al_carrito'),
]