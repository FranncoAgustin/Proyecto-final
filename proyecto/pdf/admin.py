from django.contrib import admin
from .models import ProductoPrecio, ListaPrecioPDF

class ProductoPrecioAdmin(admin.ModelAdmin):
    list_display = ('sku', 'nombre_publico', 'precio')
    readonly_fields = ('sku', 'nombre_publico', 'precio')  
    def has_add_permission(self, request):
        return False  
    def has_delete_permission(self, request, obj=None):
        return False 

admin.site.register(ProductoPrecio, ProductoPrecioAdmin)
admin.site.register(ListaPrecioPDF)
