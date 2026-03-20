# owner/forms.py
from django import forms
from django.forms import inlineformset_factory

from pdf.models import ProductoVariante, ProductoPrecio, Rubro, SubRubro
from django.forms import modelformset_factory
from .models import SiteCarouselImage, SiteInfoBlock, VentaRapida,SiteConfig

class SiteConfigForm(forms.ModelForm):
    class Meta:
        model = SiteConfig
        fields = [
            "primary_color", "secondary_color", "success_color", "danger_color",
            "muted_color",  # si lo tenés en el modelo
            "background", "surface", "text_color",
            "primary_rgb",  # si lo tenés en el modelo
            "font_base", "font_headings", "google_fonts_url",
            "texts",
        ]
        widgets = {
            # Colores como pickers, pero con clase para que se vean mejor
            "primary_color": forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color"}),
            "secondary_color": forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color"}),
            "success_color": forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color"}),
            "danger_color": forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color"}),
            "muted_color": forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color"}),
            "background": forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color"}),
            "surface": forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color"}),
            "text_color": forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color"}),

            "primary_rgb": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "13,110,253",
                }
            ),
            "font_base": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "Ej: 'Poppins', system-ui, sans-serif",
                }
            ),
            "font_headings": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "Ej: 'Poppins', system-ui, sans-serif",
                }
            ),
            "google_fonts_url": forms.URLInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "https://fonts.googleapis.com/…",
                }
            ),
            "texts": forms.Textarea(
                attrs={
                    "rows": 10,
                    "class": "form-control form-control-sm",
                }
            ),
        }


class SiteInfoBlockForm(forms.ModelForm):
    class Meta:
        model = SiteInfoBlock
        fields = ("clave", "titulo", "contenido", "orden", "activo")
        widgets = {
            "clave": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "p.ej. acerca-de",
                }
            ),
            "titulo": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "Título que ve el usuario",
                }
            ),
            "contenido": forms.Textarea(
                attrs={
                    "class": "form-control form-control-sm",
                    "rows": 4,
                    "placeholder": "Texto que se muestra al desplegar el bloque…",
                }
            ),
            "orden": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "min": "1",
                    "style": "max-width: 90px;",
                }
            ),
            # 'activo' lo ocultamos en el template (lo manejan los botones)
        }

    def clean(self):
        cleaned = super().clean()

        # Si está marcado para borrar, no validamos nada más
        if self.cleaned_data.get("DELETE"):
            return cleaned

        titulo = (cleaned.get("titulo") or "").strip()
        contenido = (cleaned.get("contenido") or "").strip()
        orden = cleaned.get("orden")

        if not titulo:
            self.add_error("titulo", "Poné un título para el bloque.")
        if not contenido:
            self.add_error("contenido", "El contenido no puede estar vacío.")
        if orden is None:
            self.add_error("orden", "Indicá un número de orden (1, 2, 3…).")
        elif orden < 1:
            self.add_error("orden", "El orden debe ser 1 o mayor.")

        return cleaned



SiteInfoBlockFormSet = modelformset_factory(
    SiteInfoBlock,
    form=SiteInfoBlockForm,
    extra=1,
    can_delete=True
)

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

class ProductoDesdeFacturaBulkForm(forms.ModelForm):
    """
    Form para completar productos recién creados desde factura.
    No incluye variantes.
    """
    class Meta:
        model = ProductoPrecio
        fields = [
            "sku",
            "nombre_publico",
            "descripcion",
            "precio",
            "precio_costo",
            "stock",
            "tech",
            "imagen",
            "activo",
        ]
        widgets = {
            "sku": forms.TextInput(attrs={"class": "form-control"}),
            "nombre_publico": forms.TextInput(attrs={"class": "form-control"}),
            "descripcion": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Descripción del producto (opcional)",
                }
            ),
            "precio": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "precio_costo": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "stock": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "tech": forms.Select(attrs={"class": "form-select"}),
            "imagen": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
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

class VentaRapidaForm(forms.ModelForm):
    producto = forms.ModelChoiceField(
        queryset=ProductoPrecio.objects.filter(activo=True).order_by("nombre_publico", "sku"),
        required=True,
        widget=forms.HiddenInput(),
    )

    variante = forms.ModelChoiceField(
        queryset=ProductoVariante.objects.filter(activo=True).select_related("producto").order_by("producto__nombre_publico", "nombre"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = VentaRapida
        fields = ["producto", "variante", "cantidad", "precio_unitario", "medio_pago", "observacion"]
        widgets = {
            "cantidad": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "precio_unitario": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "medio_pago": forms.Select(attrs={"class": "form-select"}),
            "observacion": forms.TextInput(attrs={"class": "form-control", "placeholder": "Opcional"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["variante"].queryset = ProductoVariante.objects.filter(activo=True).select_related("producto").order_by(
            "producto__nombre_publico", "nombre"
        )

    def clean_cantidad(self):
        cantidad = self.cleaned_data["cantidad"]
        if cantidad <= 0:
            raise forms.ValidationError("La cantidad debe ser mayor a 0.")
        return cantidad

    def clean_precio_unitario(self):
        precio = self.cleaned_data["precio_unitario"]
        if precio is None or precio < 0:
            raise forms.ValidationError("Ingresá un precio válido.")
        return precio

    def clean(self):
        cleaned = super().clean()
        producto = cleaned.get("producto")
        variante = cleaned.get("variante")

        if variante and producto and variante.producto_id != producto.id:
            self.add_error("variante", "La variante no pertenece al producto seleccionado.")

        return cleaned
    
class SiteCarouselImageForm(forms.ModelForm):
    class Meta:
        model = SiteCarouselImage
        fields = ["titulo", "imagen", "orden", "activo"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "imagen": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "orden": forms.NumberInput(attrs={"class": "form-control"}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

SiteCarouselImageFormSet = modelformset_factory(
    SiteCarouselImage,
    form=SiteCarouselImageForm,
    extra=1,
    can_delete=True,
)