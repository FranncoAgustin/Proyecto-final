# cliente/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("carrito/", views.ver_carrito, name="ver_carrito"),
    path("carrito/agregar/<int:pk>/", views.agregar_al_carrito, name="agregar_al_carrito"),

    # ✅ mejor: path para permitir "59:0"
    path("carrito/eliminar/<path:item_key>/", views.eliminar_del_carrito, name="eliminar_del_carrito"),
    path("carrito/actualizar/<path:item_key>/", views.actualizar_cantidad, name="actualizar_cantidad"),

    path("carrito/vaciar/", views.vaciar_carrito, name="vaciar_carrito"),
    path("carrito/aplicar-cupon/", views.aplicar_cupon, name="aplicar_cupon"),

    path("favoritos/", views.mis_favoritos, name="mis_favoritos"),
    path("favoritos/agregar/<int:pk>/", views.agregar_favorito, name="agregar_favorito"),
    path("favoritos/eliminar/<int:pk>/", views.eliminar_favorito, name="eliminar_favorito"),

    path("mi-cuenta/", views.mi_cuenta, name="mi_cuenta"),
    path("mis-compras/", views.mis_compras, name="mis_compras"),
    path("mis-compras/<int:pedido_id>/", views.mis_compras_detalle, name="mis_compras_detalle"),

    path("mis-compras/<int:pedido_id>/continuar/", views.pedido_continuar_pago, name="pedido_continuar_pago"),
    path("mis-compras/<int:pedido_id>/cancelar/", views.pedido_cancelar, name="pedido_cancelar"),
    path("mis-compras/<int:pedido_id>/eliminar/", views.pedido_eliminar, name="pedido_eliminar"),
    path("logout/", views.logout_view, name="logout"),
]
