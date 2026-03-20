# cliente/urls.py
from django.urls import path
from pdf import views as pdf_views
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
    path("logout/", views.logout_view, name="logout"),
    path("carrito/whatsapp/", views.carrito_whatsapp, name="carrito_whatsapp"),
    path('catalogo/', pdf_views.mostrar_precios, name='catalogo'),
]
