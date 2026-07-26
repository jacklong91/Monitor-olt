import os
import json
import requests
import time
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
            try:
                requests.post(url, json=payload)
            except Exception as e:
                print(f"Error Telegram: {e}")

def obtener_estado_olts():
    olts = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("Iniciando sesión...")
        page.goto(URL_ADMIN)
        
        # Esto soluciona el error de "Timeout 30000ms" obligando a esperar a que cargue el cuadro
        page.wait_for_selector("input[name='username']", timeout=60000)
        page.fill("input[name='username']", USER_ADMIN)
        page.fill("input[name='password']", PASS_ADMIN)
        page.click("button[type='submit']")
        page.wait_for_load_state('networkidle')
        
        print("Navegando a la tabla de OLTs...")
        page.goto("https://wave.adminolt.com/olt/list/")
        page.wait_for_timeout(10000) 
        
        print("Analizando tabla...")
        filas = page.query_selector_all("tr")
        
        for fila in filas:
            columnas = fila.query_selector_all("td")
            if len(columnas) >= 7:
                nombre_olt = columnas[2].inner_text().strip()
                estado_olt = columnas[6].inner_text().strip()
                if nombre_olt != "" and ("online" in estado_olt.lower() or "offline" in estado_olt.lower()):
                    olts[nombre_olt] = estado_olt
        
        browser.close()
    return olts

def main():
    print("Iniciando escaneo...")
    try:
        estado_actual = obtener_estado_olts()
    except Exception as e:
        print(f"Error en el navegador: {e}")
        return

    if not estado_actual:
        print("No se encontraron OLTs.")
        return

    estado_anterior = {}
    ultima_notificacion = 0

    # Leer la memoria del robot (Ahora con reloj incluido)
    if os.path.exists(ARCHIVO_ESTADO):
        with open(ARCHIVO_ESTADO, "r") as f:
            try:
                datos = json.load(f)
                # Leemos los equipos y el reloj de la última notificación
                if "equipos" in datos:
                    estado_anterior = datos["equipos"]
                    ultima_notificacion = datos.get("ultima_notificacion", 0)
                else:
                    estado_anterior = datos
            except:
                pass

    # Mensaje de arranque por primera vez
    if not estado_anterior:
        enviar_telegram("🤖 <b>BOT INICIADO</b> 🤖\n\nEl sistema ya está vigilando 24/7. Te avisaré al instante si hay caídas, o cada 3 horas si todo está bien.")

    hubo_cambios = False

    # Comparar estados y enviar alertas urgentes
    for olt, estado in estado_actual.items():
        estado_previo = estado_anterior.get(olt)
        
        if estado_previo and estado_previo != estado:
            hubo_cambios = True
            if "offline" in estado.lower():
                enviar_telegram(f"🚨 <b>ALERTA DE CAÍDA</b> 🚨\n\nLa OLT <b>{olt}</b> se ha desconectado.\nEstado actual: <b>{estado}</b>")
            elif "online" in estado.lower():
                enviar_telegram(f"✅ <b>OLT RECUPERADA</b> ✅\n\nLa OLT <b>{olt}</b> vuelve a estar en línea.\nEstado actual: <b>{estado}</b>")

    tiempo_actual = time.time()
    
    # Si hubo una caída o recuperación, reiniciamos el reloj de 3 horas
    if hubo_cambios:
        ultima_notificacion = tiempo_actual
    
    # Si NO hubo cambios, verificamos si ya pasaron 3 horas (10800 segundos)
    if not hubo_cambios and (tiempo_actual - ultima_notificacion) >= 10800:
        # Enviar el reporte de tranquilidad
        enviar_telegram("🕒 <b>REPORTE DE RUTINA</b> 🕒\n\n✅ <b>Sin Novedad:</b> El sistema sigue escaneando automáticamente. Ninguna OLT ha presentado caídas en las últimas 3 horas.")
        # Reiniciamos el reloj para que cuente otras 3 horas
        ultima_notificacion = tiempo_actual

    # Guardar la nueva memoria y el reloj
    datos_a_guardar = {
        "equipos": estado_actual,
        "ultima_notificacion": ultima_notificacion
    }

    with open(ARCHIVO_ESTADO, "w") as f:
        json.dump(datos_a_guardar, f, indent=4)
        
    print("Proceso finalizado correctamente.")

if __name__ == "__main__":
    main()
