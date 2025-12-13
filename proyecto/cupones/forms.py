from django import forms
from .models import Cupon

class CuponForm(forms.ModelForm):
    class Meta:
        model = Cupon
        fields = [
            "codigo",
            "descuento",
            "usos_maximos",
            "fecha_inicio",
            "fecha_fin",
            "activo",
        ]

        widgets = {
            "fecha_inicio": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "fecha_fin": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
