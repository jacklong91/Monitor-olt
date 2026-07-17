import os
import json
import sys
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
            try:
                r = requests.post(url, json=payload)
                print(f"DIAGNÓSTICO TELEGRAM -> Servidor respondió: {r.status_code} - {r.text}")
            except Exception as e:
                print(f"DIAGNÓSTICO TELEGRAM -> Error al conectar: {e}")

def obtener_estado_olts():
    olts = {}
    with sync_playwright() as p:
        # headless=True es obligatorio para GitHub Actions
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("Iniciando sesión...")
        # Cambiamos el "goto" para que espere a que la red esté totalmente inactiva
        page.goto(URL_ADMIN, wait_until="networkidle", timeout=60000)
        
        # --- CORRECCIÓN PARA CARGAR SCRIPTS LENTOS ---
        try:
            print("Esperando a que los scripts de analítica terminen de ejecutarse...")
            page.wait_for_timeout(3000) # Pausa de 3 segundos adicionales para que Google Tag Manager cargue
            
            print("Esperando que el campo de usuario esté visible (Tiempo de espera: 60 segundos)...")
            # Aumentamos a 60000ms (60 segundos) porque las máquinas de GitHub son lentas
            page.wait_for_selector("input[name='username']", timeout=60000)
            
            print("Rellenando credenciales...")
            page.fill("input[name='username']", USER_ADMIN)
            page.fill("input[name='password']", PASS_ADMIN)
            
            print("Haciendo clic en el botón de inicio...")
            page.click("button[type='submit']")
            
        except Exception as e:
            # --- DIAGNÓSTICO PARA SABER QUÉ ESTÁ PASANDO ---
            print(f"❌ ERROR CRÍTICO EN EL LOGIN: {e}")
            print(f"URL actual en el error: {page.url}")
            
            # Vista previa del HTML
            html_preview = page.content()[:500]
            print(f"Vista previa del HTML: {html_preview}")
            
            # Captura de pantalla
            page.screenshot(path="error_login.png")
            print("Se ha guardado 'error_login.png'. Revísalo en los Artifacts de GitHub Actions.")
            
            # Esto es fundamental: RELANZAMOS EL ERROR para que el script falle de verdad
            raise e
        # ---------------------------------------------

        # Esperar a que la página redirija tras el login y se estabilice
        page.wait_for_load_state('networkidle')
        
        print("Navegando a la tabla de OLTs...")
        # Si el login fue exitoso, se redirige naturalmente a esta URL.
        page.goto("https://wave.adminolt.com/olt/list/")
        
        # Espera obligatoria de 10 segundos fijos para que cargue la tabla interna
        print("Esperando 10 segundos fijos para carga de datos...")
        page.wait_for_timeout(10000) 
        
        url_actual = page.url
        print(f"DIAGNÓSTICO -> URL Actual del robot: {url_actual}")
        if "login" in url_actual.lower():
            print("⚠️ ¡ALERTA! El robot fue redirigido al Login. El inicio de sesión falló o fue bloqueado.")
        
        print("Analizando tabla de OLTs...")
        filas = page.query_selector_all("tr")
        print(f"DIAGNÓSTICO -> Se encontraron {len(filas)} filas en la página.")
        
        for i, fila in enumerate(filas):
            columnas = fila.query_selector_all("td")
            if len(columnas) > 0:
                textos_columnas = [col.inner_text().strip() for col in columnas]
                print(f"Fila {i} detectada en crudo: {textos_columnas}")
                
                if len(columnas) >= 7:
                    nombre_olt = columnas[2].inner_text().strip()
                    estado_olt = columnas[6].inner_text().strip()
                    
                    if nombre_olt != "" and ("online" in estado_olt.lower() or "offline" in estado_olt.lower()):
                        olts[nombre_olt] = estado_olt
                        print(f"-> Guardado con éxito: {nombre_olt} está {estado_olt}")
        
        browser.close()
    return olts

def main():
    print("Iniciando escaneo...")
    try:
        estado_actual = obtener_estado_olts()
        print(f"Resultado final del escaneo: {estado_actual}")
    except Exception as e:
        # Si falla el login, este bloque capturará el "raise e" y saldrá con error real
        print(f"Error crítico en el navegador: {e}")
        sys.exit(1) # IMPORTANTE: Esto hace que GitHub Actions marque el workflow como FRACASO (Rojo)

    if not estado_actual:
        print("❌ ERROR: No se pudo extraer ninguna OLT válida en este intento.")
        sys.exit(1) # Misma razón: marcar como fallido para que veas la X roja y los artefactos

    # Cargar memoria anterior
    if os.path.exists(ARCHIVO_ESTADO):
        with open(ARCHIVO_ESTADO, "r") as f:
            try:
                estado_anterior = json.load(f)
            except:
                estado_anterior = {}
    else:
        estado_anterior = {}

    # Si es la primera vez que corre con éxito, enviamos el mensaje de bienvenida
    if not estado_anterior:
        print("Primer ejecución exitosa. Enviando bienvenida a Telegram...")
        mensaje_inicio = "🤖 <b>BOT DE MONITOREO INICIADO</b> 🤖\n\nEl sistema se ha conectado con éxito a tus OLTs y comenzó la vigilancia 24/7."
        enviar_telegram(mensaje_inicio)

    # Comparar estados
    for olt, estado in estado_actual.items():
        estado_previo = estado_anterior.get(olt)
        
        if estado_previo and estado_previo != estado:
            if "offline" in estado.lower():
                enviar_telegram(f"🚨 <b>ALERTA DE CAÍDA</b> 🚨\n\nLa OLT <b>{olt}</b> se ha desconectado.\nEstado actual: <b>{estado}</b>")
            elif "online" in estado.lower():
                enviar_telegram(f"✅ <b>OLT RECUPERADA</b> ✅\n\nLa OLT <b>{olt}</b> vuelve a estar en línea.\nEstado actual: <b>{estado}</b>")

    # Guardar estado actual en la memoria
    with open(ARCHIVO_ESTADO, "w") as f:
        json.dump(estado_actual, f, indent=4)
    print("Proceso finalizado correctamente.")

if __name__ == "__main__":
    main()
