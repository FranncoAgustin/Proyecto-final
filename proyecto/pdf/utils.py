import pdfplumber
import re
from decimal import Decimal
from difflib import SequenceMatcher

def extraer_precios_de_pdf(pdf_path):
    """
    Extrae productos y precios de un PDF analizando el texto y buscando patrones.
    
    Retorna:
        list: Lista de diccionarios, e.g., [{'nombre': 'Taza', 'precio': 2400.00}]
    """
    productos_extraidos = []
    
    # Expresión regular para buscar patrones de precios.
    # Busca el símbolo '$', seguido de dígitos, opcionalmente con puntos/espacios
    # como separadores de miles y hasta dos decimales.
    # El patrón puede ser: $2300, $ 4200, $123.45, etc.
    # Hacemos una versión simple y flexible: $ seguido de uno o más dígitos, 
    # opcionalmente con espacios o puntos intermedios.
    price_pattern = re.compile(r'\$\s*(\d+[\s\.\d]*\d+)', re.IGNORECASE)

    with pdfplumber.open(pdf_path) as pdf:
        lineas_anteriores = []
        
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if not texto:
                continue

            # Analizar el texto línea por línea
            for linea in texto.split('\n'):
                linea = linea.strip()
                if not linea:
                    continue

                # 1. Buscar precios usando la expresión regular
                match = price_pattern.search(linea)
                
                if match:
                    # El precio encontrado: ej. '4150' o '12 130'
                    precio_str = match.group(1).replace(' ', '').replace('.', '').replace(',', '')
                    
                    try:
                        # Convertir a Decimal, asumiendo que el patrón encontrado es el precio
                        precio = Decimal(precio_str)
                        
                        # El nombre del producto es la parte de la línea ANTES del precio
                        # o la línea inmediatamente anterior, si la actual solo tiene el precio.
                        
                        # Opción 1: Extraer nombre de la misma línea (antes del $)
                        nombre_producto = linea[:match.start()].strip()
                        
                        # Opción 2: Usar la línea anterior si el nombre actual es muy corto
                        if len(nombre_producto) < 5 and lineas_anteriores:
                            # Tomar la última línea que NO sea un precio o un encabezado de página
                            nombre_producto = lineas_anteriores[-1]
                            
                        # Limpieza final
                        nombre_producto = re.sub(r'pág\.\s*\d+', '', nombre_producto, flags=re.IGNORECASE).strip()
                        
                        if nombre_producto:
                            productos_extraidos.append({
                                'nombre': nombre_producto,
                                'precio': precio / 100 if len(precio_str) > 4 and '.' not in match.group(1) else precio # Heurística para decimales
                            })

                    except ValueError:
                        # Ignorar si no se puede convertir a número
                        pass

                # Almacenar la línea actual para usarla como "nombre_producto" en la siguiente iteración
                # si la siguiente línea solo contiene el precio.
                lineas_anteriores.append(linea)
                # Limitar el historial para evitar contaminación
                lineas_anteriores = lineas_anteriores[-2:]
                
    return productos_extraidos

def get_similarity(a, b):
    """Calcula el porcentaje de similitud entre dos cadenas."""
    # Normalizar para mejor comparación (todo minúsculas y sin espacios extra)
    a = re.sub(r'[^a-zA-Z0-9]', '', a).lower()
    b = re.sub(r'[^a-zA-Z0-9]', '', b).lower()
    
    if not a or not b:
        return 0.0
        
    return round(SequenceMatcher(None, a, b).ratio() * 100, 2)