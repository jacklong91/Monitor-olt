import os
import json
import time
import logging
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# =========================================================================
# CONFIGURACIÓN DE LOGGING
# =========================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("olt_monitor")

# =========================================================================
# CONFIGURACIÓN DE OLTs
# =========================================================================
OLTS_CRITICAS = {
    "OLT3-N4BDR-ZONA3", "OLT4-Z2-VENETUR", "OLT6-ZONA1",
    "OLT1-N5BDPZ-ZONA3", "OLT2-N5BDPZ-ZONA3", "OLT1-R3-ZONA1",
    "OLT2-R3-ZONA1", "OLT2-Z2-ATAMO", "OLT5-N4BDR-ZONA3",
    "OLT2-R2-ZONA1-MGTA", "OLT1-N9-R1-ZONA3-MGTA", "OLT4-N4BDR-ZONA3"
}

OLTS_INACTIVAS_PERMANENTES = {
    "OLT1-R1-CGNAT1-CRPN", "OLT2-R1-CGNAT1-CRPN", "OLT2-R2-CGNAT1-CRPN"
}

ARCHIVO_ESTADO = "estado_olts.json"
INTERVALO_SEGUNDOS = 300          # 5 minutos
INTERVALO_RUTINA_SEGUNDOS = 10800 # 3 horas

# =========================================================================
# UTILIDADES
# =========================================================================
def enviar_telegram(mensaje: str) -> None:
    token = os.environ.get("TG_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID")
    if not token or not chat_id:
        logger.warning("Falta TG_TOKEN o TG_CHAT_ID")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for cid in chat_id.split(","):
        try:
            requests.post(
                url,
                data={"chat_id": cid.strip(), "text": mensaje, "parse_mode": "HTML"},
                timeout=15
            )
        except Exception as e:
            logger.error(f"Error enviando a Telegram (chat {cid.strip()}): {e}")

def cargar_estado() -> dict:
    if not os.path.exists(ARCHIVO_ESTADO):
        logger.info("No existe estado previo, se creará uno nuevo.")
        return {}
    try:
        with open(ARCHIVO_ESTADO, "r", encoding="utf-8") as f:
            contenido = f.read().strip()
            return json.loads(contenido) if contenido else {}
    except Exception as e:
        logger.error(f"Error leyendo estado: {e}")
        return {}

def guardar_estado(estado: dict) -> None:
    try:
        with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
            json.dump(estado, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error guardando estado: {e}")

# =========================================================================
# SCRAPING
# =========================================================================
def extraer_datos_olts(page, estado_anterior: dict) -> tuple[dict, list, list, list]:
    """
    Retorna: (estado_actual, caidas, recuperadas, cambios_detalle)
    """
    logger.info("Navegando a lista de OLTs...")
    page.goto("https://wave.adminolt.com/olt/list/", timeout=60000)
    
    # Espera moderna con locator en vez de sleep fijo
    try:
        page.locator("table tbody tr").first.wait_for(state="visible", timeout=15000)
    except PlaywrightTimeout:
        logger.warning("La tabla no cargó en 15s, esperando 10s adicionales...")
        page.wait_for_timeout(10000)

    filas = page.locator("table tbody tr").all()
    logger.info(f"Filas detectadas: {len(filas)}")

    estado_actual = {}
    caidas = []
    recuperadas = []
    cambios_detalle = []  # ← NUEVO: lista de strings con cada cambio detectado

    for fila in filas:
        celdas = fila.locator("td").all()
        if len(celdas) < 7:
            continue

        nombre = celdas[2].inner_text().strip()
        estado_raw = celdas[4].inner_text().strip()
        temperatura_raw = celdas[5].inner_text().strip()
        estado = estado_raw.lower()

        if not nombre:
            continue

        # Guardar estado actual
        estado_actual[nombre] = {
            "estado": estado_raw,
            "temperatura": temperatura_raw,
            "timestamp": datetime.now().isoformat()
        }

        # Comparar con estado anterior
        prev = estado_anterior.get(nombre)
        if isinstance(prev, dict):
            prev_estado = prev.get("estado", "").lower()
            prev_temp = prev.get("temperatura", "N/A")
        else:
            # Compatibilidad con versiones antiguas donde solo guardabas string
            prev_estado = str(prev).lower() if prev else ""
            prev_temp = "N/A"

        # --- DETECTAR CAMBIOS DETALLADOS ---
        cambios_olt = []

        if prev_estado and prev_estado != estado:
            if estado == "offline":
                cambios_olt.append("❌ Pasó a OFFLINE")
            elif estado == "online":
                cambios_olt.append("✅ Pasó a ONLINE")
            else:
                cambios_olt.append(f"🔄 Estado cambió: {prev_estado.upper()} → {estado_raw}")

        if prev_temp != temperatura_raw and prev_temp != "N/A":
            cambios_olt.append(f"🌡️ Temperatura cambió: {prev_temp} → {temperatura_raw}")

        if cambios_olt:
            cambios_detalle.append(f"📡 <b>{nombre}</b>:\n" + "\n".join(f"   {c}" for c in cambios_olt))

        # --- LÓGICA DE ALERTAS ---
        if nombre in OLTS_INACTIVAS_PERMANENTES:
            if prev_estado == "offline" and estado == "online":
                recuperadas.append(nombre)
            continue

        if nombre in OLTS_CRITICAS and estado == "offline":
            if nombre not in caidas:
                caidas.append(nombre)
            continue

        if prev_estado == "online" and estado == "offline":
            if nombre not in caidas:
                caidas.append(nombre)
        elif prev_estado == "offline" and estado == "online":
            if nombre not in recuperadas:
                recuperadas.append(nombre)

    return estado_actual, caidas, recuperadas, cambios_detalle

# =========================================================================
# LOGIN
# =========================================================================
def hacer_login(page, url: str, usuario: str, password: str) -> None:
    page.goto(url, timeout=60000)

    page.locator("input[placeholder*='Usuario'], input[name='username'], input[type='text']").first.wait_for(state="visible", timeout=30000)
    page.locator("input[placeholder*='Usuario'], input[name='username'], input[type='text']").first.fill(usuario)

    page.locator("input[placeholder*='Contraseña'], input[name='password'], input[type='password']").first.fill(password)
    page.keyboard.press("Enter")

    # Esperar redirección o indicador de login exitoso
    page.wait_for_timeout(3000)

# =========================================================================
# CICLO PRINCIPAL
# =========================================================================
def ciclo_monitoreo(estado_anterior: dict) -> dict:
    url = os.environ.get("URL_ADMIN")
    user = os.environ.get("USER_ADMIN")
    pwd = os.environ.get("PASS_ADMIN")

    if not all([url, user, pwd]):
        raise ValueError("Faltan variables de entorno URL_ADMIN, USER_ADMIN o PASS_ADMIN")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            hacer_login(page, url, user, pwd)
            estado_actual, caidas, recuperadas, cambios_detalle = extraer_datos_olts(page, estado_anterior)

            # Preservar metadatos del estado anterior
            estado_actual["ultima_alerta_rutina"] = estado_anterior.get("ultima_alerta_rutina", 0)
            estado_actual["bot_reparado_confirmado"] = estado_anterior.get("bot_reparado_confirmado", False)

            # --- ENVÍO DE ALERTAS ---
            ahora = time.time()

            # 1. Caídas críticas
            if caidas:
                msg = "🚨 <b>¡ALERTA CRÍTICA DE CAÍDA!</b> 🚨\n\n❌ OLT(s) OFFLINE:\n"
                for c in caidas:
                    msg += f"🔻 {c}\n"
                enviar_telegram(msg)

            # 2. Recuperaciones
            if recuperadas:
                msg = "✅ <b>¡RECUPERACIÓN EXITOSA!</b> ✅\n\n📡 OLT(s) EN LÍNEA:\n"
                for r in recuperadas:
                    msg += f"🔼 {r}\n"
                enviar_telegram(msg)

            # 3. Detalle de cambios menores (temperatura, etc.) — NUEVO
            if cambios_detalle and not caidas and not recuperadas:
                msg = "📝 <b>CAMBIOS DETECTADOS</b> (sin caídas)\n\n" + "\n\n".join(cambios_detalle)
                enviar_telegram(msg)

            # 4. Confirmación de bot activo (solo una vez)
            if not estado_actual["bot_reparado_confirmado"]:
                enviar_telegram("✅ <b>AVISO:</b> El bot está monitoreando y protegiendo las OLTs correctamente.")
                estado_actual["bot_reparado_confirmado"] = True

            # 5. Reporte de rutina cada 3h si no hubo eventos
            if not caidas and not recuperadas and not cambios_detalle:
                if ahora - estado_actual["ultima_alerta_rutina"] >= INTERVALO_RUTINA_SEGUNDOS:
                    temps = []
                    for nombre, datos in estado_actual.items():
                        if isinstance(datos, dict) and "temperatura" in datos:
                            temps.append(f"🔹 {nombre}: {datos['temperatura']}")

                    msg = ("✅ <b>REPORTE DE RUTINA (3 HORAS)</b>\n"
                           "Sistema activo. Sin novedades.\n\n"
                           "🌡️ <b>TEMPERATURAS ACTUALES:</b>\n" + "\n".join(temps))
                    enviar_telegram(msg)
                    estado_actual["ultima_alerta_rutina"] = ahora

            logger.info("Escaneo completado exitosamente.")
            return estado_actual

        except Exception as e:
            logger.error(f"Error en monitoreo: {e}")
            enviar_telegram(f"⚠️ <b>Error temporal en el escaneo:</b>\n<code>{e}</code>")
            # Devolver estado anterior para no perder datos en caso de error
            return estado_anterior

        finally:
            browser.close()

# =========================================================================
# MAIN CON BUCLE INFINITO
# =========================================================================
def main():
    logger.info("=" * 50)
    logger.info("Iniciando monitor de OLTs v2.0")
    logger.info(f"Intervalo: {INTERVALO_SEGUNDOS}s | Rutina: {INTERVALO_RUTINA_SEGUNDOS}s")
    logger.info("=" * 50)

    estado = cargar_estado()

    while True:
        try:
            inicio = time.time()
            estado = ciclo_monitoreo(estado)
            guardar_estado(estado)

            duracion = time.time() - inicio
            espera = max(0, INTERVALO_SEGUNDOS - duracion)
            logger.info(f"Ciclo duró {duracion:.1f}s. Próximo escaneo en {espera:.0f}s.")
            time.sleep(espera)

        except KeyboardInterrupt:
            logger.info("Detenido por el usuario.")
            break
        except Exception as e:
            logger.critical(f"Error fatal en el bucle principal: {e}")
            enviar_telegram(f"🔥 <b>Error fatal del bot:</b>\n<code>{e}</code>\nReiniciando en 60s...")
            time.sleep(60)

if __name__ == "__main__":
    main()
