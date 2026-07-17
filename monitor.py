import os
import json
import requests
from playwright.sync_api import sync_playwright

# Configuraciones desde los "Secrets" de GitHub
URL_ADMIN = os.environ.get("URL_ADMIN")
USER_ADMIN = os.environ.get("USER_ADMIN")
PASS_ADMIN = os.environ.get("PASS_ADMIN")
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

ARCHIVO_ESTADO = "estado_olts.json"

def enviar_telegram(mensaje):
    lista_ids = TG_CHAT_ID.split(',')
    for chat_id in lista_ids:
        chat_id_limpio = chat_id.strip()
        if chat_id_limpio:
            url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
            payload = {"chat_id": chat_id_limpio, "text": mensaje, "parse_mode": "HTML"}
            requests.post(url, json=payload)

def obtener_estado_olts():
    olts = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # 1. Iniciar sesión
        print("Iniciando sesión...")
        page.goto(URL_ADMIN)
        page.fill("input[name='username']", USER_ADMIN)
        page.fill("input[name='password']", PASS_ADMIN)
        page.click("button[type='submit']")
        
        # Esperar a que pase el login
        page.wait_for_load_state('networkidle')
        
        # 2. Ir directamente a la lista de OLTs que me pasaste
        print("Navegando a la tabla de OLTs...")
        page.goto("https://wave.adminolt.com/olt/list/")
        
        # 3. Esperar pacientemente (hasta 15 seg) a que la tabla aparezca
        print("Esperando a que carguen los datos...")
        page.wait_for_selector("table tbody tr", timeout=15000)
        
        # 4. Extraer los datos
        print("Leyendo filas...")
        filas = page.query_selector_all("table tbody tr")
        
        for fila in filas:
            columnas = fila.query_selector_all("td")
            
            # Verificamos que la fila tenga al menos 6 columnas
            if len(columnas) >= 6:
                # La Columna 3 (índice 2) es el nombre de la OLT
                nombre_olt = columnas[2].inner_text().strip()
                # La Columna 6 (índice 5) es el Estado (Online/Offline)
                estado_olt = columnas[5].inner_text().strip()
                
                if nombre_olt:
                    olts[nombre_olt] = estado_olt
        
        browser.close()
    return olts

def main():
    print("Iniciando escaneo...")
    try:
        estado_actual = obtener_estado_olts()
        print(f"OLTs encontradas: {estado_actual}")
    except Exception as e:
        print(f"Error en el navegador: {e}")
        return

    if not estado_actual:
        print("No se encontraron OLTs. El archivo JSON quedará vacío.")
        return

    # Leer la memoria del robot
    if os.path.exists(ARCHIVO_ESTADO):
        with open(ARCHIVO_ESTADO, "r") as f:
            try:
                estado_anterior = json.load(f)
            except:
                estado_anterior = {}
    else:
        estado_anterior = {}

    # Comparar estados y enviar alertas
    for olt, estado in estado_actual.items():
        estado_previo = estado_anterior.get(olt)
        
        # Si la OLT ya existía en la memoria y su estado cambió
        if estado_previo and estado_previo != estado:
            if "Offline" in estado or "offline" in estado.lower():
                mensaje = f"🚨 <b>ALERTA DE CAÍDA</b> 🚨\n\nLa OLT <b>{olt}</b> se ha desconectado.\nEstado actual: <b>{estado}</b>"
                enviar_telegram(mensaje)
            elif "Online" in estado or "online" in estado.lower():
                mensaje = f"✅ <b>OLT RECUPERADA</b> ✅\n\nLa OLT <b>{olt}</b> vuelve a estar en línea.\nEstado actual: <b>{estado}</b>"
                enviar_telegram(mensaje)

    # Guardar la nueva memoria
    with open(ARCHIVO_ESTADO, "w") as f:
        json.dump(estado_actual, f, indent=4)
    print("Proceso finalizado correctamente.")

if __name__ == "__main__":
    main()
    
