# pdf/utils_facturas.py
from decimal import Decimal
import re

try:
    import pdfplumber
except ImportError:  # por si todavía no lo tenés instalado
    pdfplumber = None


def _parse_decimal(num_str: str) -> Decimal:
    """
    Convierte textos como '41.940', '41,940', '12.500' a Decimal.
    """
    if not num_str:
        return Decimal("0")
    s = str(num_str).replace("\xa0", " ").strip()
    # sacamos separador de miles y dejamos punto como decimal
    s = s.replace(".", "").replace(",", ".")
    # eliminar símbolos de moneda
    s = s.replace("$", "").replace("U$S", "").replace("USD", "").strip()
    return Decimal(s)


def extraer_texto_factura_simple(pdf_path: str) -> str:
    """
    Extrae texto sin formato de un PDF de factura.
    Usamos pdfplumber si está disponible, sino hacemos un fallback muy simple.
    """
    if pdfplumber is None:
        # fallback: leer como binario y devolver vacío; así no rompe
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(pdf_path)
            texto = []
            for page in reader.pages:
                texto.append(page.extract_text() or "")
            return "\n".join(texto)
        except Exception:
            return ""

    texto = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            texto.append(page.extract_text() or "")
    return "\n".join(texto)


def parse_invoice_text(text: str):
    """
    Intenta extraer items de una factura genérica a partir de texto plano.

    Devuelve una lista de dicts:
    {
        "producto": str,
        "cantidad": Decimal,
        "precio_unitario": Decimal,
        "subtotal": Decimal,
        "descuento": Decimal | None,
        "moneda": "ARS" o "USD"
    }
    """
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    items = []

    if not lines:
        return items

    # 1) intentar saltar encabezado "Product / Producto  Quantity / Cantidad ..."
    start_idx = 0
    for i, l in enumerate(lines):
        low = l.lower()
        if ("product" in low or "producto" in low) and (
            "qty" in low or "quantity" in low or "cantidad" in low
        ):
            start_idx = i + 1
            break

    data_lines = lines[start_idx:]

    # 2) cortar cuando empiecen Subtotal / Total / Envío, etc.
    corte = len(data_lines)
    for i, l in enumerate(data_lines):
        low = l.lower()
        if low.startswith("subtotal") or low.startswith("total") or "subtotal:" in low:
            corte = i
            break
    data_lines = data_lines[:corte]

    i = 0
    while i < len(data_lines):
        line = data_lines[i]

        # --- patrón A: descripción en una línea + "CANT  $ PRECIO" en la siguiente ---
        qty_line = None
        if i + 1 < len(data_lines):
            qty_line = data_lines[i + 1]

        m_qty_price = None
        if qty_line:
            # ej: "6   $ 41.940" o "6 41.940"
            m_qty_price = re.match(
                r"^(\d+)\s+\$?\s*([\d\.,]+)",
                qty_line
            )

        if m_qty_price and not re.match(r"^\d+\s", line):
            desc = line
            cantidad = Decimal(m_qty_price.group(1))
            price = _parse_decimal(m_qty_price.group(2))
            subtotal = cantidad * price

            items.append({
                "producto": desc,
                "cantidad": cantidad,
                "precio_unitario": price,
                "subtotal": subtotal,
                "descuento": None,
                "moneda": "ARS",  # si aparece USD lo podríamos detectar después
            })
            i += 2
            continue

        # --- patrón B: todo en una sola línea ---
        # "Camionero algo algo   6   $ 41.940"
        m_inline = re.match(
            r"^(?P<desc>.+?)\s+(?P<cant>\d+)\s+\$?\s*(?P<price>[\d\.,]+)\s*$",
            line
        )
        if m_inline:
            desc = m_inline.group("desc").strip()
            cantidad = Decimal(m_inline.group("cant"))
            price = _parse_decimal(m_inline.group("price"))
            subtotal = cantidad * price

            items.append({
                "producto": desc,
                "cantidad": cantidad,
                "precio_unitario": price,
                "subtotal": subtotal,
                "descuento": None,
                "moneda": "ARS",
            })
            i += 1
            continue

        # TODO: acá podríamos agregar patrones C y D para
        # formatos de 4 o 5 columnas (precio unit., descuento, total, etc.)

        i += 1

    return items
