from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Profile


class RegistroForm(UserCreationForm):
    first_name = forms.CharField(label="Nombre", max_length=30)
    last_name = forms.CharField(label="Apellido", max_length=30)
    email = forms.EmailField(label="Email")
    telefono = forms.CharField(
        label="Teléfono",
        max_length=20,
        help_text="+54 11 ... (solo números)",
    )
    localidad = forms.CharField(label="Localidad", max_length=100)

    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "email",
            "telefono",
            "localidad",
            "password1",
            "password2",
        )

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Ya existe un usuario con este email.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        email = self.cleaned_data["email"].lower()

        # usamos el email como username
        user.username = email
        user.email = email
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]

        if commit:
            user.save()
            profile = user.profile  # lo crea el signal
            profile.telefono = self.cleaned_data["telefono"]
            profile.localidad = self.cleaned_data["localidad"]
            profile.save()
        return user

class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["telefono", "localidad", "avatar"]
        labels = {
            "telefono": "Teléfono",
            "localidad": "Localidad",
            "avatar": "Foto de perfil",
        }
        widgets = {
            "telefono": forms.TextInput(attrs={"placeholder": "+54 11 ..."}),
        }
