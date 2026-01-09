import pdfplumber
import re
from decimal import Decimal
from difflib import SequenceMatcher
from PyPDF2 import PdfReader
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




def extraer_precios_de_pdf(pdf_path: str):
    """
    Lee un PDF de lista de precios y devuelve:
        productos: [
            {
                "nombre": str,
                "precio": Decimal,
                "moneda": "ARS" | "USD",
                "page": int,
            },
            ...
        ]

        parse_errors: [str, ...]

    Pensado para listas tipo Génesis:
    - Nombre y descripción del producto en 1 o más líneas
    - Precio en una línea aparte con '$'
    """

    productos = []
    parse_errors = []

    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        return [], [f"Error al abrir PDF: {e}"]

    # Palabras/fragmentos típicos de encabezado que NO son productos
    header_keywords = (
        "GENES IS INSUMOS",
        "VIGENCIA",
        "Precios sujeto",
        "Las fotos son",
        "Forma de pago",
        "Transferencia",
        "Tarjeta",
        "pág.",
    )

    def is_header(line: str) -> bool:
        """
        Devuelve True si la línea parece un encabezado/sección
        y no parte de un producto.
        """
        s = line.strip()
        if not s:
            return False

        lower = s.lower()
        for k in header_keywords:
            if k.lower() in lower:
                return True

        # Líneas TODO MAYÚSCULAS sin números tipo "CARTON", "CERAMICA", "NAVIDAD!!!!"
        letters_only = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑ ]", "", s)
        if letters_only and letters_only == letters_only.upper() and not any(ch.isdigit() for ch in s):
            return True

        return False

    def normalize_spaces(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    def parse_price(line: str):
        """
        Recibe una línea que contiene '$' y devuelve:
            (Decimal(precio), moneda_str)
        Soporta formatos como:
            "$460 0" -> 4600
            "$5.642" -> 5642
            "$12,50" -> 12.50
        """
        currency = "ARS"
        if re.search(r"u\$d|usd|d[óo]lar", line, re.IGNORECASE):
            currency = "USD"

        # Sólo dejamos dígitos, coma y punto
        num = re.sub(r"[^\d,\.]", "", line)
        num = num.replace(" ", "")  # "460 0" -> "4600"

        if not num:
            raise ValueError("sin números")

        # Si hay coma y punto: puntos como miles, coma como decimal
        if "," in num and "." in num:
            num = num.replace(".", "")
            num = num.replace(",", ".")
        elif "," in num:
            # Sólo coma -> decimal
            num = num.replace(",", ".")
        else:
            # Sólo punto: puede ser miles o decimal
            if "." in num:
                parts = num.split(".")
                # Patrón típico de miles: 1-3 dígitos + grupos de 3
                if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
                    # 5.642 -> 5642
                    num = "".join(parts)
                else:
                    # Último grupo como decimales si es 1 o 2 dígitos
                    if len(parts[-1]) in (1, 2):
                        num = (''.join(parts[:-1]) or '0') + "." + parts[-1]
                    else:
                        # Ambiguo -> asumimos miles
                        num = "".join(parts)

        return Decimal(num), currency

    # Recorremos todas las páginas
    for page_index, page in enumerate(reader.pages):
        raw_text = page.extract_text() or ""
        lines = raw_text.splitlines()

        current_lines = []  # acumulamos líneas del producto actual

        for line_index, line in enumerate(lines):
            # Si la línea tiene precio
            if "$" in line:
                nombre = normalize_spaces(" ".join(current_lines))

                if not nombre:
                    parse_errors.append(
                        f"pág {page_index+1}, línea {line_index+1}: "
                        f"precio sin nombre. Línea precio: {line!r}"
                    )
                    current_lines = []
                    continue

                try:
                    precio, moneda = parse_price(line)
                except Exception as e:
                    parse_errors.append(
                        f"pág {page_index+1}, prod '{nombre}': "
                        f"no pude parsear precio en '{line}': {e}"
                    )
                else:
                    productos.append({
                        "nombre": nombre,
                        "precio": precio,
                        "moneda": moneda,
                        "page": page_index + 1,
                    })

                # Reseteamos bloque para el siguiente producto
                current_lines = []
            else:
                # Línea sin precio
                if is_header(line):
                    # Si veníamos acumulando algo y nos cruzamos un encabezado,
                    # lo descartamos porque nunca encontró su precio.
                    if current_lines:
                        parse_errors.append(
                            f"pág {page_index+1}: descartado bloque sin precio: "
                            f"{normalize_spaces(' '.join(current_lines[-3:]))}"
                        )
                        current_lines = []
                    continue

                stripped = line.strip()
                if not stripped:
                    # Líneas vacías no cortan el bloque, sólo las ignoramos.
                    continue

                current_lines.append(stripped)

        # Si queda algo al final de la página sin precio, lo descartamos
        if current_lines:
            parse_errors.append(
                f"pág {page_index+1}: bloque al final sin precio: "
                f"{normalize_spaces(' '.join(current_lines[-3:]))}"
            )
            current_lines = []

    # Eliminamos duplicados (mismo nombre + precio + moneda)
    unique = {}
    for item in productos:
        key = (item["nombre"], item["precio"], item.get("moneda", "ARS"))
        if key in unique:
            parse_errors.append(
                f"Duplicado descartado: '{item['nombre']}' $ {item['precio']} "
                f"(pág. {item['page']}) duplicado de pág. {unique[key]['page']}"
            )
        else:
            unique[key] = item

    productos_unicos = list(unique.values())
    return productos_unicos, parse_errors
    """
    Lee un PDF de lista de precios y devuelve:
        productos: [
            {
                "nombre": str,
                "precio": Decimal,
                "moneda": "ARS" | "USD",
                "page": int,
            },
            ...
        ]

        parse_errors: [str, ...]

    Pensado para listas tipo Génesis:
    - Nombre y descripción del producto en 1 o más líneas
    - Precio en una línea aparte con '$'
    """

    productos = []
    parse_errors = []

    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        return [], [f"Error al abrir PDF: {e}"]

    # Palabras/fragmentos típicos de encabezado que NO son productos
    header_keywords = (
        "GENES IS INSUMOS",
        "VIGENCIA",
        "Precios sujeto",
        "Las fotos son",
        "Forma de pago",
        "Transferencia",
        "Tarjeta",
        "pág.",
    )