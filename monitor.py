import os
import json
import time
import requests
from playwright.sync_api import sync_playwright

def enviar_telegram(mensaje):
    token = os.environ.get('TG_TOKEN')
    chat_id = os.environ.get('TG_CHAT_ID')
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    for cid in chat_id.split(','):
        requests.post(url, data={'chat_id': cid.strip(), 'text': mensaje})

def main():
    url_admin = os.environ.get('URL_ADMIN')
    user_admin = os.environ.get('USER_ADMIN')
    pass_admin = os.environ.get('PASS_ADMIN')

    archivo_estado = 'estado_olts.json'
    estado_anterior = {}
    if os.path.exists(archivo_estado):
        with open(archivo_estado, 'r') as f:
            estado_anterior = json.load(f)

    tiempo_actual = time.time()
    ultima_alerta_rutina = estado_anterior.get('ultima_alerta_rutina', 0)

    print("Iniciando escaneo...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Identificador para evitar bloqueos
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36")
        page = context.new_page()

        try:
            print("Iniciando sesión...")
            page.goto(url_admin, timeout=60000)
            
            # Esperamos a que la página cargue completamente
            page.wait_for_load_state("networkidle")
            
            # Imprimimos el título de la página. Si dice algo como "Just a moment...", sabemos que nos bloquearon.
            print(f"El bot está viendo esta página: {page.title()}")
            
            # --- TU INICIO DE SESIÓN MEJORADO ---
            # En lugar de buscar un solo nombre, le damos varias opciones (name, id, o simplemente la primera caja de texto) para que no falle.
            caja_usuario = page.locator("input[name='username'], input#username, input[type='text']").first
            caja_usuario.wait_for(state="visible", timeout=60000)
            caja_usuario.fill(user_admin)
            
            caja_password = page.locator("input[name='password'], input#password, input[type='password']").first
            caja_password.fill(pass_admin)
            
            page.keyboard.press("Enter")
            
            # Esperamos 5 segundos obligatorios para que cargue el inicio de sesión
            page.wait_for_timeout(5000) 
            
            print("Navegando a la lista de OLTs...")
            page.goto("https://wave.adminolt.com/olt/list/", timeout=60000)
            page.wait_for_timeout(10000) 
            
            filas = page.query_selector_all("table tbody tr")
            
            estado_actual = {}
            caidas = []
            recuperadas = []
            
            for fila in filas:
                columnas = fila.query_selector_all("td")
                if len(columnas) >= 7:
                    nombre = columnas[2].inner_text().strip()
                    estado = columnas[6].inner_text().strip()
                    
                    if not nombre:
                        continue
                        
                    estado_actual[nombre] = estado
                    
                    if nombre in estado_anterior:
                        if estado_anterior[nombre] == 'Online' and estado == 'Offline':
                            caidas.append(nombre)
                        elif estado_anterior[nombre] == 'Offline' and estado == 'Online':
                            recuperadas.append(nombre)
            
            estado_actual['ultima_alerta_rutina'] = ultima_alerta_rutina
            
            if caidas:
                enviar_telegram(f"⚠️ ¡ALERTA CRÍTICA!\nOLTs Caídas:\n" + "\n".join(caidas))
            if recuperadas:
                enviar_telegram(f"✅ ¡RECUPERACIÓN!\nOLTs en Línea:\n" + "\n".join(recuperadas))
                
            # --- REPORTE CADA 3 HORAS (10800 Segundos) ---
            if not caidas and not recuperadas:
                if tiempo_actual - ultima_alerta_rutina >= 10800: 
                    enviar_telegram("✅ Reporte de rutina: Sistema activo vigilando. Sin novedad en las OLTs.")
                    estado_actual['ultima_alerta_rutina'] = tiempo_actual 
            
            with open(archivo_estado, 'w') as f:
                json.dump(estado_actual, f)
                
            print("Escaneo completado exitosamente.")

        except Exception as e:
            print(f"Error en el navegador: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
            browser.close()

if __name__ == "__main__":
    main()
