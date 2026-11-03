# Poner el bot de OLTs en un servidor (Oracle Cloud Always Free + GitHub)

## La idea, en una frase

GitHub guarda el código y lo despliega; **el que corre 24/7 es el servidor**. Un script con
`while True` y un navegador no puede vivir dentro de GitHub Actions: Actions es un sistema de
CI, no un equipo siempre encendido, y usarlo como tal viola los términos de servicio de GitHub.

```
tu PC (apagada)  ->  git push  ->  GitHub  ->  SSH  ->  servidor Oracle (corre el bot)  ->  Telegram
```

---

## 1. Crear la máquina gratis en Oracle

1. Registro en `oracle.com/cloud/free` — pide tarjeta para verificar identidad.
   Ten en cuenta que muchas tarjetas venezolanas son rechazadas. Si te falla, las salidas son:
   usar la tarjeta de un familiar, o saltar a un VPS pago de ~12 USD al año (RackNerd, Contabo)
   y aplicar exactamente los mismos pasos de este documento a partir de la sección 2.
2. Elige región cercana a tus usuarios. Para este bot da igual la latencia; escoge una que
   tenga capacidad ARM disponible (São Paulo `gru1` o Santiago `scl1` suelen ser las opciones
   sudamericanas).
3. **Compute → Instances → Create instance**:
   - Image: **Ubuntu 24.04** (aarch64)
   - Shape: **A1.Flex** (Always Free). Después de crearla puedes subirla a 4 OCPU / 24 GB sin costo.
   - Boot volume: hasta 200 GB gratis; con 50 GB vas sobrado.
   - Network: deja marcado **SSH (22)**. No necesitas abrir ningún puerto más: el bot solo hace
     conexiones salientes (panel AdminOLT y API de Telegram).
   - Clave: genera una **API key pair** y descarga la privada, o sube la pública.
4. Si al crearla dice `Out of capacity`, es el agotamiento típico de ARM gratis: espera unos
   minutos y reintenta, o prueba otra disponibilidad de la misma región.

Conectarte:

```bash
ssh -i ~/Descargas/claude_oracle_key.pem ubuntu@IP_DE_TU_INSTANCIA
```

> **Advertencia real sobre el nivel gratis:** Oracle recupera instancias Always Free ARM que
> considera subutilizadas. Un bot de monitoreo usa casi nada de CPU, así que puede entrar en ese
> perfil. La mitigación no es meterle carga falsa, sino que **la recuperación se resuelve en dos
> minutos** porque todo vive en GitHub: creas una instancia nueva, corres `setup_server.sh`,
> editas el `.env` y listo. Nunca guardes nada importante en el disco de la máquina.

---

## 2. Subir el proyecto a GitHub

Desde esta PC, en la carpeta del proyecto:

```bash
git init
git add .
git commit -m "Monitor OLT: version para servidor"
git remote add origin https://github.com/TU_USUARIO/monitor-olt.git
git push -u origin main
```

El `.gitignore` que viene en el proyecto deja fuera lo que no debe ser público:
`.env` (credenciales), `estado_olts.json` (estado vivo), `error_servicio.log` (90 MB),
`nssm.exe` y `ejecutar_bot.bat`. El `.gitattributes` fuerza LF en los scripts, para que
un Git de Windows con `core.autocrlf=true` no los deje inservibles en Linux.

Si al final usas un repo **privado** (recomendado), el `git clone` del servidor necesita
autenticación: crea un *fine-grained personal access token* con permiso `Contents: Read`
sobre ese repo y pasa la URL con él, o configura una deploy key:

```bash
sudo bash setup_server.sh "https://x-access-token:ghp_TU_TOKEN@github.com/TU_USUARIO/monitor-olt.git"
```

Verifica antes de empujar que no se coló ninguna clave:

```bash
git status --short
git show --stat HEAD | grep -E "\.env|log"
```

---

## 3. Instalar en el servidor

Una sola línea, dentro de la sesión SSH:

```bash
sudo bash setup_server.sh https://github.com/TU_USUARIO/monitor-olt.git
```

Qué hace: instala Python y Git, clona el repo en `/opt/monitorolt`, crea un entorno virtual,
instala Chromium para Playwright, crea el usuario de servicio `monitor`, genera un `.env` de
ejemplo y deja el servicio systemd `monitorolt` corriendo y habilitado para arrancar tras
cada reinicio de la máquina.

Después mete tus credenciales reales y reinicia:

```bash
sudo nano /opt/monitorolt/.env     # URL_ADMIN, USER_ADMIN, PASS_ADMIN, TG_TOKEN, TG_CHAT_ID
sudo chmod 600 /opt/monitorolt/.env
sudo systemctl restart monitorolt
```

Prueba de que funciona:

```bash
journalctl -u monitorolt -f
```

Debes ver los ciclos cada 30 s y, en el canal de Telegram, el mensaje
`✅ AVISO: Bot monitoreando OLTs correctamente.`

---

## 4. Apagar el bot de tu PC (importante)

Verificado en esta máquina: el servicio que **realmente** corre este bot es
**`BotMonitorOLTsmart`** (estado: Running, y su comando es `ejecutar_bot.bat` → `monitorolt.py`).
El servicio llamado `MonitorOLT` está **Stopped** y apunta a un `monitor.py` que ya no existe;
`MonitorSmartOLT` (Stopped) corre otro script y `MonitorHubs` (Running) es el bot de HUBs,
que no debes tocar.

Si dejan de correr los dos a la vez, el canal se llena de alertas duplicadas y las dos
instancias se pispan el estado. Para apagar solo este bot:

```powershell
# PowerShell como Administrador
Stop-Service BotMonitorOLTsmart
Set-Service BotMonitorOLTsmart -StartupType Manual
```

O desde `services.msc`: detén **BotMonitorOLTsmart** y pon su tipo de inicio en "Manual".

Comprobación de que efectivamente se apagó (el archivo deja de actualizarse):

```powershell
Get-Item .\estado_olts.json | Select LastWriteTime   # vuelve a consultarlo 1 minuto despues
```

Aprovecha y libera los 90 MB de `error_servicio.log` una vez que el servidor ya esté tomando
el relevo; en Linux el log pasa a `journalctl` y se rota solo.


---

## 5. Despliegue automático al hacer push

El proyecto trae `.github/workflows/deploy.yml`. Para activarlo, crea en tu repo
(Settings → Secrets and variables → Actions) estos tres secrets:

| Secret | Valor |
|---|---|
| `DEPLOY_HOST` | IP pública de la instancia Oracle |
| `DEPLOY_USER` | `ubuntu` |
| `DEPLOY_SSH_KEY` | contenido completo de la clave privada `.pem` |

De ahí en adelante: editas `monitorolt.py`, `git push`, y el workflow corre
`update.sh` en el servidor (trae el código y reinicia el servicio). El reinicio es
**planificado**, así que no lanza el aviso de "inconveniente" al canal.

Si prefieres actualizar a mano, sin Actions: `sudo bash /opt/monitorolt/update.sh`.

---

## 6. Operación diaria

```bash
systemctl status monitorolt              # vivo o muerto
journalctl -u monitorolt --since -2h     # log de las ultimas 2 horas
sudo systemctl stop monitorolt           # mantenimiento
sudo nano /opt/monitorolt/.env           # cambiar credenciales
```

El bot se reanuda solo si crashea (`Restart=always`, cada 15 s). Si el panel te cambia la
estructura de la tabla o la sesión se rompe, manda el aviso de inconveniente y sigue
intentando; no deja de correr.

`estado_olts.json` guarda el estado (temporizador del reporte de rutina de 3 horas, alertas ya
enviadas, reinicios ya avisados). Si quieres conservar el ritmo que llevaba tu PC, cópialo al
servidor antes del primer arranque:

```bash
scp -i TU_CLAVE.pem estado_olts.json ubuntu@IP:/tmp/
sudo cp /tmp/estado_olts.json /opt/monitorolt/ && sudo chown monitor:monitor /opt/monitorolt/estado_olts.json
```

Si no lo copias, simplemente arranca limpio: vuelve a mandar el aviso de inicio y los reportes
de rutina se reinician en su ciclo de 3 horas.

---

## 7. Qué cambié en `monitorolt.py` y por qué

Tres ajustes necesarios para correr como servicio en Linux, sin tocar la lógica de alertas:

1. **El aviso de cierre ya no sale en paros planificados.** Antes, cada `systemctl stop`,
   cada despliegue y cada reinicio del servidor mandaba "⚠️ Estamos presentando un
   inconveniente" al canal, **dos veces** (lo enviaban el manejador de señal y el `atexit`).
   Ahora un paro planificado sale en silencio, y el aviso queda solo para caídas reales.
   Controlable con `AVISO_CIERRE_INESPERADO=1|0` en el `.env`.
2. **La URL del panel ya no está hardcodeada en el código.** Se deriva de `URL_ADMIN`,
   que vive en el `.env`. Necesario porque elegiste un repositorio público.
3. **Limpieza de pantalla solo si hay terminal.** `os.system('cls')` en Linux imprimía un
   error en el log cada 30 segundos; ahora no ensucia `journalctl`.

## 8. Pendiente de tu lado por haber elegido repo público

Con el repo público quedan visibles en Internet los nombres de tus OLTs (`OLT3-N4BDR-ZONA3`, …),
el agrupamiento por zonas y los nombres del equipo en `NOMBRES_EQUIPO`. No son credenciales, pero
sí son datos de tu infraestructura y de personas. Un repositorio privado no cuesta nada, permite
el mismo despliegue automático por SSH y elimina esa exposición; si te interesa, lo cambias con
Settings → Danger Zone → Change visibility, o me dices y muevo esas listas al `.env`.
