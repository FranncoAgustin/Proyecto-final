from datetime import timedelta
from django.db.models import Sum
from django.db import transaction
from django.utils import timezone

HOLD_MINUTES = 30


def _ensure_session(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def cleanup_expired_holds():
    from .models import StockHold
    StockHold.objects.filter(expires_at__lte=timezone.now()).delete()


def get_stock_reservado(producto, variante_id: int) -> int:
    from .models import StockHold

    qs = StockHold.objects.filter(
        producto=producto,
        expires_at__gt=timezone.now(),
    )

    if variante_id == 0:
        qs = qs.filter(variante__isnull=True)
    else:
        qs = qs.filter(variante_id=variante_id)

    agg = qs.aggregate(total=Sum("cantidad"))["total"] or 0
    return max(0, int(agg))


def get_stock_disponible_efectivo(producto, variante_id: int) -> int:
    """
    Stock real - reservado vigente.
    """
    stock_real = get_stock_disponible(producto, variante_id)  # tu función actual
    reservado = get_stock_reservado(producto, variante_id)
    return max(0, int(stock_real) - int(reservado))
