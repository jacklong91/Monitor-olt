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
            
            print("⏳ Esperando a que la tabla cargue los datos reales...")
            try:
                page.wait_for_selector("text=Cargando...", state="detached", timeout=60000)
                print("✅ El mensaje de 'Cargando...' ha desaparecido.")
            except Exception:
                print("ℹ️ No se encontró el mensaje de carga, la tabla ya podría estar lista.")
            
            page.wait_for_selector("table tbody tr", timeout=45000)
            
            filas = page.query_selector_all("table tbody tr")
            print(f"🔍 Filas encontradas en la tabla: {len(filas)}")
            
            if len(filas) == 0:
                raise Exception("No se encontraron filas en la tabla.")
            
            estado_actual = {}
            caidas = []
            recuperadas = []
            
            # ============ DEPURACIÓN PROFUNDA DE LA PRIMERA FILA ============
            primera_fila = filas[0]
            columnas_debug = primera_fila.query_selector_all("td")
            print("🔎 DEPURACIÓN PROFUNDA DE LA PRIMERA FILA:")
            for i, col in enumerate(columnas_debug):
                texto = col.inner_text().strip()
                print(f"   Columna [{i}]: '{texto}'")
            # =================================================================

            for fila in filas:
                columnas = fila.query_selector_all("td")
                if len(columnas) >= 7:
                    nombre = columnas[2].inner_text().strip()
                    
                    # =========== AQUÍ ESTABA EL PROBLEMA DE ÍNDICE ===========
                    # Vamos a cambiar para buscar usando el nombre de la columna o un método más robusto
                    # Pero primero, basándonos en la depuración, ajustaremos el índice.
                    # Si en el log de arriba ves "Columna [X]: 'Offline'", sabrás que X es el índice.
                    # Mientras tanto, el código sigue apuntando a [4] pero con logs más claros
                    estado_raw = columnas[4].inner_text().strip() 
                    estado = estado_raw.strip().lower()
                    
                    # CORRECCIÓN: Si estado_raw sigue estando vacío, usaremos un selector de respaldo intentando buscar el estado por XPath dentro de la fila
                    if not estado_raw: 
                        try:
                            # Intentamos buscar la etiqueta span o div que tenga la clase de color o el texto 'Online'/'Offline'
                            estado_element = fila.locator("td >> nth=4").inner_text().strip()
                            if estado_element:
                                estado_raw = estado_element
                        except:
                            pass
                        estado = estado_raw.strip().lower()
                    # =========================================================
                    
                    if not nombre:
                        continue
                        
                    # Log para saber qué está pasando exactamente con cada OLT
                    print(f"🧪 OLT: {nombre} | Estado leído: '{estado_raw}' -> Procesado: '{estado}'")
                    
                    estado_actual[nombre] = estado_raw
                    estado_previo = estado_anterior.get(nombre)
                    if isinstance(estado_previo, str):
                        estado_previo = estado_previo.lower()
                    
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

            if not estado_actual:
                enviar_telegram("⚠️ ERROR CRÍTICO: El bot no logró leer ninguna OLT.")
                return
            
            if caidas:
                enviar_telegram(f"⚠️ ¡ALERTA CRÍTICA!\nOLTs Caídas:\n" + "\n".join(caidas))
            if recuperadas:
                enviar_telegram(f"✅ ¡RECUPERACIÓN!\nOLTs en Línea:\n" + "\n".join(recuperadas))
            
            if not caidas and not recuperadas:
                print("ℹ️ No hay cambios de estado. Todo en orden.")

            with open(archivo_estado, 'w', encoding="utf-8") as f:
                json.dump(estado_actual, f, indent=4)
                
            print("✅ Escaneo completado exitosamente.")

        except Exception as e:
            print(f"❌ Error: {e}")
            enviar_telegram(f"⚠️ Error en el bot: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
