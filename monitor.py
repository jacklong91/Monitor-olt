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
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("Iniciando sesión...")
        page.goto(URL_ADMIN, wait_until="networkidle", timeout=60000)
        
        try:
            print("Esperando a que la página y los scripts de analítica carguen...")
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
            print(f"URL actual en el error: {page.url}")
            page.screenshot(path="error_login.png")
            print("Se ha guardado 'error_login.png'. Revísalo en los Artifacts.")
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
            if len(columnas) > 0:
                textos_columnas = [col.inner_text().strip() for col in columnas]
                print(f"Fila {i} detectada en crudo: {textos_columnas}")
                
                if len(columnas) >= 2:
                    nombre_olt = columnas[2].inner_text().strip()
                    
                    # 1. Si la OLT ya la guardamos (porque se repite con los puertos), la saltamos
                    if nombre_olt in olts:
                        continue
                    
                    # 2. Intentar detectar el estado real (Online o Offline)
                    estado_olt = "Online" # Valor por defecto para que no falle nunca
                    
                    # A. Buscar en el texto de todas las columnas
                    for col in columnas:
                        texto_columna = col.inner_text().strip().lower()
                        if "online" in texto_columna:
                            estado_olt = "Online"
                            break
                        elif "offline" in texto_columna:
                            estado_olt = "Offline"
                            break
                    
                    # B. Buscar en la clase CSS de la fila (si la pintan de verde/rojo)
                    clase_fila = fila.get_attribute("class")
                    if clase_fila:
                        clase_fila = clase_fila.lower()
                        if "online" in clase_fila:
                            estado_olt = "Online"
                        elif "offline" in clase_fila:
                            estado_olt = "Offline"
                    
                    # C. (Opcional) Buscar en la columna 7 que podría tener el icono
                    if len(columnas) >= 8:
                        clase_col7 = columnas[7].get_attribute("class")
                        if clase_col7:
                            clase_col7 = clase_col7.lower()
                            if "online" in clase_col7:
                                estado_olt = "Online"
                            elif "offline" in clase_col7:
                                estado_olt = "Offline"

                    # Guardamos la OLT con el estado detectado (o "Online" por defecto)
                    if nombre_olt != "":
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
