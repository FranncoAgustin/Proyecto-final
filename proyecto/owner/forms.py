# owner/forms.py
from django import forms
from pdf.models import ProductoVariante, ProductoPrecio
from django.forms import inlineformset_factory


class ProductoVarianteForm(forms.ModelForm):
    class Meta:
        model = ProductoVariante
        fields = ["nombre", "descripcion_corta", "imagen", "stock", "orden", "activo"]
        widgets = {
            "descripcion_corta": forms.TextInput(attrs={"placeholder": "Ej: Lapicera roja tinta negra"}),
        }

class ProductoPrecioForm(forms.ModelForm):
    class Meta:
        model = ProductoPrecio
        fields = [
            "sku",
            "nombre_publico",
            "imagen",
            "precio",
            "stock",
            "tech",
            "activo",
            # opcionales:
            "precio_costo",
            "descripcion",   # <-- solo si lo agregaste
        ]
        widgets = {
            "sku": forms.TextInput(attrs={"class": "form-control"}),
            "nombre_publico": forms.TextInput(attrs={"class": "form-control"}),
            "imagen": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "precio": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "stock": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "tech": forms.Select(attrs={"class": "form-select"}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "precio_costo": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

VarianteFormSet = inlineformset_factory(
    ProductoPrecio,
    ProductoVariante,
    fields=("nombre", "descripcion_corta", "imagen", "stock", "orden", "activo"),
    extra=2,
    can_delete=True,
    widgets={
        "nombre": forms.TextInput(attrs={"class": "form-control"}),
        "descripcion_corta": forms.TextInput(attrs={"class": "form-control"}),
        "imagen": forms.ClearableFileInput(attrs={"class": "form-control"}),
        "stock": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        "orden": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
    }
)

class ProductoPrecioForm(forms.ModelForm):
    class Meta:
        model = ProductoPrecio
        fields = ["sku", "nombre_publico", "imagen", "precio", "stock", "precio_costo", "tech", "activo"]
        widgets = {
            "sku": forms.TextInput(attrs={"class": "form-control"}),
            "nombre_publico": forms.TextInput(attrs={"class": "form-control"}),
            "imagen": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "precio": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "stock": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "precio_costo": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "tech": forms.Select(attrs={"class": "form-select"}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

ProductoVarianteFormSet = inlineformset_factory(
    ProductoPrecio,
    ProductoVariante,
    fields=("nombre", "descripcion_corta", "imagen", "stock", "orden", "activo"),
    extra=2,
    can_delete=True,
    widgets={
        "nombre": forms.TextInput(attrs={"class": "form-control"}),
        "descripcion_corta": forms.TextInput(attrs={"class": "form-control"}),
        "imagen": forms.ClearableFileInput(attrs={"class": "form-control"}),
        "stock": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        "orden": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
    }
)