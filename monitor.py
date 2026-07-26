import os
import json
import time
import requests
from playwright.sync_api import sync_playwright

def enviar_telegram(mensaje):
    token = os.environ.get('TG_TOKEN')
    chat_id = os.environ.get('TG_CHAT_ID')
    if not token or not chat_id:
        print("Falta el token o chat id de Telegram.")
        return
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
    # Variable para saber si ya te envió el mensaje de que fue reparado
    bot_reparado_confirmado = estado_anterior.get('bot_reparado_confirmado', False)

    print("Iniciando escaneo...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36")
        page = context.new_page()

        try:
            print("Iniciando sesión...")
            page.goto(url_admin, timeout=60000)
            
            # 1. BUSCAMOS POR EL TEXTO EXACTO DE LA IMAGEN QUE ME PASASTE
            # Busca la caja que contenga la palabra "Usuario"
            caja_usuario = page.locator("input[placeholder*='Usuario'], input[name='username'], input[type='text']").first
            caja_usuario.wait_for(state="visible", timeout=60000)
            caja_usuario.fill(user_admin)
            
            # Busca la caja que contenga la palabra "Contraseña"
            caja_password = page.locator("input[placeholder*='Contraseña'], input[name='password'], input[type='password']").first
            caja_password.fill(pass_admin)
            
            page.keyboard.press("Enter")
            
            # Esperamos 5 segundos
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
            estado_actual['bot_reparado_confirmado'] = bot_reparado_confirmado
            
            if caidas:
                enviar_telegram(f"⚠️ ¡ALERTA CRÍTICA!\nOLTs Caídas:\n" + "\n".join(caidas))
            if recuperadas:
                enviar_telegram(f"✅ ¡RECUPERACIÓN!\nOLTs en Línea:\n" + "\n".join(recuperadas))
            
            # === 2. TU AVISO DE FUNCIONAMIENTO ===
            # Si logra llegar hasta aquí, te enviará este mensaje a Telegram de inmediato.
            if not bot_reparado_confirmado:
                enviar_telegram("✅ AVISO DE FUNCIONAMIENTO: El bot fue reparado. Ha logrado iniciar sesión exitosamente y está leyendo la tabla de OLTs.")
                estado_actual['bot_reparado_confirmado'] = True
                
            # Tu reporte de rutina cada 3 horas
            if not caidas and not recuperadas:
                if tiempo_actual - ultima_alerta_rutina >= 10800:
                    enviar_telegram("✅ Reporte de rutina: Sistema activo vigilando. Sin novedad en las OLTs.")
                    estado_actual['ultima_alerta_rutina'] = tiempo_actual
            
            # Guardamos la información
            with open(archivo_estado, 'w') as f:
                json.dump(estado_actual, f)
                
            print("Escaneo completado exitosamente.")

        except Exception as e:
            print(f"Error en el navegador: {e}")
            # 3. SI HAY UN ERROR, AHORA TE LO AVISARÁ POR TELEGRAM
            enviar_telegram(f"⚠️ El bot se atascó o falló. Revisa GitHub. Error detectado: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
