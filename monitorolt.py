import os
import re
import json
import time
import requests
import socket
import atexit
import signal
import sys
import traceback
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# =========================================================================
# CONFIGURACION
# =========================================================================
script_dir = os.path.dirname(os.path.abspath(__file__))

def log(msg):
    """Solo imprime a consola, sin archivo"""
    print(msg)

def clear_screen():
    """Limpia la consola solo si hay terminal real (cls en Windows, clear en Linux)."""
    try:
        if sys.stdout.isatty():
            os.system('cls' if os.name == 'nt' else 'clear')
    except Exception:
        pass

# =========================================================================
# CARGAR .ENV
# =========================================================================
env_path = os.path.join(script_dir, '.env')
log("=" * 60)
log("INICIANDO MONITOR DE OLTs")
log(f"Script directory: {script_dir}")
log(f"Env path: {env_path}")
log(f"Env exists: {os.path.exists(env_path)}")

if os.path.exists(env_path):
    load_dotenv(env_path)
    log("✅ Archivo .env cargado")
else:
    log("❌ ERROR: No se encontro .env")
    sys.exit(1)

def _lista_desde_env(nombre_variable, predeterminada):
    """Permite mover las listas al .env del servidor.

    Con el repositorio publico, los nombres reales de las OLTs y del equipo
    pueden vivir solo en el .env. Si la variable no esta, se usa el valor
    por defecto del codigo y el bot sigue funcionando igual.
    Formato: separados por coma. Ej: OLTS_CRITICAS=OLT1-X,OLT2-Y
    """
    crudo = os.environ.get(nombre_variable, '') or ''
    valores = [v.strip() for v in crudo.split(',') if v.strip()]
    return valores or list(predeterminada)

# =========================================================================
# OLTs CRITICAS
# =========================================================================
OLTS_CRITICAS = _lista_desde_env('OLTS_CRITICAS', [
    "OLT3-N4BDR-ZONA3",
    "OLT4-Z2-VENETUR",
    "OLT6-ZONA1",
    "OLT1-N5BDPZ-ZONA3",
    "OLT2-N5BDPZ-ZONA3",
    "OLT1-R3-ZONA1",
    "OLT2-R3-ZONA1",
    "OLT5-N4BDR-ZONA3",
    "OLT2-R2-ZONA1-MGTA",
    "OLT1-N9-R1-ZONA3-MGTA",
    "OLT4-N4BDR-ZONA3"
])

OLTS_INACTIVAS_PERMANENTES = _lista_desde_env('OLTS_INACTIVAS_PERMANENTES', [
    "OLT1-R1-CGNAT1-CRPN",
    "OLT2-R1-CGNAT1-CRPN",
    "OLT1-R2-CGNAT1-CRPN",
    "OLT2-Z2-ATAMO"
])

INTERVALO_SEGUNDOS = 30
INTERVALO_REPETIR_ALERTA_CAIDA = 900  # 15 minutos

# =========================================================================
# NUEVOS UMBRALES CONFIGURABLES
# =========================================================================
UMBRAL_REINICIO_SEGUNDOS = 15 * 60      # <= 15 min encendida = posible reinicio
UMBRAL_REINICIO_INMINENTE_SEGUNDOS = 60 # < 1 min encendida = ACABA DE REINICIARSE

# =========================================================================
# MAPEO DE ZONAS (por codigo dentro del nombre de la OLT)
# Agrupa las OLTs por zona en la plantilla de afectacion.
# Orden importa: se toma la primera coincidencia.
# =========================================================================
ZONAS = [
    ("BDPZ",    "Boca de pozo"),
    ("BDR",     "Boca de rio"),
    ("VENETUR", "Venetur"),
    ("ZONA1",   "Zona 1"),
    ("ZONA3",   "Zona 3"),
]

def zona_de_olt(nombre):
    upper = nombre.upper()
    for codigo, zona in ZONAS:
        if codigo in upper:
            return zona
    return "Otras zonas"

def agrupar_por_zona(nombres):
    grupos = {}
    for n in nombres:
        z = zona_de_olt(n)
        grupos.setdefault(z, []).append(n)
    return grupos

# =========================================================================
# EQUIPO (nombres que se muestran al final de la plantilla de reinicio)
# En un canal no existen menciones (@); solo se listan los nombres como texto.
# =========================================================================
NOMBRES_EQUIPO = _lista_desde_env('NOMBRES_EQUIPO', [
    "Solorzano | Wave",
    "Maydkol Narváez | Wave",
    "Jose Mierez | Wave",
    "Jefry Colina | Wave",
    "Rossi Contact | Wave",
])

def linea_equipo():
    """Devuelve la linea final con los nombres del equipo (texto plano, sin @)."""
    return "  ·  ".join(NOMBRES_EQUIPO)

# =========================================================================
# FORMATO DE FECHA / HORA
# =========================================================================
def saludo_por_hora():
    h = datetime.now().hour
    if 5 <= h < 12:
        return "Buenos días"
    elif 12 <= h < 19:
        return "Buenas tardes"
    return "Buenas noches"

def formato_hora_12h(dt=None):
    dt = dt or datetime.now()
    h = dt.hour % 12
    h = 12 if h == 0 else h
    suf = "a.m." if dt.hour < 12 else "p.m."
    return f"{h}:{dt.minute:02d} {suf}"

def formato_duracion(segundos):
    segundos = int(segundos)
    h = segundos // 3600
    m = (segundos % 3600) // 60
    s = segundos % 60
    if h > 0:
        return f"{h}h {m}min"
    if m > 0:
        return f"{m}min {s}s"
    return f"{s}s"

# =========================================================================
# FUNCIONES TELEGRAM
# =========================================================================
def enviar_telegram(mensaje):
    token = os.environ.get('TG_TOKEN')
    chat_id = os.environ.get('TG_CHAT_ID')
    if not token or not chat_id:
        log("⚠️ Falta TG_TOKEN o TG_CHAT_ID")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for cid in chat_id.split(','):
        try:
            resp = requests.post(url, data={'chat_id': cid.strip(), 'text': mensaje}, timeout=15)
            log(f"📤 Telegram enviado a {cid.strip()}: status={resp.status_code}")
            return True
        except Exception as e:
            log(f"❌ Error Telegram: {e}")
    return False

def enviar_mensaje(mensaje):
    """Envia por Telegram."""
    return enviar_telegram(mensaje)

cierre_notificado = False
salida_planificada = False

def enviar_mensaje_reconexion():
    try:
        enviar_mensaje("✅ Conexión restablecida. El monitoreo de OLTs está activo nuevamente. 📡")
    except Exception as e:
        log(f"Error enviando mensaje de reconexion: {e}")

def enviar_mensaje_sin_internet():
    try:
        enviar_mensaje("🔌 Se detectó pérdida de conexión a internet. El monitoreo de OLTs está temporalmente fuera de servicio. ⏳")
    except Exception as e:
        log(f"Error enviando mensaje sin internet: {e}")

def enviar_mensaje_cierre():
    """Avisa al canal SOLO si el bot muere de forma inesperada.

    Un paro planificado (systemctl stop, reinicio del servidor, despliegue
    de una version nueva) no debe anunciar una incidencia que no existe.
    """
    global cierre_notificado
    if salida_planificada or cierre_notificado:
        return
    if os.environ.get('AVISO_CIERRE_INESPERADO', '1').strip() != '1':
        return
    cierre_notificado = True
    try:
        enviar_mensaje("⚠️ Estamos presentando un inconveniente. En breve estaremos de vuelta monitoreando las OLTs. 🔄")
    except Exception as e:
        log(f"Error enviando mensaje de cierre: {e}")

# Registrar manejadores de cierre
atexit.register(enviar_mensaje_cierre)

def manejar_senal(signum, frame):
    """Paro planificado: sale en silencio y sin duplicar el aviso."""
    global salida_planificada
    salida_planificada = True
    log(f"🚫 Señal recibida ({signum}). Cerrando (paro planificado, sin aviso al canal).")
    sys.exit(0)

signal.signal(signal.SIGINT, manejar_senal)
signal.signal(signal.SIGTERM, manejar_senal)

# =========================================================================
# PLANTILLAS DE MENSAJES
# =========================================================================
def construir_plantilla_caida(caidas, estado_actual, estado_anterior, tiempo_actual):
    """Plantilla de afectacion (caida) con agrupacion por zona."""
    inicios = []
    for c in caidas:
        ts = estado_actual.get(f"_caida_{c}") or estado_anterior.get(f"_caida_{c}")
        if ts:
            inicios.append(ts)
    inicio = min(inicios) if inicios else tiempo_actual
    dt_inicio = datetime.fromtimestamp(inicio)
    afectacion = max(0, int(tiempo_actual - inicio))

    lineas = ["Para la hora presentamos afectación en las siguientes OLTs:", ""]
    grupos = agrupar_por_zona(caidas)
    for zona, nombres in grupos.items():
        lineas.append(f"📍 {zona}")
        for n in nombres:
            lineas.append(f"• {n}")
        lineas.append("")
    lineas.append(f"📅 Fecha de incidencia: {dt_inicio.strftime('%d/%m/%Y')}")
    lineas.append(f"🕐 Hora de incidencia: {formato_hora_12h(dt_inicio)}")
    lineas.append("✅ Hora de solución: Pendiente")
    lineas.append(f"⏱️ Tiempo bajo afectación: {formato_duracion(afectacion)}")
    lineas.append("📌 Status: 🔴 Pendiente")
    return "\n".join(lineas)

def construir_plantilla_restablecimiento(recuperadas, estado_anterior, tiempo_actual):
    """Plantilla de restablecimiento (recuperacion) con agrupacion por zona."""
    dt = datetime.now()
    lineas = ["Se restablecieron las siguientes OLTs:", ""]
    grupos = agrupar_por_zona(recuperadas)
    for zona, nombres in grupos.items():
        lineas.append(f"📍 {zona}")
        for n in nombres:
            caida_ts = estado_anterior.get(f"_caida_{n}")
            if caida_ts:
                dur = formato_duracion(tiempo_actual - caida_ts)
                lineas.append(f"• {n}  (caída: {dur})")
            else:
                lineas.append(f"• {n}")
        lineas.append("")
    lineas.append(f"📅 Fecha de solución: {dt.strftime('%d/%m/%Y')}")
    lineas.append(f"🕐 Hora de solución: {formato_hora_12h(dt)}")
    lineas.append("📌 Status: 🟢 Resuelto")
    return "\n".join(lineas)

def construir_plantilla_reinicio(reinicios, reinicios_criticos):
    """Plantilla de reinicio (solo OLTs que NUNCA cayeron, pero se reiniciaron)."""
    nombres = [n for n, _ in (reinicios_criticos + reinicios)]
    dt = datetime.now()
    lineas = [f"{saludo_por_hora()}, equipo", ""]
    lineas.append(f"Se informa que se presentó un reinicio de las siguientes OLT a las {formato_hora_12h(dt)}")
    lineas.append("")
    for n in nombres:
        lineas.append(f"• {n}")
    lineas.append("")
    lineas.append("Se están verificando los servicios adscritos a las OLT")
    lineas.append("")
    lineas.append(f"Para su conocimiento {linea_equipo()}")
    return "\n".join(lineas)

# =========================================================================
# FUNCIONES AUXILIARES
# =========================================================================
def verificar_internet():
    """Verifica si hay conexion a internet"""
    try:
        requests.get("https://www.google.com", timeout=5)
        return True
    except:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except:
            return False

def cargar_estado_anterior(archivo_estado):
    if not os.path.exists(archivo_estado):
        return {}
    try:
        with open(archivo_estado, "r", encoding="utf-8") as f:
            contenido = f.read().strip()
            return json.loads(contenido) if contenido else {}
    except Exception as e:
        log(f"⚠️ Error leyendo estado_olts.json: {e}")
        return {}

def parsear_uptime(texto):
    """
    Convierte el 'Tiempo Encendida' de AdminOLT a segundos.
    Soporta formatos como:
      '54 days, 3:13:09'  ->  54*86400 + 3*3600 + 13*60 + 9
      '3 days, 19:41.50'
      'X min, Y sec' / 'X horas' / '15:32'
    Devuelve None si no aplica ('---', vacío o formato no reconocido).
    """
    if not texto:
        return None
    t = texto.strip().lower()
    if t in ('---', '--', '-', '', 'n/a'):
        return None
    total = 0
    dias = re.search(r'(\d+)\s*(?:days?|d[ií]as?|d\b)', t)
    if dias:
        total += int(dias.group(1)) * 86400
    horas = re.search(r'(\d+)\s*(?:hours?|hrs?|horas?|h\b)', t)
    if horas:
        total += int(horas.group(1)) * 3600
    mins = re.search(r'(\d+)\s*(?:minutes?|mins?|min\b|m\b)', t)
    if mins:
        total += int(mins.group(1)) * 60
    segs = re.search(r'(\d+)\s*(?:seconds?|secs?|seg(?:undos)?\b|s\b)', t)
    if segs:
        total += int(segs.group(1))
    # Formato HH:MM:SS o MM:SS al final ("3:13:09")
    m = re.search(r'(\d+):(\d{1,2})(?::(\d{1,2}))?(?:\.\d+)?$', t)
    if m:
        if m.group(3) is not None:
            total += int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        else:
            total += int(m.group(1)) * 60 + int(m.group(2))
    return total if total > 0 else None

def url_lista_olts():
    """Deriva la URL de la lista de OLTs desde URL_ADMIN.

    Evita dejar el dominio del panel hardcodeado en el codigo: con el repo
    publico, la URL real del AdminOLT solo vive en el .env del servidor.
    """
    base = (os.environ.get('URL_ADMIN') or '').strip()
    if not base:
        return ''
    if '/olt' in base.lower():
        return base
    return base.rstrip('/') + '/olt/list/'

def hacer_login(page, url_admin, user_admin, pass_admin):
    """Hace login una sola vez"""
    log("🔐 Iniciando sesion en AdminOLT...")
    try:
        page.goto(url_admin, timeout=60000)
        page.wait_for_timeout(2000)

        try:
            caja_usuario = page.locator("input[placeholder*='Usuario'], input[placeholder*='usuario'], input[name='username'], input[id='username'], input[placeholder*='Correo'], input[placeholder*='correo']").first
            caja_usuario.wait_for(state="visible", timeout=15000)
            caja_usuario.fill(user_admin)
        except Exception as e:
            log(f"   Usando fallback para usuario: {e}")
            page.fill("input#id_username", user_admin)

        try:
            caja_password = page.locator("input[placeholder*='Contrasena'], input[placeholder*='Contraseña'], input[name='password'], input[id='password']").first
            caja_password.fill(pass_admin)
        except Exception as e:
            log(f"   Usando fallback para password: {e}")
            page.fill("input#id_password", pass_admin)

        page.keyboard.press("Enter")
        page.wait_for_timeout(5000)
        log("✅ Sesion iniciada.")
        return True
    except Exception as e:
        log(f"❌ Error en login: {e}")
        return False

def verificar_sesion_activa(page):
    try:
        current_url = page.url
        if 'login' in current_url.lower() or 'accounts' in current_url.lower():
            return False
        return True
    except Exception:
        return False

def tabla_tiene_temperaturas(page):
    filas = page.query_selector_all("table tbody tr")
    if len(filas) <= 1:
        return False
    for fila in filas:
        columnas = fila.query_selector_all("td")
        if len(columnas) >= 6:
            temp = columnas[5].inner_text().strip()
            if temp and temp != '' and ('°' in temp or 'C' in temp or temp.replace('.','').isdigit()):
                return True
    return False

def esperar_tabla_cargada(page):
    max_refreshes = 3
    for refresh_num in range(max_refreshes):
        max_intentos = 10
        for intento in range(max_intentos):
            if tabla_tiene_temperaturas(page):
                filas = page.query_selector_all("table tbody tr")
                log(f"✅ Tabla cargada ({len(filas)} filas)")
                return True
            log(f"⏳ Esperando temperaturas... {intento + 1}/{max_intentos} (refresh {refresh_num + 1}/{max_refreshes})")
            page.wait_for_timeout(2000)
        if refresh_num < max_refreshes - 1:
            log(f"🔄 Refrescando pagina...")
            page.goto(url_lista_olts(), timeout=60000)
            page.wait_for_timeout(3000)
    log("⚠️ Temperaturas no disponibles tras 3 refreshes.")
    return False

# =========================================================================
# FUNCION PRINCIPAL DE ESCANEO
# =========================================================================
def escanear_olts(page, estado_anterior, tiempo_actual):
    archivo_estado = os.path.join(script_dir, 'estado_olts.json')
    ultima_alerta_rutina = estado_anterior.get('ultima_alerta_rutina', 0)
    bot_reparado_confirmado = estado_anterior.get('bot_reparado_confirmado', False)
    tiempo_transcurrido = tiempo_actual - ultima_alerta_rutina
    tiempo_restante = max(0, 10800 - tiempo_transcurrido)

    log(f"🚀 [{datetime.now().strftime('%H:%M:%S')}] Refrescando datos...")
    log(f"   Tiempo desde ultimo reporte: {int(tiempo_transcurrido)}s (faltan {int(tiempo_restante)}s para reporte)")

    try:
        page.goto(url_lista_olts(), timeout=60000)
        page.wait_for_timeout(3000)
        temperaturas_ok = esperar_tabla_cargada(page)

        filas = page.query_selector_all("table tbody tr")
        log(f"🔍 Filas: {len(filas)}")

        estado_actual = {}
        caidas = []
        recuperadas = []
        reinicios = []               # OLTs con 1-15 min encendida
        reinicios_criticos = []      # OLTs con < 1 min encendida (minuto cero)
        info_temperaturas = []       # temperatura + uptime + abonados

        for key, value in estado_anterior.items():
            if key.startswith("_caida_") or key.startswith("_recuperacion_") \
               or key.startswith("_alerta_caida_") or key.startswith("_reinicio_alertado_") \
               or key.startswith("_reinicio_alerta_ts_") or key.startswith("_reinicio_uptime_") \
               or key.startswith("_reciente_caida_"):
                estado_actual[key] = value

        for fila in filas:
            columnas = fila.query_selector_all("td")
            if len(columnas) >= 7:
                nombre = columnas[2].inner_text().strip()
                host = columnas[3].inner_text().strip() if len(columnas) > 3 else ''
                estado_raw = columnas[4].inner_text().strip()
                temperatura_raw = columnas[5].inner_text().strip()
                uptime_raw = columnas[6].inner_text().strip() if len(columnas) > 6 else '---'
                onus_raw = columnas[7].inner_text().strip() if len(columnas) > 7 else '?'
                estado = estado_raw.lower()
                if not nombre:
                    continue
                log(f"📡 {nombre} | {estado_raw} | {temperatura_raw} | ⏱️ {uptime_raw} | 📶 {onus_raw} ONU's")
                info_temperaturas.append(
                    f"🔹 {nombre}:\n"
                    f"   🌡️ {temperatura_raw}\n"
                    f"   ⏱️ Encendida: {uptime_raw}\n"
                    f"   👥 Abonados: {onus_raw}"
                )
                estado_actual[nombre] = estado_raw
                estado_previo = estado_anterior.get(nombre)
                if isinstance(estado_previo, str):
                    estado_previo = estado_previo.lower()

                uptime_seg = parsear_uptime(uptime_raw)

                # ===== DETECCION DE CAIDA (online -> offline) =====
                if estado_previo == 'online' and estado == 'offline':
                    if nombre not in caidas:
                        caidas.append(nombre)
                    estado_actual[f"_caida_{nombre}"] = tiempo_actual
                    estado_actual[f"_alerta_caida_enviada_{nombre}"] = 0
                    estado_actual.pop(f"_reciente_caida_{nombre}", None)

                # ===== DETECCION DE RECUPERACION (offline -> online) =====
                elif estado_previo == 'offline' and estado == 'online':
                    if nombre not in OLTS_INACTIVAS_PERMANENTES:
                        recuperadas.append(nombre)
                    estado_actual[f"_recuperacion_{nombre}"] = tiempo_actual
                    estado_actual.pop(f"_alerta_caida_enviada_{nombre}", None)
                    estado_actual.pop(f"_caida_{nombre}", None)
                    # Marcar como caida reciente para NO confundir con reinicio
                    estado_actual[f"_reciente_caida_{nombre}"] = tiempo_actual

                # ===== DETECCION DE REINICIO (SOLO si la OLT NUNCA cayo) =====
                # Reinicio REAL: la OLT estaba online, sigue online, y su uptime
                # se reinicio (valor bajo) sin haber pasado por estado offline.
                # Si estuvo offline y volvio online, es CAIDA + recuperacion,
                # NO es reinicio (aunque el uptime sea bajo).
                if estado == 'online' and uptime_seg is not None:
                    reciente_caida = estado_actual.get(f"_reciente_caida_{nombre}")
                    if reciente_caida and uptime_seg <= UMBRAL_REINICIO_SEGUNDOS:
                        # Viene de una caida: se suprime el reinicio hasta que
                        # el uptime supere el umbral (estable).
                        estado_actual[f"_reciente_caida_{nombre}"] = reciente_caida
                        log(f"   🟡 {nombre} viene de caida (uptime {uptime_raw}): no se reporta como reinicio")
                    else:
                        if reciente_caida:
                            estado_actual.pop(f"_reciente_caida_{nombre}", None)
                        if estado_previo == 'online':
                            ya_alertado = estado_anterior.get(f"_reinicio_alertado_{nombre}")
                            # Seguro anti-repeticion: nunca re-avisar el MISMO reinicio
                            # dentro de los 15 min siguientes al ultimo aviso de esta OLT
                            ult_ts_reinicio = estado_anterior.get(f"_reinicio_alerta_ts_{nombre}", 0)
                            recien_avisado = (tiempo_actual - ult_ts_reinicio) < 900
                            # Deteccion de reinicio NUEVO: el tiempo encendida retrocedio
                            uptime_previo = estado_anterior.get(f"_reinicio_uptime_{nombre}")
                            reinicio_nuevo = (
                                isinstance(uptime_previo, (int, float))
                                and uptime_seg < uptime_previo - 5
                                and uptime_seg <= UMBRAL_REINICIO_SEGUNDOS
                            )
                            estado_actual[f"_reinicio_uptime_{nombre}"] = uptime_seg

                            if uptime_seg < UMBRAL_REINICIO_INMINENTE_SEGUNDOS:
                                if reinicio_nuevo:
                                    reinicios_criticos.append((nombre, uptime_raw))
                                    estado_actual[f"_reinicio_alertado_{nombre}"] = tiempo_actual
                                    estado_actual[f"_reinicio_alerta_ts_{nombre}"] = tiempo_actual
                                    log(f"   🚨🚨 ¡SEGUNDO REINICIO! {nombre} se reinicio de nuevo ({uptime_raw})")
                                elif not ya_alertado and not recien_avisado:
                                    reinicios_criticos.append((nombre, uptime_raw))
                                    estado_actual[f"_reinicio_alertado_{nombre}"] = tiempo_actual
                                    estado_actual[f"_reinicio_alerta_ts_{nombre}"] = tiempo_actual
                                    log(f"   🚨 ¡REINICIO INMINENTE! {nombre} lleva solo {uptime_raw} encendida")
                                else:
                                    log(f"   ⏸️ Reinicio de {nombre} ya alertado. No se repite el aviso.")
                            elif uptime_seg <= UMBRAL_REINICIO_SEGUNDOS:
                                if reinicio_nuevo:
                                    reinicios.append((nombre, uptime_raw))
                                    estado_actual[f"_reinicio_alertado_{nombre}"] = tiempo_actual
                                    estado_actual[f"_reinicio_alerta_ts_{nombre}"] = tiempo_actual
                                    log(f"   🔄🔄 ¡SE REINICIO DE NUEVO! {nombre} ({uptime_raw})")
                                elif not ya_alertado and not recien_avisado:
                                    reinicios.append((nombre, uptime_raw))
                                    estado_actual[f"_reinicio_alertado_{nombre}"] = tiempo_actual
                                    estado_actual[f"_reinicio_alerta_ts_{nombre}"] = tiempo_actual
                                    log(f"   🔄 ¡Posible reinicio! {nombre} lleva {uptime_raw} encendida")
                                else:
                                    log(f"   ⏸️ Reinicio de {nombre} ya alertado. No se repite el aviso.")
                            else:
                                # Histeresis: cuando supera el umbral, se libera la bandera
                                if estado_actual.get(f"_reinicio_alertado_{nombre}"):
                                    estado_actual.pop(f"_reinicio_alertado_{nombre}", None)

                if nombre in OLTS_INACTIVAS_PERMANENTES:
                    continue

                if nombre in OLTS_CRITICAS and estado == 'offline':
                    ultima_alerta_ts = estado_anterior.get(f"_alerta_caida_enviada_{nombre}", 0)
                    tiempo_desde_alerta = tiempo_actual - ultima_alerta_ts
                    if tiempo_desde_alerta >= INTERVALO_REPETIR_ALERTA_CAIDA:
                        if nombre not in caidas:
                            caidas.append(nombre)
                        if f"_caida_{nombre}" not in estado_anterior:
                            estado_actual[f"_caida_{nombre}"] = tiempo_actual
                        estado_actual[f"_alerta_caida_enviada_{nombre}"] = tiempo_actual
                        log(f"   🔔 Alerta caida: {nombre}")
                    else:
                        min_restantes = int((INTERVALO_REPETIR_ALERTA_CAIDA - tiempo_desde_alerta) // 60)
                        log(f"   ⏸️ Caida alertada. Proxima en {min_restantes} min")

        estado_actual['ultima_alerta_rutina'] = ultima_alerta_rutina
        estado_actual['bot_reparado_confirmado'] = bot_reparado_confirmado

        # ================= MENSAJES =================
        # Se envia primero la alerta (icono) y debajo la plantilla con los datos.

        if caidas:
            msg = "🚨🔴 ¡ALERTA CRÍTICA DE CAÍDA! 🔴🚨\n\n"
            msg += construir_plantilla_caida(caidas, estado_actual, estado_anterior, tiempo_actual)
            enviar_mensaje(msg)
            log(f"📤 Alerta CAIDA enviada: {caidas}")

        if recuperadas:
            msg = "✅🟢 ¡RESTABLECIMIENTO EXITOSO! 🟢✅\n\n"
            msg += construir_plantilla_restablecimiento(recuperadas, estado_anterior, tiempo_actual)
            enviar_mensaje(msg)
            log(f"📤 Alerta RESTABLECIMIENTO enviada: {recuperadas}")

        if reinicios or reinicios_criticos:
            msg = "🔄🟠 ¡REINICIO DETECTADO! 🟠🔄\n\n"
            msg += construir_plantilla_reinicio(reinicios, reinicios_criticos)
            enviar_mensaje(msg)
            log(f"📤 Alerta REINICIO enviada: {[r[0] for r in reinicios] + [r[0] for r in reinicios_criticos]}")

        if not bot_reparado_confirmado:
            enviar_mensaje("✅ AVISO: Bot monitoreando OLTs correctamente.")
            estado_actual['bot_reparado_confirmado'] = True
            log("📤 Aviso inicio enviado")

        log(f"📊 DEBUG: caidas={len(caidas)}, recuperadas={len(recuperadas)}, "
            f"reinicios_criticos={len(reinicios_criticos)}, reinicios={len(reinicios)}, "
            f"tiempo_transcurrido={int(tiempo_transcurrido)}s")

        hubo_novedad = caidas or recuperadas or reinicios or reinicios_criticos

        if not hubo_novedad:
            if tiempo_transcurrido >= 10800:
                log("📊 DEBUG: Condiciones para reporte CUMPLIDAS")
                if temperaturas_ok and info_temperaturas:
                    msg = "✅ 📊 REPORTE DE RUTINA (3 HORAS)\nSistema activo. Sin novedad.\n\n🌡️ ESTADO DE OLTs:\n\n"
                    msg += "\n\n".join(info_temperaturas)
                    resultado = enviar_mensaje(msg)
                    if resultado:
                        estado_actual['ultima_alerta_rutina'] = tiempo_actual
                        log("📤 REPORTE RUTINA enviado (temp, tiempo encendida y abonados)")
                    else:
                        log("❌ Fallo al enviar reporte de rutina")
                else:
                    log("⚠️ Reporte omitido: temperaturas no disponibles")
            else:
                log(f"📊 DEBUG: Faltan {int(10800 - tiempo_transcurrido)}s para reporte")
        else:
            log("📊 DEBUG: Reporte omitido por novedades (caidas/recuperaciones/reinicios)")

        with open(archivo_estado, 'w', encoding="utf-8") as f:
            json.dump(estado_actual, f, indent=4)

        log(f"✅ Escaneo completado. Proximo en {INTERVALO_SEGUNDOS}s")

    except Exception as e:
        log(f"\n❌ Error interno: {e}")
        log(traceback.format_exc())
        enviar_mensaje("⚠️ Estamos presentando un inconveniente técnico. En breve estaremos de vuelta monitoreando las OLTs. 🔄")

# =========================================================================
# MAIN
# =========================================================================
def main():
    url_admin = os.environ.get('URL_ADMIN')
    user_admin = os.environ.get('USER_ADMIN')
    pass_admin = os.environ.get('PASS_ADMIN')
    tg_token = os.environ.get('TG_TOKEN')
    tg_chat_id = os.environ.get('TG_CHAT_ID')

    log("=" * 60)
    log("VERIFICACION DE CONFIGURACION:")
    log(f"  URL_ADMIN: {'OK (' + url_admin + ')' if url_admin else 'VACIA'}")
    log(f"  USER_ADMIN: {'OK' if user_admin else 'VACIA'}")
    log(f"  PASS_ADMIN: {'OK' if pass_admin else 'VACIA'}")
    log(f"  TG_TOKEN: {'OK' if tg_token else 'VACIA'}")
    log(f"  TG_CHAT_ID: {'OK (' + tg_chat_id + ')' if tg_chat_id else 'VACIA'}")
    log("=" * 60)

    if not url_admin:
        log("❌ ERROR: URL_ADMIN vacia")
        sys.exit(1)
    if not user_admin or not pass_admin:
        log("❌ ERROR: USER_ADMIN o PASS_ADMIN vacios")
        sys.exit(1)

    log("💡 Navegador INVISIBLE. Sesion mantenida abierta.")
    log("💡 Envio de alertas: Telegram.")
    log("💡 Alerta de caida: 1 vez, luego cada 15 min.")
    log("💡 Deteccion de internet: Activa.")
    log("💡 Reporte de rutina: Cada 3 horas (con temperatura, tiempo encendida y ONUs).")
    log(f"💡 Deteccion de reinicio: SOLO si la OLT NUNCA cayo (online->online con uptime bajo).")

    internet_estaba_caido = False
    tiempo_internet_caido = 0

    while True:
        browser = None
        try:
            with sync_playwright() as p:
                log("🌐 Abriendo navegador Chromium (headless)...")
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = context.new_page()

                login_ok = hacer_login(page, url_admin, user_admin, pass_admin)
                if not login_ok:
                    raise Exception("Login fallo")

                while True:
                    try:
                        # LIMPIAR PANTALLA AL INICIO DE CADA CICLO
                        clear_screen()

                        if not verificar_internet():
                            if not internet_estaba_caido:
                                log("🔌 Sin conexion a internet. Enviando alerta...")
                                enviar_mensaje_sin_internet()
                                internet_estaba_caido = True
                                tiempo_internet_caido = time.time()
                            else:
                                duracion = int(time.time() - tiempo_internet_caido)
                                log(f"🔌 Sin internet desde hace {duracion}s...")
                            time.sleep(30)
                            continue
                        else:
                            if internet_estaba_caido:
                                duracion_offline = int(time.time() - tiempo_internet_caido)
                                min_off = duracion_offline // 60
                                log(f"🌐 Conexion restablecida despues de {min_off} min.")
                                enviar_mensaje_reconexion()
                                internet_estaba_caido = False
                                if not verificar_sesion_activa(page):
                                    log("🔄 Sesion expirada durante caida. Re-haciendo login...")
                                    hacer_login(page, url_admin, user_admin, pass_admin)

                        if not verificar_sesion_activa(page):
                            log("🔄 Sesion expirada. Re-haciendo login...")
                            hacer_login(page, url_admin, user_admin, pass_admin)

                        estado_anterior = cargar_estado_anterior(os.path.join(script_dir, 'estado_olts.json'))
                        tiempo_actual = time.time()
                        escanear_olts(page, estado_anterior, tiempo_actual)

                    except Exception as e:
                        error_str = str(e).lower()
                        if "closed" in error_str or "target page" in error_str:
                            log("💥 Navegador cerrado. Reiniciando...")
                            raise
                        log(f"⚠️ Error en ciclo: {e}")
                        log(traceback.format_exc())
                        enviar_mensaje("⚠️ Estemos presentando un inconveniente técnico. En breve estaremos de vuelta. 🔄")

                    time.sleep(INTERVALO_SEGUNDOS)

        except Exception as e:
            log(f"💥 Error critico. Reiniciando en 10s... {e}")
            log(traceback.format_exc())
            if browser:
                try:
                    browser.close()
                except:
                    pass
            time.sleep(10)

if __name__ == "__main__":
    main()
