from django.contrib import admin
from .models import ProductoPrecio, ListaPrecioPDF, ProductoVariante

@admin.register(ListaPrecioPDF)
class ListaPrecioPDFAdmin(admin.ModelAdmin):
    list_display = ("nombre", "fecha_subida")
    search_fields = ("nombre",)

@admin.register(ProductoPrecio)
class ProductoPrecioAdmin(admin.ModelAdmin):
    list_display = (
        "nombre_publico",
        "sku",
        "tech",
        "rubro",
        "subrubro",
        "precio",
        "stock",
        "activo",
        "ultima_actualizacion",
    )
    list_filter = ("tech", "rubro", "subrubro", "activo")
    search_fields = ("nombre_publico", "sku")
    list_editable = ("precio", "stock", "activo", "tech", "rubro", "subrubro")
    ordering = ("nombre_publico",)

@admin.register(ProductoVariante)
class ProductoVarianteAdmin(admin.ModelAdmin):
    list_display = ("producto", "nombre", "stock", "activo", "orden")
    list_filter = ("activo",)
    search_fields = ("producto__nombre_publico", "producto__sku", "nombre")
    list_editable = ("stock", "activo", "orden")
