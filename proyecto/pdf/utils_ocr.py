import pytesseract
from PIL import Image
import re
from decimal import Decimal
from datetime import datetime
import os
import pdfplumber
from pdf2image import convert_from_path

# ⚠️ RUTAS WINDOWS (Ajusta según tu instalación)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
POPPLER_PATH = r'C:\Program Files\poppler-24.02.0\Library\bin' 

def parse_decimal(str_val):
    """Convierte strings de dinero ($1.200,50) a Decimal."""
    if not str_val: return Decimal(0)
    # Limpiar moneda y espacios
    clean = str_val.replace('$', '').replace('U$S', '').replace('USD', '').strip()
    
    # Lógica para detectar miles vs decimales
    if ',' in clean and '.' in clean:
        # Caso 1.200,50 -> Borrar punto, cambiar coma por punto
        clean = clean.replace('.', '').replace(',', '.')
    elif ',' in clean:
        # Caso 1200,50 -> Cambiar coma por punto
        clean = clean.replace(',', '.')
    # Caso 1200.50 -> Se deja igual (python lo entiende)
    
    try:
        return Decimal(clean)
    except:
        return Decimal(0)

def procesar_texto_factura(texto):
    """
    Analiza el texto línea por línea intentando múltiples estrategias
    para extraer ítems (Cantidad, Descripción, Precio).
    """
    datos = {'fecha': None, 'items': [], 'raw_text': texto}
    lines = texto.split('\n')

    # --- 1. BUSCAR FECHA ---
    # Busca formatos comunes dd/mm/yyyy o dd-mm-yyyy
    date_pattern = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', texto)
    if date_pattern:
        date_str = date_pattern.group(1)
        for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%Y-%m-%d'):
            try:
                datos['fecha'] = datetime.strptime(date_str, fmt).date()
                break
            except ValueError: continue

    # --- 2. BUSCAR ÍTEMS (Estrategia Multi-Patrón) ---
    
    # Patrón A (CSV/Digital): "Descripción","Cantidad","Precio" (Tu primer PDF)
    pattern_csv_like = re.compile(r'"(.+?)","(\d+(?:[.,]\d+)?)","\$?\s*([\d.,]+)"')

    # Patrón B (Estándar): Cantidad ... Descripción ... Precio
    pattern_std = re.compile(r'^\s*(\d+(?:[.,]\d+)?)\s+(.+?)\s+\$?\s*([\d.,]+)')

    # Patrón C (Ticket): Cantidad ... Precio ... Total ... Descripción
    pattern_ticket = re.compile(r'^\s*(\d+(?:[.,]\d+)?)\s+\$?\s*([\d.,]+)\s+(.+)')

    for line in lines:
        line = line.strip()
        if not line: continue
        
        # Ignorar líneas basura comunes
        upper_line = line.upper()
        if "TOTAL" in upper_line or "SUBTOTAL" in upper_line or "FECHA" in upper_line:
            continue
        if "CAJERO" in upper_line or "PAGO" in upper_line:
            continue

        item = None

        # INTENTO 1: Formato CSV/Comillas
        match_csv = pattern_csv_like.search(line)
        if match_csv:
            desc, cant_str, precio_str = match_csv.groups()
            item = {
                'cantidad': parse_decimal(cant_str),
                'producto': desc.strip(),
                'precio_unitario': parse_decimal(precio_str)
            }

        # INTENTO 2: Formato Estándar (Cant - Desc - Precio)
        if not item:
            match_std = pattern_std.search(line)
            if match_std:
                cant_str, desc, precio_str = match_std.groups()
                if any(c.isalpha() for c in desc):
                    item = {
                        'cantidad': parse_decimal(cant_str),
                        'producto': desc.strip(),
                        'precio_unitario': parse_decimal(precio_str)
                    }

        # INTENTO 3: Formato Ticket (Cant - Precio - Desc)
        if not item:
            match_ticket = pattern_ticket.search(line)
            if match_ticket:
                cant_str, precio_str, desc = match_ticket.groups()
                if any(c.isalpha() for c in desc):
                    item = {
                        'cantidad': parse_decimal(cant_str),
                        'producto': desc.strip(),
                        'precio_unitario': parse_decimal(precio_str)
                    }

        # Si encontramos un ítem válido, lo agregamos
        if item:
            item['subtotal'] = item['cantidad'] * item['precio_unitario']
            if len(item['producto']) > 2 and item['precio_unitario'] > 0:
                datos['items'].append(item)
    
    return datos

def extraer_datos_factura(file_path):
    """
    Función maestra: Maneja Imágenes y PDFs (Digitales y Escaneados).
    """
    texto_completo = ""
    es_pdf = file_path.lower().endswith('.pdf')

    try:
        if es_pdf:
            print("Intentando leer como PDF digital...")
            try:
                with pdfplumber.open(file_path) as pdf:
                    for page in pdf.pages:
                        texto_pag = page.extract_text(layout=True) 
                        if texto_pag:
                            texto_completo += texto_pag + "\n"
            except Exception as e:
                print(f"Advertencia pdfplumber: {e}")

            # Si no hay texto, asumimos que es escaneado
            if len(texto_completo.strip()) < 10:
                print("PDF parece escaneado, usando OCR...")
                try:
                    images = convert_from_path(file_path, poppler_path=POPPLER_PATH)
                    for img in images:
                        texto_completo += pytesseract.image_to_string(img, lang='spa') + "\n"
                except Exception as e:
                    return {'fecha': None, 'items': [], 'raw_text': f"Error Poppler: {e}"}
        else:
            # Imagen Directa
            img = Image.open(file_path)
            texto_completo = pytesseract.image_to_string(img, lang='spa')

    except Exception as e:
        return {'fecha': None, 'items': [], 'raw_text': f"Error general: {e}"}

    return procesar_texto_factura(texto_completo)