# cliente/models.py
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    telefono = models.CharField(max_length=20, blank=True)
    localidad = models.CharField(max_length=100, blank=True)

    # verificación
    email_verified = models.BooleanField(default=False)
    phone_verified = models.BooleanField(default=False)

    # NUEVO: avatar / foto de perfil
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.username

    

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    # Si el usuario se acaba de crear -> creo el perfil
    if created:
        Profile.objects.create(user=instance)
    else:
        # Para usuarios que ya existían (admin, etc):
        # si no hay profile, lo creo; si existe, lo uso
        Profile.objects.get_or_create(user=instance)