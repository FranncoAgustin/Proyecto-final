from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class MySocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Adapter para que allauth haga auto-signup con Google
    sin mostrar la pantalla /3rdparty/signup/,
    siempre que tengamos un email.
    """

    def is_auto_signup_allowed(self, request, sociallogin):
        # Usuario "provisorio" que viene del provider
        user = sociallogin.user

        # Asegurarnos de tener email (de Google)
        email = user.email or sociallogin.account.extra_data.get("email")
        if not email:
            # Si el provider no da email, que muestre el formulario
            return False

        # Forzamos que el email quede en el user local
        user.email = email

        # Si querés, podés pisar nombre/apellido:
        # user.first_name = sociallogin.account.extra_data.get("given_name", "")
        # user.last_name = sociallogin.account.extra_data.get("family_name", "")

        # Decimos a allauth: "Sí, podés crear el usuario sin pedir más datos"
        return True
