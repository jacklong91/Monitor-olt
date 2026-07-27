import os
import json
import time
import requests
from playwright.sync_api import sync_playwright

OLTS_CRITICAS = [
    "OLT3-N4BDR-ZONA3", "OLT4-Z2-VENETUR", "OLT6-ZONA1", "OLT1-N5BDPZ-ZONA3",
    "OLT2-N5BDPZ-ZONA3", "OLT1-R3-ZONA1", "OLT2-R3-ZONA1", "OLT2-Z2-ATAMO",
    "OLT5-N4BDR-ZONA3", "OLT2-R2-ZONA1-MGTA", "OLT1-N9-R1-ZONA3-MGTA", "OLT4-N4BDR-ZONA3"
]
OLTS_INACTIVAS_PERMANENTES = [
    "OLT1-R1-CGNAT1-CRPN", "OLT2-R1-CGNAT1-CRPN", "OLT1-R2-CGNAT1-CRPN"
]

def enviar_telegram(mensaje):
    token = os.environ.get('TG_TOKEN')
    chat_id = os.environ.get('TG_CHAT_ID')
    if not token or not chat_id:
        print("❌ Faltan TG_TOKEN o TG_CHAT_ID.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for cid in chat_id.split(','):
        cid = cid.strip()
        if not cid: continue
        try:
            resp = requests.post(url, data={'chat_id': cid, 'text': mensaje}, timeout=10)
            if resp.status_code == 200:
                print(f"✅ Enviado a {cid}")
            else:
                print(f"❌ Error HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"❌ Excepción: {e}")

def cargar_estado_anterior(archivo_estado):
    if not os.path.exists(archivo_estado):
        return {}
    try:
        with open(archivo_estado, "r", encoding="utf-8") as f:
            contenido = f.read().strip()
            return json.loads(contenido) if contenido else {}
    except Exception:
        return {}

def main():
    url_admin = os.environ.get('URL_ADMIN')
    user_admin = os.environ.get('USER_ADMIN')
    pass_admin = os.environ.get('PASS_ADMIN')

    archivo_estado = 'estado_olts.json'
    estado_anterior = cargar_estado_anterior(archivo_estado)

    tiempo_actual = time.time()
    ultima_alerta_rutina = estado_anterior.get('ultima_alerta_rutina', 0)
    bot_reparado_confirmado = estado_anterior.get('bot_reparado_confirmado', False)

    print("🚀 Iniciando escaneo de OLTs con Playwright...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = context.new_page()

        try:
            print("🔐 Navegando a la página de login...")
            page.goto(url_admin, timeout=60000)
            
            caja_usuario = page.locator("input[placeholder*='Usuario'], input[name='username'], input[type='text']").first
            caja_usuario.wait_for(state="visible", timeout=60000)
            caja_usuario.fill(user_admin)
            
            caja_password = page.locator("input[placeholder*='Contraseña'], input[name='password'], input[type='password']").first
            caja_password.fill(pass_admin)
            
            page.keyboard.press("Enter")
            page.wait_for_timeout(5000) 

            print("📋 Navegando a la lista de OLTs...")
            page.goto("https://wave.adminolt.com/olt/list/", timeout=60000)
            
            page.wait_for_selector("table tbody tr", timeout=45000)
            filas = page.query_selector_all("table tbody tr")
            print(f"🔍 Filas encontradas en la tabla: {len(filas)}")
            
            # 🔴 CORRECCIÓN NUEVA: Validación robusta
            if len(filas) == 0:
                raise Exception("No se encontraron filas en la tabla. Posible error de login o cambio en la web.")
            
            # Imprimir la primera fila para depurar (te servirá para entender qué está leyendo)
            primera_fila_cols = filas[0].query_selector_all("td")
            print(f"🐞 DEPURACIÓN: La primera fila tiene {len(primera_fila_cols)} columnas.")
            if len(primera_fila_cols) > 0:
                print(f"🐞 Contenido de la columna 1: '{primera_fila_cols[0].inner_text().strip()}'")

            estado_actual = {}
            caidas = []
            recuperadas = []
            
            for fila in filas:
                columnas = fila.query_selector_all("td")
                if len(columnas) >= 7:
                    nombre = columnas[2].inner_text().strip()
                    estado_raw = columnas[6].inner_text().strip()
                    estado = estado_raw.lower()
                    
                    if not nombre:
                        continue
                        
                    estado_actual[nombre] = estado_raw
                    estado_previo = estado_anterior.get(nombre)
                    if isinstance(estado_previo, str):
                        estado_previo = estado_previo.lower()
                    
                    # Lógica de filtros
                    if nombre in OLTS_INACTIVAS_PERMANENTES:
                        if estado_previo == 'offline' and estado == 'online':
                            recuperadas.append(nombre)
                        continue 
                    
                    if nombre in OLTS_CRITICAS and estado == 'offline':
                        if nombre not in caidas:
                            caidas.append(nombre)
                        continue

                    if estado_previo == 'online' and estado == 'offline':
                        if nombre not in caidas:
                            caidas.append(nombre)
                    elif estado_previo == 'offline' and estado == 'online':
                        recuperadas.append(nombre)

            # 🛑 Si no se encontró NINGUNA OLT válida (estado_actual vacío), NO guardamos el nuevo estado
            if not estado_actual:
                enviar_telegram("⚠️ ERROR CRÍTICO EN EL BOT: El script se ejecutó pero NO logró leer ninguna OLT. Revise el login o los cambios en la web. El estado anterior NO fue modificado.")
                print("❌ No se guardará el estado porque no se encontraron OLTs válidas.")
                return # Salimos sin sobrescribir el JSON

            # Si todo salió bien, recién aquí actualizamos las variables de estado
            estado_actual['ultima_alerta_rutina'] = ultima_alerta_rutina
            estado_actual['bot_reparado_confirmado'] = bot_reparado_confirmado
            
            if caidas:
                enviar_telegram(f"⚠️ ¡ALERTA CRÍTICA!\nOLTs Caídas:\n" + "\n".join(caidas))
            if recuperadas:
                enviar_telegram(f"✅ ¡RECUPERACIÓN!\nOLTs en Línea:\n" + "\n".join(recuperadas))
            
            if not bot_reparado_confirmado:
                enviar_telegram("✅ AVISO DE FUNCIONAMIENTO: El bot está monitoreando y protegiendo las OLTs correctamente.")
                estado_actual['bot_reparado_confirmado'] = True
                
            if not caidas and not recuperadas:
                if tiempo_actual - ultima_alerta_rutina >= 10800:
                    enviar_telegram("✅ Reporte de rutina: Sistema activo vigilando. Sin novedad en las OLTs.")
                    estado_actual['ultima_alerta_rutina'] = tiempo_actual
            
            with open(archivo_estado, 'w', encoding="utf-8") as f:
                json.dump(estado_actual, f, indent=4)
                
            print("✅ Escaneo completado exitosamente.")

        except Exception as e:
            error_msg = f"⚠️ Error durante el escaneo: {e}"
            print(f"❌ {error_msg}")
            enviar_telegram(error_msg)
        finally:
            browser.close()

if __name__ == "__main__":
    main()
