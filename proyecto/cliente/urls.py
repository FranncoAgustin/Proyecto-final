# cliente/urls.py
from django.urls import path

from . import views

urlpatterns = [
    # Carrito
    path("carrito/", views.ver_carrito, name="ver_carrito"),
    path("carrito/agregar/<int:pk>/", views.agregar_al_carrito, name="agregar_al_carrito"),
    path("carrito/eliminar/<int:pk>/", views.eliminar_del_carrito, name="eliminar_del_carrito"),
    path("carrito/actualizar/<int:pk>/", views.actualizar_cantidad, name="actualizar_cantidad"),
    path("carrito/vaciar/", views.vaciar_carrito, name="vaciar_carrito"),
    path("carrito/aplicar-cupon/", views.aplicar_cupon, name="aplicar_cupon"),


    # Favoritos
    path("favoritos/", views.mis_favoritos, name="mis_favoritos"),
    path("favoritos/agregar/<int:pk>/", views.agregar_favorito, name="agregar_favorito"),
    path("favoritos/eliminar/<int:pk>/", views.eliminar_favorito, name="eliminar_favorito"),

    # Cuenta
    path("mi-cuenta/", views.mi_cuenta, name="mi_cuenta"),
    path("mis-compras/", views.mis_compras, name="mis_compras"),
    path("logout/", views.logout_view, name="logout"),
]
