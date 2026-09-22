from django import forms
from .models import PriceDocSource, ScrapingProveedor

class PriceDocSourceForm(forms.ModelForm):
    class Meta:
        model = PriceDocSource
        fields = [
            "nombre", "url", "doc_id", "tipo", 
            "activo", "orden", "es_principal",
        ]
        widgets = {
            "nombre": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ej: Lista proveedor sublimación",
            }),
            "url": forms.URLInput(attrs={
                "class": "form-control",
                "placeholder": "https://docs.google.com/document/d/...",
            }),
            "doc_id": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "ID del archivo en Google Drive / Google Docs",
            }),
            "tipo": forms.Select(attrs={
                "class": "form-select",
            }),
            "activo": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
            "orden": forms.NumberInput(attrs={
                "class": "form-control",
                "min": "0",
            }),
            "es_principal": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
        }

    def clean_doc_id(self):
        doc_id = (self.cleaned_data.get("doc_id") or "").strip()
        if not doc_id:
            raise forms.ValidationError("Tenés que ingresar el doc_id.")
        return doc_id

    def clean_nombre(self):
        nombre = (self.cleaned_data.get("nombre") or "").strip()
        if not nombre:
            raise forms.ValidationError("Tenés que ingresar un nombre para la fuente.")
        return nombre

    def clean(self):
        cleaned_data = super().clean()
        url = (cleaned_data.get("url") or "").strip()
        doc_id = (cleaned_data.get("doc_id") or "").strip()

        # Si no cargan URL pero sí doc_id, está bien.
        # Si cargan URL y no doc_id, avisamos.
        if url and not doc_id:
            self.add_error("doc_id", "Si cargás una URL, también necesitás el doc_id.")
        return cleaned_data


# -------------------------------
# FORMULARIOS PARA SCRAPING
# -------------------------------

class ScrapingProveedorForm(forms.ModelForm):
    class Meta:
        model = ScrapingProveedor
        fields = ["nombre", "url", "activo", "metodo"]
        widgets = {
            "nombre": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ej: Bleu Diseño",
            }),
            "url": forms.URLInput(attrs={
                "class": "form-control",
                "placeholder": "https://bleudiseno.empretienda.com.ar",
            }),
            "activo": forms.CheckboxInput(attrs={
                "class": "form-check-input role-switch",
            }),
            "metodo": forms.Select(attrs={
                "class": "form-select",
            }),
        }

    def clean_nombre(self):
        nombre = (self.cleaned_data.get("nombre") or "").strip()
        if not nombre:
            raise forms.ValidationError("El nombre del proveedor es obligatorio.")
        return nombre

    def clean(self):
        cleaned_data = super().clean()
        url = (cleaned_data.get("url") or "").strip()
        doc_id = (cleaned_data.get("doc_id") or "").strip()
        tipo = cleaned_data.get("tipo")

        if tipo != "web_html" and not doc_id:
            self.add_error("doc_id", "Para archivos de Drive/Docs necesitás el doc_id.")
        
        if tipo == "web_html" and not url:
            self.add_error("url", "Para scraping web necesitás ingresar la URL.")

        return cleaned_data