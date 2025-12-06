import re
from decimal import Decimal
from datetime import datetime
import pdfplumber
from difflib import get_close_matches

def parse_decimal(str_val):
    """Convierte strings de dinero ($1.200,50) a Decimal."""
    if not str_val: return Decimal(0)
    # Limpiar moneda y espacios
    clean = str_val.replace('$', '').replace('U$S', '').replace('USD', '').strip()
    
    # Lógica para detectar miles vs decimales (formato latino)
    if ',' in clean and '.' in clean:
        # Caso 1.200,50 -> Borrar punto, cambiar coma por punto
        clean = clean.replace('.', '').replace(',', '.')
    elif ',' in clean:
        # Caso 1200,50 -> Cambiar coma por punto
        clean = clean.replace(',', '.')
    
    try:
        return Decimal(clean)
    except:
        return Decimal(0)

def extraer_fecha(texto):
    """Intenta extraer fecha con múltiples formatos."""
    # 1. Formatos numéricos (dd/mm/yyyy)
    date_pattern = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', texto)
    if date_pattern:
        date_str = date_pattern.group(1)
        for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%Y-%m-%d'):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError: continue
    
    # 2. Formatos con texto (noviembre 10, 2025)
    meses = {
        'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04', 'mayo': '05', 'junio': '06',
        'julio': '07', 'agosto': '08', 'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
    }
    for linea in texto.split('\n'):
        linea_lower = linea.lower()
        if any(m in linea_lower for m in meses):
            for mes_nombre, mes_num in meses.items():
                if mes_nombre in linea_lower:
                    # Busca digitos cercanos
                    nums = re.findall(r'\d+', linea)
                    if len(nums) >= 2:
                        # Asumimos que el año es el numero de 4 digitos (2025) y el dia es el de 1 o 2 (10)
                        anio = next((n for n in nums if len(n) == 4), None)
                        dia = next((n for n in nums if len(n) in [1,2] and n != anio), None)
                        
                        if anio and dia:
                            try:
                                return datetime.strptime(f"{dia}/{mes_num}/{anio}", "%d/%m/%Y").date()
                            except: pass
    return None

def extraer_items_tabla(pdf):
    """
    Estrategia 1: Usar la detección nativa de tablas de pdfplumber.
    Funciona bien para facturas con lineas dibujadas o columnas claras.
    """
    items = []
    try:
        for page in pdf.pages:
            # Intentamos extraer tablas
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    # Limpiamos valores None
                    row = [col.replace('\n', ' ').strip() if col else '' for col in row]
                    
                    # Buscamos filas que parezcan items: [Descripcion, Cant, Precio] o variaciones
                    # Heurística: Buscar un numero pequeño (cant) y uno con formato precio
                    
                    candidatos_num = []
                    candidato_desc = ""
                    
                    for col in row:
                        # Si es precio o cantidad
                        if re.match(r'^[\d.,$ ]+$', col) and len(col) < 15:
                            val = parse_decimal(col)
                            if val > 0: candidatos_num.append(val)
                        elif len(col) > 3:
                            candidato_desc = col
                            
                    if len(candidatos_num) >= 2 and candidato_desc:
                        # Asumimos: el menor es cantidad, el mayor es precio unitario (o total)
                        candidatos_num.sort()
                        cant = candidatos_num[0]
                        precio = candidatos_num[1] # A veces es unitario, a veces total. Asumimos unitario si hay 3 numeros?
                        
                        # Filtros anti-ruido
                        if "TOTAL" in candidato_desc.upper() or "SUBTOTAL" in candidato_desc.upper(): continue
                        
                        items.append({
                            'cantidad': cant,
                            'producto': candidato_desc,
                            'precio_unitario': precio,
                            'subtotal': cant * precio
                        })
    except: pass
    return items

def buscar_producto_db(descripcion_pdf):
    """
    Busca si la descripción del PDF coincide con algún producto en la DB.
    Retorna el nombre del producto en DB si hay coincidencia, sino None.
    """
    # Importación diferida para evitar ciclos
    from .models import ProductoPrecio
    
    # Obtenemos todos los nombres de productos de la base de datos
    nombres_productos = list(ProductoPrecio.objects.values_list('nombre_publico', flat=True))
    
    # Usamos get_close_matches para encontrar la mejor coincidencia
    # cutoff=0.6 significa que debe haber al menos un 60% de similitud
    coincidencias = get_close_matches(descripcion_pdf, nombres_productos, n=1, cutoff=0.6)
    
    if coincidencias:
        return coincidencias[0]
    return None

def procesar_texto_completo(texto):
    """
    Estrategia 2: Regex Multilínea sobre todo el texto + Búsqueda en DB.
    """
    items = []
    
    # --- PATRÓN CSV MULTILÍNEA (Tu Factura) ---
    # Busca: "Cualquier texto", "Numero", "Precio"
    pattern_csv_multiline = re.compile(r'"((?:[^"]|\n)*?)"\s*,\s*"([\d.,\n\s]+)"\s*,\s*"\$?\s*([\d.,\n\s]+)"', re.DOTALL)
    
    matches = pattern_csv_multiline.findall(texto)
    for m in matches:
        desc, cant_raw, precio_raw = m
        
        # Limpieza
        desc = desc.replace('\n', ' ').strip()
        # Ignorar encabezados
        if "PRODUCTO" in desc.upper() and "CANTIDAD" in desc.upper(): continue
        if "NUMERO DE PEDIDO" in desc.upper(): continue
        
        cantidad = parse_decimal(cant_raw.replace('\n',''))
        precio = parse_decimal(precio_raw.replace('\n',''))
        
        # Intentar mejorar la descripción con la base de datos
        nombre_db = buscar_producto_db(desc)
        producto_final = nombre_db if nombre_db else desc

        if cantidad > 0 and precio > 0:
            items.append({
                'cantidad': cantidad,
                'producto': producto_final,
                'precio_unitario': precio,
                'subtotal': cantidad * precio
            })
            
    if items: return items

    # --- PATRÓN TICKET/ESTÁNDAR ---
    lines = texto.split('\n')
    pattern_std = re.compile(r'^\s*(\d+(?:[.,]\d+)?)\s+(.+?)\s+\$?\s*([\d.,]+)') # Cant Desc Precio
    pattern_ticket = re.compile(r'^\s*(\d+(?:[.,]\d+)?)\s+\$?\s*([\d.,]+)\s+(.+)') # Cant Precio Desc

    for line in lines:
        line = line.strip()
        if not line: continue
        
        # Anti-ruido
        upper = line.upper()
        if "TOTAL" in upper or "SUBTOTAL" in upper or "FECHA" in upper: continue

        item = None
        match_std = pattern_std.search(line)
        if match_std:
            c, d, p = match_std.groups()
            # Verificamos si la descripción coincide con algún producto en DB
            nombre_db = buscar_producto_db(d)
            if nombre_db:
                # Si coincide, confiamos plenamente en esta línea
                item = (c, nombre_db, p)
            elif any(char.isalpha() for char in d) and len(d)>2:
                # Si no coincide pero parece texto válido, lo tomamos igual
                item = (c, d, p)
        
        if not item:
            match_t = pattern_ticket.search(line)
            if match_t:
                c, p, d = match_t.groups()
                nombre_db = buscar_producto_db(d)
                if nombre_db:
                    item = (c, nombre_db, p)
                elif any(char.isalpha() for char in d):
                    item = (c, d, p)
        
        if item:
            c_val = parse_decimal(item[0])
            p_val = parse_decimal(item[2])
            if c_val > 0 and p_val > 0:
                items.append({
                    'cantidad': c_val,
                    'producto': item[1].strip(),
                    'precio_unitario': p_val,
                    'subtotal': c_val * p_val
                })

    return items

def extraer_datos_factura(file_path):
    """Función principal."""
    texto_completo = ""
    items = []
    fecha = None
    
    try:
        with pdfplumber.open(file_path) as pdf:
            # 1. Intentar extracción de texto
            for page in pdf.pages:
                txt = page.extract_text()
                if txt: texto_completo += txt + "\n"
            
            # 2. Intentar extracción de tablas (Mejor para estructuras limpias)
            items_tabla = extraer_items_tabla(pdf)
            if items_tabla:
                items = items_tabla
            
            # 3. Si tablas falló o devolvió poco, usamos Regex Multilínea (Mejor para tu factura CSV)
            if not items or len(items) == 0:
                items = procesar_texto_completo(texto_completo)

            # 4. Extraer Fecha
            fecha = extraer_fecha(texto_completo)
            
        if not texto_completo.strip():
            return {'fecha': None, 'items': [], 'raw_text': "El PDF parece ser una imagen sin texto. Escanea con OCR."}

    except Exception as e:
        return {'fecha': None, 'items': [], 'raw_text': f"Error leyendo PDF: {e}"}

    return {
        'fecha': fecha,
        'items': items,
        'raw_text': texto_completo
    }