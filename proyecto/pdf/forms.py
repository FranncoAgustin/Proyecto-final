from django import forms
from .models import ListaPrecioPDF, FacturaProveedor

class ListaPrecioForm(forms.ModelForm):
    # Checkbox para decidir si solo se actualizan precios o se cargan nuevos productos
    actualizar_solo_precios = forms.BooleanField(
        required=False, 
        label="Solo actualizar precios (ignorar nuevos productos)"
    )
    
    class Meta:
        model = ListaPrecioPDF
        fields = ('nombre', 'archivo_pdf',)

# --- Nuevo formulario para la Confirmación ---

class ConfirmacionForm(forms.Form):
    # Campo oculto para llevar el ID de la lista
    lista_id = forms.IntegerField(widget=forms.HiddenInput())
    
    # Campos para cada producto: sku_original, accion
    # El action_{sku} puede ser: 'crear', 'actualizar_precio', 'ignorar'
    # Usaremos campos dinámicos en la vista.
    pass

class FacturaProveedorForm(forms.ModelForm):
    class Meta:
        model = FacturaProveedor
        fields = ('archivo',)
        widgets = {
            # Acepta imágenes y PDFs
            'archivo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*,.pdf'})
        }