# pdf/utils_facturas.py
from decimal import Decimal
import re

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


# ============================================================
# Helpers
# ============================================================

def _parse_decimal(num_str: str) -> Decimal:
    """
    Convierte:
    '41.940'   -> 41940
    '$ 9.990'  -> 9990
    '1.234,56' -> 1234.56
    """
    if not num_str:
        return Decimal("0")

    s = str(num_str).replace("\xa0", " ").strip()
    s = s.replace("$", "").replace("U$S", "").replace("USD", "").strip()

    if "," in s and "." in s:
        # 1.234,56
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # 1234,56
        s = s.replace(",", ".")
    else:
        # 41.940 -> 41940
        s = s.replace(".", "")

    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


def _clean_line(line: str) -> str:
    line = (line or "").replace("\xa0", " ").strip()
    line = re.sub(r"\s+", " ", line)
    return line


def _group_words_into_rows(words, tolerance=3):
    """
    Agrupa palabras por coordenada vertical (top).
    """
    rows = []

    for w in sorted(words, key=lambda x: (x["top"], x["x0"])):
        placed = False
        for row in rows:
            if abs(row["top"] - w["top"]) <= tolerance:
                row["words"].append(w)
                placed = True
                break

        if not placed:
            rows.append({
                "top": w["top"],
                "words": [w],
            })

    # ordenar palabras dentro de cada fila
    for row in rows:
        row["words"] = sorted(row["words"], key=lambda x: x["x0"])

    return rows


def _row_text(row):
    return " ".join(w["text"] for w in row["words"]).strip()


def _extract_row_parts(row):
    """
    Divide una fila en:
    - desc_words (columna izquierda)
    - qty_words  (columna central)
    - price_words (columna derecha)

    Ajustado al layout real de tu PDF:
    desc   ~ x < 320
    qty    ~ 320..380
    price  ~ >= 380
    """
    desc_words = []
    qty_words = []
    price_words = []

    for w in row["words"]:
        x0 = w["x0"]
        txt = w["text"]

        if x0 < 320:
            desc_words.append(txt)
        elif x0 < 380:
            qty_words.append(txt)
        else:
            price_words.append(txt)

    desc = " ".join(desc_words).strip()
    qty = " ".join(qty_words).strip()
    price = " ".join(price_words).strip()

    return desc, qty, price


def _is_header_or_footer_row(text):
    low = (text or "").strip().lower()
    if not low:
        return True

    bad_starts = [
        "gmail -",
        "product quantity price",
        "subtotal",
        "total",
        "envío",
        "envio",
        "método de pago",
        "metodo de pago",
        "https://",
        "17/3/26",
    ]

    return any(low.startswith(x) for x in bad_starts)


def _is_anchor_row(qty_text, price_text):
    """
    Fila con cantidad y precio presentes.
    """
    qty_ok = bool(re.fullmatch(r"\d+", qty_text.strip() if qty_text else ""))
    price_ok = bool(re.search(r"\d", price_text or ""))
    return qty_ok and price_ok


def _rows_gap(a, b):
    return abs((b["top"] or 0) - (a["top"] or 0))


# ============================================================
# Texto simple
# ============================================================

def extraer_texto_factura_simple(pdf_path: str) -> str:
    """
    Extrae texto sin formato de un PDF de factura.
    """
    if pdfplumber is None:
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


# ============================================================
# Parser por POSICIÓN (el importante para tu factura)
# ============================================================

def parse_invoice_pdf(pdf_path: str):
    """
    Parser basado en posiciones del PDF.
    Soporta estos 3 casos del layout real:

    A) desc arriba + anchor en el medio + desc abajo
       TERMO BALA DOBLE CAPA ACERO
       1 $ 7.990
       500ml - color NEGRO

    B) desc arriba + anchor con parte de desc + desc abajo
       IMPERIAL DE ALGARROBO GUARDA DE
       BRONCE GRUESA - BASE ANCHA - 2 $ 23.980
       BOCA ANCHA

    C) todo inline
       BOTELLA FLIP 650ML COLOR NEGRO 3 $ 41.970
    """
    items = []

    if pdfplumber is None:
        return items

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
                if not words:
                    continue

                rows = _group_words_into_rows(words, tolerance=3)

                # Filtrar encabezado / pie
                filtered_rows = []
                for row in rows:
                    txt = _row_text(row)
                    if _is_header_or_footer_row(txt):
                        continue
                    filtered_rows.append(row)

                n = len(filtered_rows)
                if n == 0:
                    continue

                # Detectar filas ancla (cantidad + precio)
                anchors = []
                for idx, row in enumerate(filtered_rows):
                    desc, qty, price = _extract_row_parts(row)
                    if _is_anchor_row(qty, price):
                        anchors.append(idx)

                if not anchors:
                    continue

                for pos, anchor_idx in enumerate(anchors):
                    row = filtered_rows[anchor_idx]
                    desc_anchor, qty, price = _extract_row_parts(row)

                    cantidad = Decimal(qty.strip())
                    precio_unitario = _parse_decimal(price)

                    if cantidad <= 0 or precio_unitario <= 0:
                        continue

                    # Límite superior: luego del ancla anterior
                    prev_anchor = anchors[pos - 1] if pos > 0 else None
                    # Límite inferior: antes del ancla siguiente
                    next_anchor = anchors[pos + 1] if pos + 1 < len(anchors) else None

                    partes = []

                    # 1) filas anteriores cercanas
                    k = anchor_idx - 1
                    prev_buffer = []
                    while k >= 0:
                        if prev_anchor is not None and k <= prev_anchor:
                            break

                        pdesc, pqty, pprice = _extract_row_parts(filtered_rows[k])

                        if _is_anchor_row(pqty, pprice):
                            break
                        if not pdesc:
                            break

                        # si el salto vertical es muy grande, ya no pertenece al item
                        gap = _rows_gap(filtered_rows[k], filtered_rows[k + 1])
                        if gap > 20:
                            break

                        prev_buffer.append(pdesc)
                        k -= 1

                    prev_buffer.reverse()
                    partes.extend(prev_buffer)

                    # 2) texto descriptivo en la misma fila ancla (columna izquierda)
                    if desc_anchor:
                        partes.append(desc_anchor)

                    # 3) filas siguientes cercanas
                    j = anchor_idx + 1
                    last_row = row
                    while j < n:
                        if next_anchor is not None and j >= next_anchor:
                            break

                        ndesc, nqty, nprice = _extract_row_parts(filtered_rows[j])

                        if _is_anchor_row(nqty, nprice):
                            break
                        if not ndesc:
                            break

                        gap = _rows_gap(last_row, filtered_rows[j])
                        if gap > 20:
                            break

                        partes.append(ndesc)
                        last_row = filtered_rows[j]
                        j += 1

                    producto = " ".join(partes)
                    producto = re.sub(r"\s+", " ", producto).strip(" -|,.;")

                    if producto:
                        items.append({
                            "producto": producto,
                            "cantidad": cantidad,
                            "precio_unitario": precio_unitario,
                            "subtotal": cantidad * precio_unitario,
                            "descuento": None,
                            "moneda": "ARS",
                        })

    except Exception:
        return []

    # deduplicado simple
    final_items = []
    seen = set()
    for item in items:
        key = (
            item["producto"],
            str(item["cantidad"]),
            str(item["precio_unitario"]),
        )
        if key not in seen:
            seen.add(key)
            final_items.append(item)

    return final_items

# ============================================================
# Fallback texto plano
# ============================================================

def parse_invoice_text(text: str):
    """
    Fallback de texto plano.
    Se usa si el parser por PDF no devuelve nada.
    """
    lines = [_clean_line(l) for l in (text or "").splitlines() if _clean_line(l)]
    items = []

    if not lines:
        return items

    for line in lines:
        low = line.lower()
        if (
            low.startswith("subtotal")
            or low.startswith("total")
            or low.startswith("envío")
            or low.startswith("envio")
            or low.startswith("gmail -")
            or low == "product quantity price"
        ):
            continue

        m_inline = re.match(
            r"^(?P<desc>.+?)\s+(?P<cant>\d+)\s+\$?\s*(?P<price>[\d\.,]+)\s*$",
            line
        )
        if m_inline:
            desc = m_inline.group("desc").strip()
            cantidad = Decimal(m_inline.group("cant"))
            price = _parse_decimal(m_inline.group("price"))

            if desc and cantidad > 0 and price > 0:
                items.append({
                    "producto": desc,
                    "cantidad": cantidad,
                    "precio_unitario": price,
                    "subtotal": cantidad * price,
                    "descuento": None,
                    "moneda": "ARS",
                })

    return items