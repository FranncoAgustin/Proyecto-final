# owner/forms.py
from django import forms
from pdf.models import ProductoVariante

class ProductoVarianteForm(forms.ModelForm):
    class Meta:
        model = ProductoVariante
        fields = ["nombre", "descripcion_corta", "imagen", "stock", "orden", "activo"]
        widgets = {
            "descripcion_corta": forms.TextInput(attrs={"placeholder": "Ej: Lapicera roja tinta negra"}),
        }
