import os
import mercadopago
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url  # 👈 para DATABASE_URL

# ==============================
# BASE
# ==============================
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

# ==============================
# CLAVES / ENV
# ==============================
# En producción (Render) poné SECRET_KEY en variables de entorno
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "django-insecure-l^&=+p0jlju3o40u3q0$=6tsy+_(g3k^!4y(j!%53*+0o3lq^=",
)

DEBUG = os.getenv("DEBUG", "True") == "True"

MP_PUBLIC_KEY = os.getenv("MP_PUBLIC_KEY", "")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")
MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "")
SITE_URL = os.getenv("SITE_URL", "http://127.0.0.1:8000")

# Render setea esto automáticamente
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")

# ==============================
# SECURITY / HOSTS
# ==============================
ALLOWED_HOSTS = [
    "127.0.0.1",
    "localhost",
    "petronila-irremovable-abnormally.ngrok-free.dev",
]

if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

CSRF_TRUSTED_ORIGINS = [
    "https://*.ngrok-free.dev",
    "https://petronila-irremovable-abnormally.ngrok-free.dev",
    # opcional: si alguna vez usás el dominio viejo de ngrok
    "https://*.ngrok.io",
]

if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

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
    "django.contrib.sites",  # <-- NECESARIO para allauth / Sites
    "django.contrib.humanize",

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

SITE_ID = 3

LOGIN_REDIRECT_URL = "/mi-cuenta/"
LOGOUT_REDIRECT_URL = "/catalogo/"
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_EMAIL_VERIFICATION = "none"  # en dev
SOCIALACCOUNT_AUTO_SIGNUP = True
# SOCIALACCOUNT_ADAPTER = "cliente.adapters.MySocialAccountAdapter"

# ==============================
# MIDDLEWARE
# ==============================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # 👈 AGREGAR
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
# TEMPLATES (BASE GLOBAL)
# ==============================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "cliente.context_processors.carrito_y_favoritos",
                "owner.context_processors.siteinfo_blocks",
                "owner.context_processors.site_cfg",
            ],
        },
    },
]

# ==============================
# DATABASE
# ==============================
# En local (sin DATABASE_URL) → SQLite
# En Render (con DATABASE_URL) → Postgres de Render
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
STATICFILES_DIRS = [BASE_DIR / "static"]

# Para Render: donde se juntan los estáticos con collectstatic
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise para producción
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ==============================
# MEDIA FILES (PDFs, imágenes)
# ==============================
MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# ==============================
# SECURITY EXTRA
# ==============================
X_FRAME_OPTIONS = "SAMEORIGIN"

# ==============================
# DEFAULT MODEL
# ==============================
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Para que Django reconozca https detrás del proxy (ngrok / render)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Para que allauth construya URLs con https
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"

# (recomendado con proxies)
USE_X_FORWARDED_HOST = True
