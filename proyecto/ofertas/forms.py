from django import forms
from .models import Oferta


TECNICAS_CHOICES = [
    ("SUB", "Sublimación"),
    ("LAS", "Láser"),
    ("3D", "Impresión 3D"),
    ("OTR", "Otras"),
]


class OfertaForm(forms.ModelForm):
    tecnicas = forms.MultipleChoiceField(
        choices=TECNICAS_CHOICES,
        required=False,
        widget=forms.SelectMultiple(attrs={
            "class": "form-select",
            "size": 4,
        }),
        label="Técnicas",
        help_text="Si no seleccionás ninguna, aplica a todas",
    )

    class Meta:
        model = Oferta
        fields = [
            "nombre",
            "tipo_descuento",
            "valor",
            "tecnicas",
            "fecha_inicio",
            "fecha_fin",
            "activo",
        ]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "tipo_descuento": forms.Select(attrs={"class": "form-select"}),
            "valor": forms.NumberInput(attrs={"class": "form-control"}),
            "fecha_inicio": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"}
            ),
            "fecha_fin": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"}
            ),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_tecnicas(self):
        return self.cleaned_data.get("tecnicas", [])
