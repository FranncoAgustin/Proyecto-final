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

class FacturaProveedorForm(forms.ModelForm):
    class Meta:
        model = FacturaProveedor
        fields = ('archivo',)
        widgets = {
            # El widget 'accept' ayuda al navegador a filtrar archivos (solo PDF)
            'archivo': forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf'})
        }