import os
import json
import requests
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURACIÓN (Variables de Entorno / Secrets)
# ==========================================
ADMINOLT_URL = os.environ.get("ADMINOLT_URL", "https://adminolt.com").rstrip('/')
USERNAME = os.environ.get("ADMINOLT_USER")
PASSWORD = os.environ.get("ADMINOLT_PASS")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

ARCHIVO_ESTADO = "estado_olts.json"


def enviar_telegram(mensaje):
    """Envía un mensaje de notificación a Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Advertencia: TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        print("✉️ Notificación enviada a Telegram exitosamente.")
    except Exception as e:
        print(f"❌ Error al enviar mensaje a Telegram: {e}")


def cargar_estado_anterior():
    """Carga la memoria guardada protegiendo el script si el JSON está vacío o corrupto."""
    if not os.path.exists(ARCHIVO_ESTADO):
        print("ℹ️ No existe estado_olts.json. Se creará uno nuevo.")
        return {}

    try:
        with open(ARCHIVO_ESTADO, "r", encoding="utf-8") as f:
            contenido = f.read().strip()
            if not contenido:
                print("⚠️ El archivo estado_olts.json estaba vacío. Reiniciando memoria...")
                return {}
            return json.loads(contenido)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"⚠️ El archivo estado_olts.json estaba dañado ({e}). Reiniciando memoria...")
        return {}
    except Exception as e:
        print(f"❌ Error al acceder a {ARCHIVO_ESTADO}: {e}")
        return {}


def guardar_estado_actual(estado):
    """Guarda el estado actual de las OLTs en estado_olts.json."""
    try:
        with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
            json.dump(estado, f, indent=4, ensure_ascii=False)
        print("💾 Estado actual guardado correctamente en estado_olts.json.")
    except Exception as e:
        print(f"❌ Error guardando estado en JSON: {e}")


def obtener_estado_olts_adminolt():
    """Realiza el inicio de sesión en AdminOLT y escanea el estado de todas las OLTs."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    })

    login_page_url = f"{ADMINOLT_URL}/login/"
    try:
        res = session.get(login_page_url, timeout=20)
        soup = BeautifulSoup(res.text, "html.parser")
        
        # Extracción del token CSRF si la plataforma lo requiere
        csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
        csrf_token = csrf_input["value"] if csrf_input else ""

        login_data = {
            "username": USERNAME,
            "password": PASSWORD,
            "csrfmiddlewaretoken": csrf_token
        }
        
        headers_login = {"Referer": login_page_url}
        resp_post = session.post(login_page_url, data=login_data, headers=headers_login, timeout=20)

        if "login" in resp_post.url.lower() and resp_post.status_code == 200:
            print("❌ Error de inicio de sesión: Revisa tus credenciales (ADMINOLT_USER / ADMINOLT_PASS).")
            return None

    except Exception as e:
        print(f"❌ Error conectando a AdminOLT durante el login: {e}")
        return None

    # Escaneo de la página del dashboard / lista de OLTs
    olts_url = f"{ADMINOLT_URL}/olt/"
    try:
        r = session.get(olts_url, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        
        estado_actual = {}
        
        # Búsqueda de filas/tarjetas de OLTs
        # (Ajusta los selectores según el HTML exacto si AdminOLT actualiza la estructura)
        filas = soup.find_all(["tr", "div"], class_=lambda c: c and ("olt" in c.lower() or "item" in c.lower()))
        
        if not filas:
            # Búsqueda alternativa general si no coinciden las clases específicas
            filas = soup.find_all("tr")

        for fila in filas:
            texto_fila = fila.get_text()
            if "OLT" in texto_fila:
                # Detección de nombre y estado (Online / Offline)
                columnas = fila.find_all(["td", "div"])
                if len(columnas) >= 2:
                    nombre = columnas[0].get_text(strip=True)
                    
                    # Detección mediante clases CSS de badges o texto explicativo
                    badge_rojo = fila.find(class_=lambda c: c and ("danger" in c or "red" in c or "offline" in c))
                    badge_verde = fila.find(class_=lambda c: c and ("success" in c or "green" in c or "online" in c))

                    if badge_rojo or "offline" in texto_fila.lower() or "caida" in texto_fila.lower():
                        estado_actual[nombre] = "Offline"
                    elif badge_verde or "online" in texto_fila.lower():
                        estado_actual[nombre] = "Online"

        print(f"🔍 Escaneo completado. OLTs encontradas: {len(estado_actual)}")
        return estado_actual

    except Exception as e:
        print(f"❌ Error extrayendo información de AdminOLT: {e}")
        return None


def main():
    print("🚀 Iniciando monitor de OLTs...")
    
    estado_anterior = cargar_estado_anterior()
    estado_actual = obtener_estado_olts_adminolt()

    if estado_actual is None:
        print("⚠️ No se pudo obtener el estado actual. Cancelando proceso para no sobreescribir memoria.")
        return

    # Si es la primera vez que corre y no había memoria anterior
    if not estado_anterior:
        print("📝 Primera ejecución exitosa. Registrando estado base...")
        guardar_estado_actual(estado_actual)
        
        # Reportar si hay OLTs caídas desde el primer inicio
        caidas_iniciales = [olt for olt, est in estado_actual.items() if est == "Offline"]
        if caidas_iniciales:
            msg = "🚨 <b>ALERTA DE INICIO - OLTs CAÍDAS DETECTADAS:</b>\n\n"
            for olt in caidas_iniciales:
                msg += f"• 🔴 <b>{olt}</b> está Offline\n"
            enviar_telegram(msg)
        return

    # Comparar cambios entre el escaneo anterior y el actual
    cambios_detectados = False
    
    for olt, estado_nuevo in estado_actual.items():
        estado_viejo = estado_anterior.get(olt)

        # 1. Detectar CAÍDA (Online -> Offline)
        if estado_viejo == "Online" and estado_nuevo == "Offline":
            msg = f"🚨 <b>ALERTA OLT CAÍDA</b> 🚨\n\n🔴 La OLT <b>{olt}</b> ha perdido conexión."
            enviar_telegram(msg)
            cambios_detectados = True

        # 2. Detectar RECUPERACIÓN (Offline -> Online)
        elif estado_viejo == "Offline" and estado_nuevo == "Online":
            msg = f"✅ <b>RESTAURACIÓN OLT</b> ✅\n\n🟢 La OLT <b>{olt}</b> vuelve a estar Online."
            enviar_telegram(msg)
            cambios_detectados = True

        # 3. Nueva OLT añadida que entra en estado caida
        elif estado_viejo is None and estado_nuevo == "Offline":
            msg = f"⚠️ <b>NUEVA OLT DETECTADA (OFFLINE)</b>\n\n🔴 La OLT <b>{olt}</b> se registró en estado Offline."
            enviar_telegram(msg)
            cambios_detectados = True

    # Guardar siempre el estado más reciente
    guardar_estado_actual(estado_actual)
    
    if not cambios_detectados:
        print("✅ Sin novedades: El estado de las OLTs no ha cambiado respecto al escaneo anterior.")


if __name__ == "__main__":
    main()
