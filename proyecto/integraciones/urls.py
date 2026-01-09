from django.urls import path
from . import views

urlpatterns = [
    path("mp/crear-preferencia/", views.mp_crear_preferencia, name="mp_crear_preferencia"),
    path("mp/webhook/", views.mp_webhook, name="mp_webhook"),
    path("mp/success/", views.mp_success, name="mp_success"),
    path("mp/pending/", views.mp_pending, name="mp_pending"),
    path("mp/failure/", views.mp_failure, name="mp_failure"),
]