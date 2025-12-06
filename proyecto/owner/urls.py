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
)

urlpatterns = [
    path("", AdminDashboardView.as_view(), name="admin_panel"),

    path("historia/", HistoriaIngresosView.as_view(), name="historia_ingresos"),
    path("historia/listas/", historia_listas, name="historia_listas"),
    path("historia/listas/<int:lista_id>/", historia_lista_detalle, name="historia_lista_detalle"),

    path("producto/<int:pk>/editar/", owner_producto_editar, name="owner_producto_editar"),
    path("producto/<int:pk>/toggle-activo/", owner_producto_toggle_activo, name="owner_producto_toggle_activo"),
    path("producto/<int:pk>/eliminar/", owner_producto_eliminar, name="owner_producto_eliminar"),

    # 👇 NUEVO endpoint para acciones masivas
    path(
        "producto/acciones-masivas/",
        owner_productos_acciones_masivas,
        name="owner_productos_acciones_masivas",
    ),
]

