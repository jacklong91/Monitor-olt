import os
import json
import requests
from playwright.sync_api import sync_playwright

# Obtenemos las variables seguras de GitHub
URL = os.environ.get('URL_ADMIN')
USER = os.environ.get('USER_ADMIN')
PASSWORD = os.environ.get('PASS_ADMIN')
TG_TOKEN = os.environ.get('TG_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

ESTADO_FILE = 'estado_olts.json'

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
    requests.post(url, json=payload)

def cargar_memoria():
    if os.path.exists(ESTADO_FILE):
        with open(ESTADO_FILE, 'r') as f:
            return json.load(f)
    return {}

def guardar_memoria(datos):
    with open(ESTADO_FILE, 'w') as f:
        json.dump(datos, f)

def main():
    memoria_anterior = cargar_memoria()
    memoria_nueva = {}
    
    with sync_playwright() as p:
        # Iniciar navegador en modo invisible (headless)
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            print("Navegando al login...")
            page.goto(URL, timeout=60000)
            
            # --- NOTA: DEPENDIENDO DE TU ADMINOLT, ESTOS SELECTORES PUEDEN CAMBIAR ---
            # Llenamos el formulario de login y enviamos
            page.fill('input[name="username"]', USER) # o el name que use tu login
            page.fill('input[name="password"]', PASSWORD)
            page.click('button[type="submit"]')
            
            # Esperamos a que cargue la tabla (hasta 30 segundos)
            print("Esperando la tabla de OLTs...")
            page.wait_for_selector('table tbody tr', timeout=30000)
            
            filas = page.query_selector_all('table tbody tr')
            caidas = []
            recuperadas = []
            
            for fila in filas:
                columnas = fila.query_selector_all('td')
                if len(columnas) < 5:
                    continue
                
                nombre = columnas[2].inner_text().strip()
                estado_texto = columnas[4].inner_text().strip()
                
                estado_actual = 'Online' if 'Online' in estado_texto else 'Offline' if 'Offline' in estado_texto else 'Desconocido'
                
                if estado_actual == 'Desconocido':
                    continue
                
                memoria_nueva[nombre] = estado_actual
                
                estado_previo = memoria_anterior.get(nombre)
                
                if estado_previo == 'Online' and estado_actual == 'Offline':
                    caidas.append(nombre)
                elif estado_previo == 'Offline' and estado_actual == 'Online':
                    recuperadas.append(nombre)
            
            # Lógica de envío de alertas
            if caidas:
                txt = "⚠️ <b>¡ALERTA OLT CAÍDA!</b> ⚠️\n\nEquipos:\n" + "\n".join([f"• <code>{c}</code>" for c in caidas])
                enviar_telegram(txt)
                print("Alerta de caída enviada.")
                
            if recuperadas:
                txt = "✅ <b>¡RECUPERACIÓN OLT!</b> ✅\n\nEquipos de nuevo en línea:\n" + "\n".join([f"• <code>{r}</code>" for r in recuperadas])
                enviar_telegram(txt)
                print("Alerta de recuperación enviada.")

            # Guardamos el estado actual para la próxima ejecución
            guardar_memoria(memoria_nueva)
            
        except Exception as e:
            print(f"Error durante el escaneo: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
