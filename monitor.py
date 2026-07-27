import os
import json
import time
import requests
from playwright.sync_api import sync_playwright

# =========================================================================
# CONFIGURACIÓN DE OLTs CRÍTICAS (Nuevos Avances)
# =========================================================================
# Escribe aquí los nombres EXACTOS de las OLTs que SIEMPRE deben estar Online.
# Si alguna de estas aparece como 'Offline', el bot enviará la alerta de caída
# incluso si la memoria del bot se reinició recientemente.
OLTS_CRITICAS = [
    # Ejemplo: "OLT-CENTRAL-01",
    # Ejemplo: "OLT-NORTE-02"
]

def enviar_telegram(mensaje):
    token = os.environ.get('TG_TOKEN')
    chat_id = os.environ.get('TG_CHAT_ID')
    if not token or not chat_id:
        print("Falta el token o chat id de Telegram.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    for cid in chat_id.split(','):
        requests.post(url, data={'chat_id': cid.strip(), 'text': mensaje})

def cargar_estado_anterior(archivo_estado):
    """Carga la memoria guardada protegiendo el script si el JSON está vacío o corrupto."""
    if not os.path.exists(archivo_estado):
        print("ℹ️ No existe estado_olts.json. Se creará uno nuevo.")
        return {}
    try:
        with open(archivo_estado, "r", encoding="utf-8") as f:
            contenido = f.read().strip()
            if not contenido:
                return {}
            return json.loads(contenido)
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
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
        page = context.new_page()

        try:
            if not url_admin:
                raise ValueError("La variable URL_ADMIN está vacía.")
                
            page.goto(url_admin, timeout=60000)
            
            caja_usuario = page.locator("input[placeholder*='Usuario'], input[name='username'], input[type='text']").first
            caja_usuario.wait_for(state="visible", timeout=60000)
            caja_usuario.fill(user_admin)
            
            caja_password = page.locator("input[placeholder*='Contraseña'], input[name='password'], input[type='password']").first
            caja_password.fill(pass_admin)
            
            page.keyboard.press("Enter")
            page.wait_for_timeout(5000) 
            
            print("Navegando a la lista de OLTs...")
            page.goto("https://wave.adminolt.com/olt/list/", timeout=60000)
            page.wait_for_timeout(10000) 
            
            filas = page.query_selector_all("table tbody tr")
            print(f"🔍 Filas encontradas en la tabla: {len(filas)}")
            
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
                    
                    estado_previo = estado_anterior.get(nombre)
                    
                    # 1. Transición normal: Estaba Online y pasó a Offline
                    if estado_previo == 'Online' and estado == 'Offline':
                        caidas.append(nombre)
                    
                    # 2. Transición normal: Estaba Offline y pasó a Online
                    elif estado_previo == 'Offline' and estado == 'Online':
                        recuperadas.append(nombre)
                    
                    # 3. Regla de OLTs Críticas: Si está en la lista de críticas, debe estar Online sí o sí.
                    # Si aparece Offline y no hay registro previo (o memoria limpia), alerta de inmediato.
                    elif nombre in OLTS_CRITICAS and estado == 'Offline' and estado_previo != 'Offline':
                        if nombre not in caidas:
                            caidas.append(nombre)
            
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
                
            print("Escaneo completado exitosamente.")

        except Exception as e:
            print(f"❌ Error en el navegador: {e}")
            enviar_telegram(f"⚠️ Error temporal en el escaneo de OLTs: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
