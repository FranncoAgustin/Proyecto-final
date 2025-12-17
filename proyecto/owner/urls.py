# owner/urls.py

from django.urls import path

from .views import (
    AdminDashboardView,
    HistoriaIngresosView,
    historia_listas,
    historia_lista_detalle,
    owner_producto_editar,
    owner_producto_eliminar,
    owner_producto_toggle_activo,
    owner_productos_acciones_masivas,   # 👈 NUEVO
    owner_cupon_list,
    owner_cupon_create,
    owner_cupon_edit,
    owner_cupon_delete,
    owner_oferta_list, 
    owner_oferta_create, 
    owner_oferta_edit, 
    owner_oferta_delete,
    owner_producto_variantes,
    owner_variante_editar,
    owner_variante_eliminar,
    owner_producto_create_ui,
    owner_api_product_suggest,
    owner_api_product_detail,
    
)

urlpatterns = [
    path("", AdminDashboardView.as_view(), name="home"),
    path("productos/nuevo/", owner_producto_create_ui, name="owner_producto_create_ui"),
    path("api/product-suggest/", owner_api_product_suggest, name="owner_api_product_suggest"),
    path("api/product-detail/<int:pk>/", owner_api_product_detail, name="owner_api_product_detail"),


    path("historia/", HistoriaIngresosView.as_view(), name="historia_ingresos"),
    path("historia/listas/", historia_listas, name="historia_listas"),
    path("historia/listas/<int:lista_id>/", historia_lista_detalle, name="historia_lista_detalle"),

    path("producto/<int:pk>/editar/", owner_producto_editar, name="owner_producto_editar"),
    path("producto/<int:pk>/variantes/", owner_producto_variantes, name="owner_producto_variantes"),
    path("variantes/<int:variante_id>/editar/", owner_variante_editar, name="owner_variante_editar"),
    path("variantes/<int:variante_id>/eliminar/", owner_variante_eliminar, name="owner_variante_eliminar"),

    path("producto/<int:pk>/toggle-activo/", owner_producto_toggle_activo, name="owner_producto_toggle_activo"),
    path("producto/<int:pk>/eliminar/", owner_producto_eliminar, name="owner_producto_eliminar"),
    path("cupones/", owner_cupon_list, name="owner_cupon_list"),
    path("cupones/crear/", owner_cupon_create, name="owner_cupon_create"),
    path("cupones/<int:cupon_id>/editar/", owner_cupon_edit, name="owner_cupon_edit"),
    path("cupones/<int:cupon_id>/eliminar/", owner_cupon_delete, name="owner_cupon_delete"),
    path("ofertas/", owner_oferta_list, name="owner_oferta_list"),
    path("ofertas/crear/", owner_oferta_create, name="owner_oferta_create"),
    path("ofertas/<int:oferta_id>/editar/", owner_oferta_edit, name="owner_oferta_edit"),
    path("ofertas/<int:oferta_id>/eliminar/", owner_oferta_delete, name="owner_oferta_delete"),
    path("producto/acciones-masivas/",owner_productos_acciones_masivas,name="owner_productos_acciones_masivas",),
]

