import os
import json
import requests
from playwright.sync_api import sync_playwright

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
        
        print("Iniciando sesión...")
        page.goto(URL_ADMIN)
        page.fill("input[name='username']", USER_ADMIN)
        page.fill("input[name='password']", PASS_ADMIN)
        page.click("button[type='submit']")
        page.wait_for_load_state('networkidle')
        
        print("Navegando a la tabla de OLTs...")
        page.goto("https://wave.adminolt.com/olt/list/")
        page.wait_for_timeout(10000) 
        
        print("Leyendo datos finales...")
        filas = page.query_selector_all("tr")
        
        for fila in filas:
            columnas = fila.query_selector_all("td")
            
            # Verificamos que tenga suficientes columnas para llegar a la 6
            if len(columnas) >= 7:
                nombre_olt = columnas[2].inner_text().strip()
                # ¡LAS COORDENADAS CORRECTAS!
                estado_olt = columnas[6].inner_text().strip()
                
                # Guardamos solo si tiene un nombre y el estado dice Online u Offline
                if nombre_olt != "" and ("Online" in estado_olt or "Offline" in estado_olt):
                    olts[nombre_olt] = estado_olt
                    print(f"Equipo guardado en memoria: {nombre_olt} -> {estado_olt}")
        
        browser.close()
    return olts

def main():
    print("Iniciando escaneo...")
    try:
        estado_actual = obtener_estado_olts()
        print(f"Total de OLTs listas para monitorear: {estado_actual}")
    except Exception as e:
        print(f"Error en el navegador: {e}")
        return

    if not estado_actual:
        print("No se encontraron OLTs válidas.")
        return

    if os.path.exists(ARCHIVO_ESTADO):
        with open(ARCHIVO_ESTADO, "r") as f:
            try:
                estado_anterior = json.load(f)
            except:
                estado_anterior = {}
    else:
        estado_anterior = {}

    # Mensaje de bienvenida la primera vez que lee las OLTs con éxito
    if not estado_anterior:
        mensaje_inicio = "🤖 <b>BOT DE MONITOREO INICIADO</b> 🤖\n\nEl sistema ha registrado tus equipos exitosamente y ya está vigilando 24/7."
        enviar_telegram(mensaje_inicio)

    for olt, estado in estado_actual.items():
        estado_previo = estado_anterior.get(olt)
        
        # Comparamos si el estado cambió para enviar la alerta
        if estado_previo and estado_previo != estado:
            if "Offline" in estado or "offline" in estado.lower():
                enviar_telegram(f"🚨 <b>ALERTA DE CAÍDA</b> 🚨\n\nLa OLT <b>{olt}</b> se ha desconectado.\nEstado actual: <b>{estado}</b>")
            elif "Online" in estado or "online" in estado.lower():
                enviar_telegram(f"✅ <b>OLT RECUPERADA</b> ✅\n\nLa OLT <b>{olt}</b> vuelve a estar en línea.\nEstado actual: <b>{estado}</b>")

    with open(ARCHIVO_ESTADO, "w") as f:
        json.dump(estado_actual, f, indent=4)
    print("Proceso finalizado correctamente.")

if __name__ == "__main__":
    main()
