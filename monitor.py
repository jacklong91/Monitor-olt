import os
import json
import time
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

# =========================================================================
# CONFIGURACION DE OLTs CRITICAS (Deben estar SIEMPRE en Online)
# =========================================================================
OLTS_CRITICAS = [
    "OLT3-N4BDR-ZONA3",
    "OLT4-Z2-VENETUR",
    "OLT6-ZONA1",
    "OLT1-N5BDPZ-ZONA3",
    "OLT2-N5BDPZ-ZONA3",
    "OLT1-R3-ZONA1",
    "OLT2-R3-ZONA1",
    "OLT2-Z2-ATAMO",
    "OLT5-N4BDR-ZONA3",
    "OLT2-R2-ZONA1-MGTA",
    "OLT1-N9-R1-ZONA3-MGTA",
    "OLT4-N4BDR-ZONA3"
]

# =========================================================================
# CONFIGURACION DE OLTs APAGADAS / SIN TRABAJAR (Siempre en Offline)
# Solo alertaran si cambian a ONLINE.
# =========================================================================
OLTS_INACTIVAS_PERMANENTES = [
    "OLT1-R1-CGNAT1-CRPN",
    "OLT2-R1-CGNAT1-CRPN",
    "OLT1-R2-CGNAT1-CRPN"
]

def enviar_telegram(mensaje):
    token = os.environ.get('TG_TOKEN')
    chat_id = os.environ.get('TG_CHAT_ID')
    if not token or not chat_id:
        print("⚠️ Advertencia: Falta el token o chat id de Telegram.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    for cid in chat_id.split(','):
        try:
            requests.post(url, data={'chat_id': cid.strip(), 'text': mensaje}, timeout=15)
        except Exception as e:
            print(f"❌ Error de red al intentar enviar mensaje a Telegram: {e}")

def cargar_estado_anterior(archivo_estado):
    if not os.path.exists(archivo_estado):
        print("ℹ️ No existe estado_olts.json. Se creara uno nuevo.")
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
                raise ValueError("La variable URL_ADMIN esta vacia.")
                
            page.goto(url_admin, timeout=60000)
            
            caja_usuario = page.locator("input[placeholder*='Usuario'], input[name='username'], input[type='text']").first
            caja_usuario.wait_for(state="visible", timeout=60000)
            caja_usuario.fill(user_admin)
            
            caja_password = page.locator("input[placeholder*='Contrasena'], input[name='password'], input[type='password']").first
            caja_password.fill(pass_admin)
            
            page.keyboard.press("Enter")
            
            page.wait_for_timeout(5000) 
            
            print("Navegando a la lista de OLTs...")
            page.goto("https://wave.adminolt.com/olt/list/", timeout=60000)
            
            print("⏳ Esperando 10 segundos para que la tabla cargue completamente...")
            page.wait_for_timeout(10000)

            filas = page.query_selector_all("table tbody tr")
            print(f"🔍 Filas encontradas en la tabla: {len(filas)}")
            
            if len(filas) <= 1:
                print("⚠️ Advertencia: Solo se detecto 0 o 1 fila. Es posible que los datos aun no hayan cargado.")

            estado_actual = {}
            caidas = []
            recuperadas = []
            info_temperaturas = [] # Lista para guardar los nombres y temperaturas
            
            # Preservar timestamps de caida de ejecuciones anteriores
            for key, value in estado_anterior.items():
                if key.startswith("_caida_") or key.startswith("_recuperacion_"):
                    estado_actual[key] = value
            
            for fila in filas:
                columnas = fila.query_selector_all("td")
                if len(columnas) >= 7:
                    nombre = columnas[2].inner_text().strip()
                    estado_raw = columnas[4].inner_text().strip()
                    temperatura_raw = columnas[5].inner_text().strip() # Extraemos la temperatura
                    estado = estado_raw.lower()
                    
                    if not nombre:
                        continue
                        
                    print(f"📡 Leyendo: {nombre} | Estado: {estado_raw} | Temp: {temperatura_raw}")
                    
                    # Guardamos el dato para el reporte de rutina
                    info_temperaturas.append(f"🔹 {nombre}: {temperatura_raw}")
                        
                    estado_actual[nombre] = estado_raw
                    
                    estado_previo = estado_anterior.get(nombre)
                    if isinstance(estado_previo, str):
                        estado_previo = estado_previo.lower()
                    
                    if nombre in OLTS_INACTIVAS_PERMANENTES:
                        if estado_previo == 'offline' and estado == 'online':
                            recuperadas.append(nombre)
                        continue 
                    
                    # Guardar hora de caida cuando pasa a offline
                    if estado_previo == 'online' and estado == 'offline':
                        if nombre not in caidas:
                            caidas.append(nombre)
                            # Guardar timestamp de caida en estado_actual
                            estado_actual[f"_caida_{nombre}"] = tiempo_actual
                    
                    # Calcular tiempo caido cuando se recupera
                    elif estado_previo == 'offline' and estado == 'online':
                        recuperadas.append(nombre)
                        # Guardar timestamp de recuperacion para calcular duracion
                        estado_actual[f"_recuperacion_{nombre}"] = tiempo_actual
                    
                    # Para OLTs criticas que ya estan offline (sin estado previo o primer escaneo)
                    if nombre in OLTS_CRITICAS and estado == 'offline':
                        if nombre not in caidas:
                            caidas.append(nombre)
                            # Si no tiene hora de caida guardada, registrar ahora
                            if f"_caida_{nombre}" not in estado_anterior:
                                estado_actual[f"_caida_{nombre}"] = tiempo_actual
            
            estado_actual['ultima_alerta_rutina'] = ultima_alerta_rutina
            estado_actual['bot_reparado_confirmado'] = bot_reparado_confirmado
            
            # --- ENVIO DE MENSAJES A TELEGRAM ---
            
            if caidas:
                hora_caida = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                mensaje_caida = f"🚨🔴 ¡ALERTA CRITICA DE CAIDA! 🔴🚨\n🕐 Hora de caida: {hora_caida}\n\n❌ OLT(s) OFFLINE:\n\n"
                for c in caidas:
                    mensaje_caida += f"🔻 {c}\n"
                enviar_telegram(mensaje_caida)
                
            if recuperadas:
                hora_recuperacion = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                mensaje_recuperacion = f"✅🟢 ¡RECUPERACION EXITOSA! 🟢✅\n🕐 Hora de recuperacion: {hora_recuperacion}\n\n📡 OLT(s) EN LINEA:\n\n"
                for r in recuperadas:
                    # Calcular tiempo caido
                    caida_ts = estado_anterior.get(f"_caida_{r}")
                    if caida_ts:
                        duracion_segundos = tiempo_actual - caida_ts
                        horas = int(duracion_segundos // 3600)
                        minutos = int((duracion_segundos % 3600) // 60)
                        segundos = int(duracion_segundos % 60)
                        
                        if horas > 0:
                            duracion_str = f"{horas}h {minutos}m {segundos}s"
                        elif minutos > 0:
                            duracion_str = f"{minutos}m {segundos}s"
                        else:
                            duracion_str = f"{segundos}s"
                        
                        mensaje_recuperacion += f"🔼 {r}\n   ⏱️ Tiempo caida: {duracion_str}\n"
                        
                        # Limpiar el registro de caida ya que se recupero
                        if f"_caida_{r}" in estado_actual:
                            del estado_actual[f"_caida_{r}"]
                        if f"_recuperacion_{r}" in estado_actual:
                            del estado_actual[f"_recuperacion_{r}"]
                    else:
                        mensaje_recuperacion += f"🔼 {r}\n   ⏱️ Tiempo caida: desconocido\n"
                enviar_telegram(mensaje_recuperacion)
            
            if not bot_reparado_confirmado:
                enviar_telegram("✅ AVISO: El bot esta monitoreando y protegiendo las OLTs correctamente.")
                estado_actual['bot_reparado_confirmado'] = True
                
            if not caidas and not recuperadas:
                if tiempo_actual - ultima_alerta_rutina >= 10800: # 10800 segundos = 3 horas
                    mensaje_rutina = "✅ 📊 REPORTE DE RUTINA (3 HORAS)\nSistema activo vigilando. Sin novedad en las OLTs.\n\n🌡️ TEMPERATURAS ACTUALES:\n"
                    mensaje_rutina += "\n".join(info_temperaturas)
                    enviar_telegram(mensaje_rutina)
                    estado_actual['ultima_alerta_rutina'] = tiempo_actual
            
            with open(archivo_estado, 'w', encoding="utf-8") as f:
                json.dump(estado_actual, f, indent=4)
                
            print("✅ Escaneo completado exitosamente.")

        except Exception as e:
            print(f"❌ Error general en la automatizacion: {e}")
            enviar_telegram(f"⚠️ Error temporal en el escaneo de OLTs: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
