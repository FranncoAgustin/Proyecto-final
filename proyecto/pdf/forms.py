from django import forms
from .models import ListaPrecioPDF, FacturaProveedor
from decimal import Decimal



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

class ListaPreciosPDFForm(forms.Form):
    TECH_CHOICES = [
        ("ALL", "Toda la base"),
        ("SUB", "Sublimación"),
        ("LAS", "Grabado láser"),
        ("3D",  "Impresión 3D"),
        ("OTR", "Otros"),
    ]

    tecnica = forms.ChoiceField(choices=TECH_CHOICES, initial="ALL", required=True)
    incluir_sku = forms.BooleanField(required=False, initial=True)

    # % de descuento mayorista (ej: 20 = -20%)
    descuento_mayorista = forms.DecimalField(
        required=True,
        initial=Decimal("20"),
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        decimal_places=2,
        max_digits=6,
        help_text="Ej: 20 = 20% de descuento"
    )

    # ✅ NUEVO: elegir si el PDF muestra lista mayorista (1 solo precio)
    lista_mayorista = forms.BooleanField(
        required=False,
        initial=False,
        label="Lista mayorista (mostrar precio mayorista)"
    )

    # ✅ NUEVO: marca de agua fija (solo se reemplaza si tildás esto)
    reemplazar_marca_agua = forms.BooleanField(
        required=False,
        initial=False,
        label="Reemplazar marca de agua guardada"
    )

    marca_agua = forms.ImageField(required=False, help_text="Opcional (PNG/JPG)")

    instagram_url = forms.URLField(
        required=False,
        initial="https://www.instagram.com/_mundo_personalizado/",
        label="Instagram (URL)"
    )
    whatsapp_url = forms.URLField(
        required=False,
        initial="https://wa.me/message/NSO7K5POCXLKE1",
        label="WhatsApp (URL)"
    )
    
class FacturaForm(forms.Form):
    # Cliente
    cliente_nombre = forms.CharField(label="Nombre del cliente", max_length=140)
    cliente_telefono = forms.CharField(label="Teléfono", max_length=60, required=False)
    cliente_doc = forms.CharField(label="DNI/CUIL", max_length=60, required=False)
    cliente_direccion = forms.CharField(label="Dirección", max_length=180, required=False)

    # Vendedor editable (precargado)
    vendedor_nombre = forms.CharField(max_length=120, required=True)
    vendedor_whatsapp = forms.CharField(max_length=50, required=True)
    vendedor_horario = forms.CharField(max_length=80, required=True)
    vendedor_direccion = forms.CharField(max_length=160, required=True)

    validez_dias = forms.IntegerField(label="Validez (días)", initial=7, min_value=1)
    sena = forms.DecimalField(label="Seña ($)", initial=Decimal("0.00"), required=False, min_value=Decimal("0.00"))