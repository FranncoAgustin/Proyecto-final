import pdfplumber
import re
from decimal import Decimal
from difflib import SequenceMatcher
import difflib

def get_similarity(a: str, b: str) -> int:
    """
    Devuelve un porcentaje de similitud (0-100) entre dos strings.
    Lo usamos para sugerir productos similares cuando el SKU no coincide exacto.
    """
    if not a or not b:
        return 0
    ratio = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return int(ratio * 100)




def extraer_precios_de_pdf(path):
    """
    Lee todo el PDF y devuelve:
      items: lista de dicts {nombre, precio, moneda, page}
      parse_errors: lista de dicts con líneas que no se pudieron interpretar

    Mantiene compatibilidad con tu código actual: cada item sigue teniendo
    'nombre' y 'precio', pero agregamos campos extra que podés usar.
    """
    items = []
    parse_errors = []

    with pdfplumber.open(path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            # una línea por fila, sin vacías
            lines = [l.strip() for l in text.splitlines() if l.strip()]

            current_name_lines = []

            for line in lines:
                # Saltamos headers/footers de la lista
                if line.startswith("pág.") or "GENESIS INSUMOS" in line:
                    continue

                # Saltamos títulos de secciones tipo CARTON / CERAMICA / NAVIDAD
                if line.isupper() and len(line.split()) <= 3:
                    current_name_lines = []
                    continue

                # ¿es una línea con precio?
                if "$" in line or re.search(r"\d{3,}", line):
                    # moneda
                    currency = "ARS"
                    if re.search(r"U\$?D|US\$", line, re.I):
                        currency = "USD"

                    # tomar el último número grande de la línea como precio
                    m_price = re.search(r"(\d[\d\.]*)\s*$", line)
                    if not m_price:
                        parse_errors.append({
                            "page": page_index,
                            "raw": line,
                            "reason": "No pude leer el precio",
                        })
                        current_name_lines = []
                        continue

                    price_str = m_price.group(1).replace(".", "")
                    try:
                        price = Decimal(price_str)
                    except Exception:
                        parse_errors.append({
                            "page": page_index,
                            "raw": line,
                            "reason": f"Precio inválido: {price_str}",
                        })
                        current_name_lines = []
                        continue

                    if not current_name_lines:
                        # precio sin nombre previo
                        parse_errors.append({
                            "page": page_index,
                            "raw": line,
                            "reason": "Precio sin nombre antes",
                        })
                        continue

                    name = " ".join(current_name_lines)

                    # descartamos AGOTADO
                    if "AGOTADO" in line.upper() or "AGOTADO" in name.upper():
                        current_name_lines = []
                        continue

                    items.append({
                        "nombre": name,
                        "precio": price,
                        "moneda": currency,
                        "page": page_index,
                    })
                    current_name_lines = []
                else:
                    # asumimos que es parte del nombre
                    current_name_lines.append(line)

    return items, parse_errors
