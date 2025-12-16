import os
from pathlib import Path

import dj_database_url  # pip install dj-database-url

BASE_DIR = Path(__file__).resolve().parent.parent

# ==============================
# SECURITY
# ==============================
SECRET_KEY = os.getenv("SECRET_KEY", "dev-insegura-solo-local")
DEBUG = os.getenv("DEBUG", "False") == "True"

# Render usa dominio *.onrender.com
ALLOWED_HOSTS = ["localhost", "127.0.0.1", ".onrender.com"]

# Para que CSRF no te tire 403 en Render / ngrok
CSRF_TRUSTED_ORIGINS = [
    "https://*.onrender.com",
    "https://*.ngrok-free.app",
]

# Si usás HTTPS en Render (sí), esto ayuda:
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ==============================
# APPLICATIONS
# ==============================
INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",

    # Allauth
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",

    # Libs
    "widget_tweaks",

    # Apps propias
    "pdf",
    "owner",
    "cliente",
    "cupones",
    "dashboard",
    "integraciones",
    "ofertas",
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# En producción lo ideal es SITE_ID=1 (y configurarlo en Admin > Sites)
#SITE_ID = int(os.getenv("SITE_ID", "1"))
SITE_ID = 3

LOGIN_REDIRECT_URL = "/mi-cuenta/"
LOGOUT_REDIRECT_URL = "/ver_catalogo_completo/"
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_EMAIL_VERIFICATION = os.getenv("ACCOUNT_EMAIL_VERIFICATION", "none")
SOCIALACCOUNT_AUTO_SIGNUP = True

# ==============================
# MIDDLEWARE
# ==============================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # <-- importante en Render
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ==============================
# URLS / SERVER
# ==============================
ROOT_URLCONF = "main.urls"
WSGI_APPLICATION = "main.wsgi.application"

# ==============================
# TEMPLATES
# ==============================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "cliente.context_processors.carrito_y_favoritos",
            ],
        },
    },
]

# ==============================
# DATABASE
# - En Render: usa DATABASE_URL (Postgres)
# - En local: cae a sqlite si no existe DATABASE_URL
# ==============================
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

# ==============================
# AUTH PASSWORDS
# ==============================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ==============================
# INTERNATIONALIZATION
# ==============================
LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_I18N = True
USE_TZ = True

# ==============================
# STATIC FILES
# ==============================
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Si tenés /static en desarrollo:
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

# WhiteNoise (mejor compresión/cache)
#STORAGES = {
#    "staticfiles": {
#        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
#    }
#}

# ==============================
# MEDIA FILES
# ==============================
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ==============================
# SECURITY MISC
# ==============================
X_FRAME_OPTIONS = "SAMEORIGIN"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ==============================
# MERCADOPAGO
# ==============================
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")
