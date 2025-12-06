import pdfplumber
import re
from decimal import Decimal
from difflib import SequenceMatcher

def get_similarity(a, b):
    """Calcula el porcentaje de similitud entre dos cadenas."""
    a = re.sub(r'[^a-zA-Z0-9]', '', a).lower()
    b = re.sub(r'[^a-zA-Z0-9]', '', b).lower()
    if not a or not b: return 0.0
    return round(SequenceMatcher(None, a, b).ratio() * 100, 2)

def extraer_precios_de_pdf(pdf_path):
    """
    Extrae productos, precios Y CANTIDADES de un PDF.
    Intenta detectar patrones como:
    - "5 Mate Imperial $15000" (Cantidad al inicio)
    - "Mate Imperial ... 5 ... $15000" (Cantidad en medio)
    """
    productos_extraidos = []
    
    # Regex mejorada: Busca Cantidad (opcional) + Texto + Precio
    # Grupo 1: Cantidad (opcional, dígitos al inicio)
    # Grupo 2: Precio (con $)
    line_pattern = re.compile(r'(?:^|\s)(\d+)?\s*(.+?)\s*\$\s*(\d+[\s\.\d]*\d+)', re.IGNORECASE)

    with pdfplumber.open(pdf_path) as pdf:
        lineas_anteriores = []
        
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if not texto: continue

            for linea in texto.split('\n'):
                linea = linea.strip()
                if not linea: continue

                match = line_pattern.search(linea)
                
                if match:
                    cant_str = match.group(1) # Puede ser None
                    texto_intermedio = match.group(2).strip()
                    precio_str = match.group(3).replace(' ', '').replace('.', '').replace(',', '')
                    
                    try:
                        precio = Decimal(precio_str)
                        
                        # Determinar Cantidad
                        cantidad = 1 # Default
                        if cant_str and cant_str.isdigit():
                            cantidad = int(cant_str)
                        
                        # Determinar Nombre
                        # Si el texto intermedio es muy corto, quizás el nombre venía de la línea anterior
                        nombre_producto = texto_intermedio
                        if len(nombre_producto) < 4 and lineas_anteriores:
                            nombre_producto = lineas_anteriores[-1] + " " + nombre_producto
                        
                        # Limpieza final de nombre
                        nombre_producto = re.sub(r'pág\.\s*\d+', '', nombre_producto, flags=re.IGNORECASE).strip()
                        
                        if nombre_producto and precio > 0:
                            # Heurística simple para decimales si el precio es enorme sin puntos
                            if len(precio_str) > 5 and '.' not in match.group(3) and ',' not in match.group(3):
                                # A veces 1250000 es 12.500,00 -> dividir por 100?
                                # Por seguridad en listas argentinas, asumimos enteros salvo que haya coma explícita
                                pass 

                            productos_extraidos.append({
                                'nombre': nombre_producto,
                                'precio': precio,
                                'cantidad': cantidad # Nuevo campo
                            })

                    except ValueError:
                        pass

                lineas_anteriores.append(linea)
                lineas_anteriores = lineas_anteriores[-2:]
                
    return productos_extraidos