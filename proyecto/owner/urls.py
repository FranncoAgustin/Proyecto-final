# owner/urls.py

from django.urls import path

import owner.views_theme

from .views import (
    AdminDashboardView,
    owner_producto_editar,
    owner_producto_eliminar,
    owner_producto_toggle_activo,
    owner_productos_acciones_masivas,
    owner_cupon_list,
    owner_cupon_create,
    owner_cupon_edit,
    owner_cupon_delete,
    owner_oferta_list,
    owner_oferta_create,
    owner_oferta_edit,
    owner_oferta_delete,
    owner_producto_create_ui,
    owner_api_product_suggest,
    owner_api_product_detail,
    owner_rubros_list,
    owner_rubro_create,
    owner_subrubro_create,
    owner_filtros_panel,
    owner_api_rubro_create,
    owner_api_subrubro_create,
    owner_autorubros,
    owner_siteinfo_list,
    owner_siteconfig_edit,
    owner_historia_global,

)

urlpatterns = [
    path("", AdminDashboardView.as_view(), name="home"),

    # ✅ SOLO ESTA ruta para alta de producto
    path("productos/nuevo/", owner_producto_create_ui, name="owner_producto_create_ui"),

    path("api/product-suggest/", owner_api_product_suggest, name="owner_api_product_suggest"),
    path("api/product-detail/<int:pk>/", owner_api_product_detail, name="owner_api_product_detail"),

    path("producto/<int:pk>/editar/", owner_producto_editar, name="owner_producto_editar"),
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

    path(
        "producto/acciones-masivas/",
        owner_productos_acciones_masivas,
        name="owner_productos_acciones_masivas",
    ),

    path("rubros/", owner_rubros_list, name="owner_rubros_list"),
    path("rubros/nuevo/", owner_rubro_create, name="owner_rubro_create"),
    path("subrubros/nuevo/", owner_subrubro_create, name="owner_subrubro_create"),

    path("owner/filtros/", owner_filtros_panel, name="owner_filtros_panel"),
    path("owner/api/rubro/create/", owner_api_rubro_create, name="owner_api_rubro_create"),
    path("owner/api/subrubro/create/", owner_api_subrubro_create, name="owner_api_subrubro_create"),

    path("filtros/auto-asignar/", owner_autorubros, name="owner_autorubros"),
    path("owner/info-sitio/", owner_siteinfo_list, name="owner_siteinfo_list"),

    path("theme.css", owner.views_theme.theme_css, name="theme_css"),
    path("owner/site-config/", owner_siteconfig_edit, name="owner_siteconfig_edit"),
     path("historia/", owner_historia_global, name="owner_historia_global"),
]