# owner/forms.py
from django import forms
from django.forms import inlineformset_factory

from pdf.models import ProductoVariante, ProductoPrecio, Rubro, SubRubro


# =========================
# Rubros / Subrubros
# =========================
class RubroForm(forms.ModelForm):
    class Meta:
        model = Rubro
        fields = ["nombre", "tech", "orden", "activo"]


class SubRubroForm(forms.ModelForm):
    class Meta:
        model = SubRubro
        fields = ["rubro", "nombre", "orden", "activo"]


# =========================
# Producto principal
# =========================
class ProductoPrecioForm(forms.ModelForm):
    """
    Form básico para el producto. En los templates usás los campos sueltos,
    pero este form te sirve para validación si lo necesitás.
    """
    class Meta:
        model = ProductoPrecio
        fields = [
            "sku",
            "nombre_publico",
            "imagen",
            "precio",
            "descripcion",
            "stock",
            "precio_costo",
            "tech",
            "activo",
        ]
        widgets = {
            "sku": forms.TextInput(attrs={"class": "form-control"}),
            "nombre_publico": forms.TextInput(attrs={"class": "form-control"}),
            "imagen": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "precio": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "stock": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "precio_costo": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "tech": forms.Select(attrs={"class": "form-select"}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "descripcion": forms.Textarea(attrs={"rows": 3, "placeholder": "Descripción del producto (opcional)", }),
        }


# =========================
# Variantes (form clásico)
# =========================
class ProductoVarianteForm(forms.ModelForm):
    """
    Form usado por las vistas antiguas:
    - owner_producto_variantes
    - owner_variante_editar

    Lo dejamos para no romper nada, aunque ahora la idea es
    manejar variantes desde la pantalla unificada con el formset.
    """
    class Meta:
        model = ProductoVariante
        fields = ["nombre", "descripcion_corta", "imagen", "stock", "orden", "activo", "precio"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "descripcion_corta": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ej: Lapicera roja tinta negra"}
            ),
            "imagen": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "stock": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "orden": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "precio": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "placeholder": "Vacío = usa precio principal"}
            ),
        }


# =========================
# Variantes (inline formset)
# =========================
class ProductoVarianteInlineForm(forms.ModelForm):
    """
    Form para usar dentro del inline formset en la pantalla de producto.
    Este es el que se usa en owner_producto_editar con vformset.
    """
    class Meta:
        model = ProductoVariante
        fields = ["nombre", "descripcion_corta", "imagen", "stock", "precio"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej: Rojo, 400cc"}),
            "descripcion_corta": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Opcional: detalle corto"}
            ),
            "imagen": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "stock": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "precio": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "placeholder": "Vacío = usa precio principal"}
            ),
        }

    def clean_precio(self):
        # Permitimos vacío = "usa precio del producto"
        return self.cleaned_data.get("precio")


ProductoVarianteFormSet = inlineformset_factory(
    parent_model=ProductoPrecio,
    model=ProductoVariante,
    form=ProductoVarianteInlineForm,
    extra=0,        # arrancamos sin filas nuevas; las agrega el JS con empty_form
    can_delete=True,
)
