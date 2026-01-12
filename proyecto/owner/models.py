from django.db import models
from django.utils.text import slugify
from django.conf import settings


class ProductoPrecio(models.Model):
    # ⚠ SIN FK a ListaPrecioPDF acá
    sku = models.CharField(max_length=255, unique=True)
    nombre_publico = models.CharField(max_length=255)
    precio = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return self.nombre_publico


class SiteInfoBlock(models.Model):
    site = models.ForeignKey(
        "SiteConfig",
        on_delete=models.CASCADE,
        related_name="info_blocks",
    )

    clave = models.CharField(
        "Clave interna",
        max_length=80,
        blank=True,
        help_text="Solo para uso interno. Si lo dejás vacío se genera desde el título."
    )

    titulo = models.CharField("Título", max_length=120)
    contenido = models.TextField("Contenido", blank=True)
    orden = models.PositiveIntegerField("Orden", default=1)
    activo = models.BooleanField("Activo", default=True)

    class Meta:
        ordering = ("orden", "id")

    def save(self, *args, **kwargs):
        if not self.clave:
            self.clave = slugify(self.titulo)[:80]
        super().save(*args, **kwargs)


class SiteConfig(models.Model):
    # ====== Colores (CSS variables) ======
    primary_color   = models.CharField(max_length=20, default="#0d6efd")
    secondary_color = models.CharField(max_length=20, default="#6c757d")
    success_color   = models.CharField(max_length=20, default="#198754")
    danger_color    = models.CharField(max_length=20, default="#dc3545")
    background      = models.CharField(max_length=20, default="#ffffff")
    surface         = models.CharField(max_length=20, default="#ffffff")
    text_color      = models.CharField(max_length=20, default="#111111")
    muted_color     = models.CharField(max_length=20, default="#6c757d")

    # para el degradado
    primary_rgb = models.CharField(
        max_length=20,
        default="13,110,253",
        help_text="Formato: R,G,B (ej: 13,110,253)",
    )

    # ====== Tipografías ======
    font_base = models.CharField(
        max_length=120,
        default="system-ui, -apple-system, Segoe UI, Roboto, Arial"
    )
    font_headings = models.CharField(
        max_length=120,
        default="system-ui, -apple-system, Segoe UI, Roboto, Arial"
    )
    google_fonts_url = models.URLField(blank=True, default="")

    # ====== Textos / palabras globales ======
    texts = models.JSONField(default=dict, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Configuración del sitio"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


# ========== NUEVO: Bitácora global ==========
class BitacoraEvento(models.Model):
    TIPO_CHOICES = [
        # =====================================================
        # CARRITO / CUPONES / FAVORITOS (FRONT CLIENTE)
        # =====================================================

        # Carrito (nuevos nombres usados en cliente/views.py)
        ("carrito_agregar", "Carrito: producto agregado"),
        ("carrito_eliminar", "Carrito: producto eliminado"),
        ("carrito_actualizar", "Carrito: cantidad actualizada"),
        ("carrito_vaciar", "Carrito: carrito vaciado"),
        ("carrito_agregar_sin_stock", "Carrito: intento de agregar sin stock"),
        ("carrito_sin_stock", "Carrito: producto quitado por falta de stock"),

        # Cupón
        ("cupon_aplicado", "Cupón aplicado"),
        ("cupon_invalido", "Cupón inválido o vencido"),

        # Favoritos
        ("favorito_agregar", "Favoritos: producto agregado"),
        ("favorito_eliminar", "Favoritos: producto eliminado"),

        # =====================================================
        # COMPRAS / PEDIDOS (FRONT CLIENTE + INTEGRACIONES)
        # =====================================================

        # Viejos nombres que ya tenías (por si ya hay datos)
        ("compra_creada", "Compra realizada"),
        ("compra_cancelada", "Compra cancelada"),

        # Pedidos (nuevos nombres usados en cliente/views.py)
        ("pedido_ver_detalle", "Pedido: ver detalle"),
        ("pedido_continuar_pago", "Pedido: continuar pago"),
        ("pedido_continuar_no_permitido", "Pedido: continuar no permitido"),
        ("pedido_continuar_sin_link", "Pedido: continuar sin link de pago"),
        ("pedido_cancelar", "Pedido: cancelado por el cliente"),
        ("pedido_cancelar_no_permitido", "Pedido: intento de cancelación no permitida"),
        ("pedido_eliminar", "Pedido: eliminado por el cliente"),
        ("pedido_eliminar_no_permitido", "Pedido: intento de eliminación no permitida"),

        # =====================================================
        # PRODUCTOS / PRECIOS (PANEL OWNER)
        # =====================================================

        ("producto_creado", "Producto creado"),
        ("producto_editado", "Producto editado"),
        ("producto_eliminado", "Producto eliminado"),
        ("precio_actualizado", "Precio actualizado"),

        # Acciones masivas (AdminDashboard / owner_productos_acciones_masivas)
        ("productos_bulk_activar", "Productos: alta masiva"),
        ("productos_bulk_desactivar", "Productos: baja masiva"),
        ("productos_bulk_eliminar", "Productos: eliminación masiva"),
        ("productos_bulk_tech", "Productos: técnica asignada masivamente"),

        # =====================================================
        # RUBROS / FILTROS
        # =====================================================

        ("rubros_asignados", "Rubros asignados / auto-rubros"),
        ("autorubros_aplicados", "Auto-rubros aplicados"),

        ("rubro_creado", "Rubro creado"),
        ("rubro_editado", "Rubro editado"),
        ("rubro_eliminado", "Rubro eliminado"),

        ("subrubro_creado", "Subrubro creado"),
        ("subrubro_editado", "Subrubro editado"),
        ("subrubro_eliminado", "Subrubro eliminado"),

        # =====================================================
        # CONFIGURACIÓN / CONTENIDO
        # =====================================================

        ("siteconfig_edit", "Personalización del sitio modificada"),
        ("siteinfo_edit", "Información del sitio modificada"),
        ("perfil_actualizado", "Perfil de usuario actualizado"),

        # =====================================================
        # LISTAS DE PRECIOS / FACTURAS PROVEEDOR / FACTURAS PDF
        # =====================================================

        ("lista_cargada", "Lista de precios cargada"),
        ("lista_import_confirmada", "Importación de lista confirmada"),

        ("factura_proveedor_cargada", "Factura de proveedor cargada"),
        ("factura_proveedor_confirmada", "Factura de proveedor confirmada"),

        ("factura_pdf_generada", "Factura PDF generada"),
        ("lista_precios_pdf_generada", "Lista de precios PDF generada"),

        # =====================================================
        # SESIÓN / AUTH
        # =====================================================

        ("logout", "Usuario cerró sesión"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bitacora_eventos",
    )
    tipo = models.CharField(max_length=50, choices=TIPO_CHOICES)
    titulo = models.CharField(max_length=200)
    detalle = models.TextField(blank=True)

    # Referencia opcional a un objeto
    obj_model = models.CharField(max_length=100, blank=True)
    obj_id = models.CharField(max_length=50, blank=True)

    # Datos extra (IDs, montos, etc.)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.get_tipo_display()} - {self.titulo}"
