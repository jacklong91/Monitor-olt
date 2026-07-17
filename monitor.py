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
    olts = {} # Guardará los datos usando la IP como clave única
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("Iniciando sesión...")
        page.goto(URL_ADMIN, wait_until="networkidle", timeout=60000)
        
        try:
            print("Esperando a que la página cargue...")
            page.wait_for_timeout(3000)
            
            print("Esperando el campo de 'Usuario o Email'...")
            page.get_by_placeholder("Usuario o Email").wait_for(timeout=60000)
            
            print("Rellenando credenciales...")
            page.get_by_placeholder("Usuario o Email").fill(USER_ADMIN)
            page.get_by_placeholder("Contraseña").fill(PASS_ADMIN)
            
            print("Haciendo clic en el botón 'Acceder'...")
            page.locator("button:has-text('Acceder')").click()
            
        except Exception as e:
            print(f"❌ ERROR CRÍTICO EN EL LOGIN: {e}")
            page.screenshot(path="error_login.png")
            raise e 

        page.wait_for_load_state('networkidle')
        
        print("Navegando a la tabla de OLTs...")
        page.goto("https://wave.adminolt.com/olt/list/")
        
        print("Esperando 10 segundos fijos para carga de datos...")
        page.wait_for_timeout(10000) 
        
        url_actual = page.url
        print(f"DIAGNÓSTICO -> URL Actual del robot: {url_actual}")
        if "login" in url_actual.lower():
            print("⚠️ ¡ALERTA! El robot fue redirigido al Login.")
        
        print("Analizando tabla de OLTs...")
        filas = page.query_selector_all("tr")
        print(f"DIAGNÓSTICO -> Se encontraron {len(filas)} filas en la página.")
        
        for i, fila in enumerate(filas):
            columnas = fila.query_selector_all("td")
            if len(columnas) >= 6: # La tabla tiene 6 columnas visibles
                modelo_olt = columnas[1].inner_text().strip()  # Columna "OLT"
                zona_olt = columnas[2].inner_text().strip()    # Columna "Nombre"
                ip_olt = columnas[3].inner_text().strip()      # Columna "Host" (La usaremos como ID único)
                estado_olt = columnas[4].inner_text().strip().lower() # Columna "Estado" (Online/Offline)
                
                if modelo_olt != "" and (estado_olt == "online" or estado_olt == "offline"):
                    # Usamos la IP como clave para no confundir modelos duplicados
                    clave_olt = ip_olt
                    nombre_amigable = f"{modelo_olt} ({zona_olt})"
                    
                    # Guardamos la información en el diccionario
                    olts[clave_olt] = {
                        "nombre": nombre_amigable,
                        "estado": estado_olt
                    }
                    print(f"-> OLT guardada: {nombre_amigable} -> IP: {ip_olt} -> Estado: {estado_olt}")
        
        browser.close()
    return olts

def main():
    print("Iniciando escaneo...")
    try:
        estado_actual = obtener_estado_olts()
        print(f"Resultado final del escaneo: {estado_actual}")
    except Exception as e:
        print(f"Error crítico en el navegador: {e}")
        sys.exit(1)

    if not estado_actual:
        print("❌ ERROR: No se pudo extraer ninguna OLT válida en este intento.")
        sys.exit(1)

    # Cargar memoria anterior
    if os.path.exists(ARCHIVO_ESTADO):
        with open(ARCHIVO_ESTADO, "r") as f:
            try:
                estado_anterior = json.load(f)
            except:
                estado_anterior = {}
    else:
        estado_anterior = {}

    # Si es la primera vez, enviamos bienvenida
    if not estado_anterior:
        print("Primer ejecución exitosa. Enviando bienvenida a Telegram...")
        mensaje_inicio = "🤖 <b>BOT DE MONITOREO INICIADO</b> 🤖\n\nEl sistema se ha conectado con éxito a tus OLTs y comenzó la vigilancia 24/7."
        enviar_telegram(mensaje_inicio)

    # Comparar estados actuales con los anteriores
    for clave_olt, datos in estado_actual.items():
        # clave_olt es la IP de la OLT
        estado_previo = estado_anterior.get(clave_olt, {}).get("estado")
        estado_actual_olt = datos["estado"]
        
        if estado_previo and estado_previo != estado_actual_olt:
            if "offline" in estado_actual_olt:
                enviar_telegram(f"🚨 <b>ALERTA DE CAÍDA</b> 🚨\n\nLa OLT <b>{datos['nombre']}</b> se ha desconectado.\nIP: {clave_olt}\nEstado actual: <b>{estado_actual_olt.upper()}</b>")
            elif "online" in estado_actual_olt:
                enviar_telegram(f"✅ <b>OLT RECUPERADA</b> ✅\n\nLa OLT <b>{datos['nombre']}</b> vuelve a estar en línea.\nIP: {clave_olt}\nEstado actual: <b>{estado_actual_olt.upper()}</b>")

    # Guardar estado actual en la memoria (sobrescribe el anterior)
    with open(ARCHIVO_ESTADO, "w") as f:
        json.dump(estado_actual, f, indent=4)
    print("Proceso finalizado correctamente.")

if __name__ == "__main__":
    main()
