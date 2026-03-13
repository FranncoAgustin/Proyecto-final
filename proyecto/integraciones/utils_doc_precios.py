# integraciones/utils_doc_precios.py
import re
from decimal import Decimal
from typing import Iterator
from io import BytesIO

from docx import Document  # python-docx

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None

from .models import PriceDocSnapshot, PriceDocItem, PriceDocSource, Q2


# =========================
# Utilidades base
# =========================

PRICE_RE = re.compile(r"\$\s*([0-9][0-9\.\s]*)(?:,([0-9]{1,2}))?")
SPLIT_COLS_RE = re.compile(r"\s{2,}|\t+")


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _parse_price(text: str) -> Decimal | None:
    """
    Devuelve Decimal si encuentra un precio con $, ej: "$ 12.345,67".
    """
    if not text or "$" not in text:
        return None
    m = PRICE_RE.search(text)
    if not m:
        return None
    int_part = re.sub(r"[^\d]", "", m.group(1))  # quita puntos, espacios, etc.
    dec_part = (m.group(2) or "00").ljust(2, "0")[:2]
    return Decimal(f"{int_part}.{dec_part}").quantize(Q2)


def _build_item_from_texts(textos: list[str]) -> dict | None:
    """
    Lógica común para transformar una fila/lista de columnas en item:
    - ignora celdas vacías
    - PRECIO = última celda con '$'
    - ART, PRODUCTO, DESCRIPCION = primeras columnas no vacías antes del precio
    """
    nonempty = [(i, _normalize_ws(t)) for i, t in enumerate(textos) if _normalize_ws(t)]
    if not nonempty:
        return None

    price_candidates = []
    for i, t in nonempty:
        p = _parse_price(t)
        if p is not None:
            price_candidates.append((i, t, p))

    if not price_candidates:
        return None

    price_i, price_text, price_value = price_candidates[-1]
    left_texts = [t for i, t in nonempty if i < price_i]

    if not left_texts:
        return None

    first_upper = left_texts[0].upper()
    price_upper = price_text.upper()

    # headers típicos
    if (
        first_upper.startswith("ART")
        or first_upper == "COD"
        or first_upper == "CODIGO"
        or first_upper == "CÓDIGO"
    ) and ("PRECIO" in price_upper or "$" in price_text):
        return None

    art = left_texts[0]
    producto = left_texts[1] if len(left_texts) >= 2 else ""
    descripcion = " ".join(left_texts[2:]) if len(left_texts) >= 3 else ""

    return {
        "art": art,
        "producto": producto,
        "descripcion": descripcion,
        "compra": price_value,
        "precio_str": price_text,
    }


# =========================
# Google Docs JSON
# =========================

def _cell_text(cell: dict) -> str:
    """
    Extrae todo el texto plano de una celda de Google Docs.
    Ignora imágenes y otros objetos.
    """
    out = []
    for content in cell.get("content", []):
        p = content.get("paragraph")
        if not p:
            continue
        for el in p.get("elements", []):
            tr = el.get("textRun")
            if tr and "content" in tr:
                out.append(tr["content"])
    return _normalize_ws("".join(out))


def _iter_table_rows(doc_json: dict) -> Iterator[dict]:
    """
    Itera todas las filas de todas las tablas del documento de Google.
    """
    body = doc_json.get("body", {}).get("content", [])
    for block in body:
        table = block.get("table")
        if not table:
            continue
        for r in table.get("tableRows", []):
            yield r


def parse_row_to_item(row: dict) -> dict | None:
    """
    Aplica la lógica común a una fila de Google Docs.
    """
    cells = row.get("tableCells", [])
    textos = [_cell_text(c) for c in cells]
    return _build_item_from_texts(textos)


def crear_snapshot_desde_doc_json(source: PriceDocSource, doc_json: dict) -> PriceDocSnapshot:
    """
    Crea un snapshot completo de la lista desde el JSON del Google Doc.
    """
    snapshot = PriceDocSnapshot.objects.create(source=source)

    items = []
    for row in _iter_table_rows(doc_json):
        parsed = parse_row_to_item(row)
        if not parsed:
            continue

        items.append(PriceDocItem(
            snapshot=snapshot,
            art=parsed["art"],
            producto=parsed["producto"],
            descripcion=parsed["descripcion"],
            compra=parsed["compra"],
        ))

    PriceDocItem.objects.bulk_create(items)
    return snapshot


# =========================
# DOCX (Word) con python-docx
# =========================

def crear_snapshot_desde_docx_bytes(source: PriceDocSource, file_bytes: bytes) -> PriceDocSnapshot:
    """
    Crea un snapshot leyendo tablas desde un .docx (Office) usando python-docx.
    """
    snapshot = PriceDocSnapshot.objects.create(source=source)

    doc = Document(BytesIO(file_bytes))
    items = []

    for table in doc.tables:
        for row in table.rows:
            textos = [_normalize_ws(cell.text) for cell in row.cells]
            parsed = _build_item_from_texts(textos)
            if not parsed:
                continue

            items.append(PriceDocItem(
                snapshot=snapshot,
                art=parsed["art"],
                producto=parsed["producto"],
                descripcion=parsed["descripcion"],
                compra=parsed["compra"],
            ))

    PriceDocItem.objects.bulk_create(items)
    return snapshot


# =========================
# PDF
# =========================

def _pdf_extract_lines(file_bytes: bytes) -> list[str]:
    """
    Extrae líneas de texto desde un PDF.
    """
    if PdfReader is None:
        raise RuntimeError(
            "No está disponible pypdf. Instalalo con: pip install pypdf"
        )

    reader = PdfReader(BytesIO(file_bytes))
    lines: list[str] = []

    for page in reader.pages:
        text = page.extract_text() or ""
        if not text:
            continue

        for raw_line in text.splitlines():
            line = _normalize_ws(raw_line)
            if line:
                lines.append(line)

    return lines


def _parse_pdf_line_direct(line: str) -> dict | None:
    """
    Intenta parsear una línea de PDF que ya trae toda la fila junta.

    Ejemplos típicos:
    - ART123  Producto X  Descripción  $ 12.345,00
    - ART123    Producto X    $ 12.345
    """
    if "$" not in line:
        return None

    cols = [c.strip() for c in SPLIT_COLS_RE.split(line) if c.strip()]

    # Primer intento: columnas separadas por muchos espacios / tabs
    if len(cols) >= 2:
        parsed = _build_item_from_texts(cols)
        if parsed:
            return parsed

    # Segundo intento: precio al final y texto a la izquierda
    m = PRICE_RE.search(line)
    if not m:
        return None

    price_value = _parse_price(m.group(0))
    if price_value is None:
        return None

    left = _normalize_ws(line[:m.start()])
    if not left:
        return None

    # Separamos en hasta 3 bloques de forma flexible
    parts = [p for p in SPLIT_COLS_RE.split(left) if p.strip()]
    if len(parts) >= 2:
        art = parts[0].strip()
        producto = parts[1].strip()
        descripcion = " ".join(p.strip() for p in parts[2:]) if len(parts) >= 3 else ""
    else:
        # Si vino muy pegado, usamos todo como ART
        art = left
        producto = ""
        descripcion = ""

    art_upper = art.upper()
    if art_upper.startswith("ART") and "PRECIO" in line.upper():
        return None

    return {
        "art": art,
        "producto": producto,
        "descripcion": descripcion,
        "compra": price_value,
        "precio_str": m.group(0),
    }


def _parse_pdf_lines_with_context(lines: list[str]) -> list[dict]:
    """
    Fallback para PDFs donde el texto sale cortado en varias líneas:
    - una línea con ART / producto
    - otra línea con descripción
    - otra línea con precio
    """
    items: list[dict] = []
    buffer: list[str] = []

    for line in lines:
        if "$" in line:
            price_value = _parse_price(line)
            if price_value is None:
                continue

            left_text = " ".join(buffer).strip()
            buffer = []

            if not left_text:
                # Intentar sacar algo de la misma línea
                parsed = _parse_pdf_line_direct(line)
                if parsed:
                    items.append(parsed)
                continue

            parts = [p.strip() for p in SPLIT_COLS_RE.split(left_text) if p.strip()]
            if len(parts) >= 2:
                art = parts[0]
                producto = parts[1]
                descripcion = " ".join(parts[2:]) if len(parts) >= 3 else ""
            else:
                art = left_text
                producto = ""
                descripcion = ""

            if art.upper().startswith("ART") and "PRECIO" in line.upper():
                continue

            items.append({
                "art": art,
                "producto": producto,
                "descripcion": descripcion,
                "compra": price_value,
                "precio_str": line,
            })
        else:
            # Filtrar algunas líneas ruidosas
            upper = line.upper()
            if upper in {"LISTA DE PRECIOS", "PRECIO", "PRECIOS", "ART", "ARTÍCULO", "ARTICULO"}:
                continue
            buffer.append(line)

    return items


def crear_snapshot_desde_pdf_bytes(source: PriceDocSource, file_bytes: bytes) -> PriceDocSnapshot:
    """
    Crea un snapshot leyendo texto desde un PDF.

    Estrategia:
    1) intenta parsear líneas directas que ya contienen la fila completa
    2) si no encuentra items suficientes, usa un fallback por contexto
    """
    snapshot = PriceDocSnapshot.objects.create(source=source)

    lines = _pdf_extract_lines(file_bytes)
    items_data: list[dict] = []

    # Primer intento: línea completa
    for line in lines:
        parsed = _parse_pdf_line_direct(line)
        if parsed:
            items_data.append(parsed)

    # Fallback si el PDF viene partido en varias líneas
    if len(items_data) < 3:
        items_data = _parse_pdf_lines_with_context(lines)

    # Deduplicar por (art, compra) para evitar repetidos por extracción rara del PDF
    seen = set()
    items = []

    for parsed in items_data:
        key = (parsed["art"], parsed["compra"])
        if key in seen:
            continue
        seen.add(key)

        items.append(PriceDocItem(
            snapshot=snapshot,
            art=parsed["art"],
            producto=parsed["producto"],
            descripcion=parsed["descripcion"],
            compra=parsed["compra"],
        ))

    PriceDocItem.objects.bulk_create(items)
    return snapshot