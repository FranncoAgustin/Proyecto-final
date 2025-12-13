from django import forms
from .models import Oferta

class OfertaForm(forms.ModelForm):
    class Meta:
        model = Oferta
        fields = "__all__"
        widgets = {
            "fecha_inicio": forms.DateTimeInput(
                attrs={"type": "datetime-local"}
            ),
            "fecha_fin": forms.DateTimeInput(
                attrs={"type": "datetime-local"}
            ),
        }
