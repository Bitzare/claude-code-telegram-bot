# Claude Code Telegram Bot

Bot de Telegram que te deja hablar con [Claude Code](https://docs.claude.com/en/docs/claude-code) desde el movil: le mandas un mensaje al bot y Claude Code trabaja sobre un proyecto en tu propio PC (lee/edita archivos, ejecuta comandos, etc.). Incluye tambien un comando opcional `/build` para compilar un APK de Flutter y descargarlo desde el movil.

## Como funciona (importante antes de usarlo)

Este bot **no usa una API key de Anthropic**. Lo que hace es invocar el CLI `claude` que tengas instalado y logueado en tu propio PC (`claude -p --dangerously-skip-permissions ...`). Es decir:

- Cada persona que quiera usar esta herramienta debe **clonar este repo y correr su propia instancia** en su propia maquina, con su propio bot de Telegram y su propia sesion de Claude Code.
- No hay una version "centralizada" en la que varias personas compartan un mismo bot con claves distintas: quien corre el bot es quien paga/usa su propia cuenta de Claude Code, y decide a que `PROJECT_PATH` y que `ALLOWED_USER_IDS` da acceso.
- `--dangerously-skip-permissions` le da a Claude Code permiso total (Bash, editar archivos, etc.) sobre `PROJECT_PATH`. **No expongas tu bot a gente en la que no confies** ni amplies `ALLOWED_USER_IDS` a IDs que no controles tu mismo.

## Requisitos

- Python 3.11+
- [Claude Code](https://docs.claude.com/en/docs/claude-code) instalado y logueado (`claude` disponible en el PATH)
- Un bot de Telegram (token de [@BotFather](https://t.me/BotFather))
- (Opcional, solo para `/build`) Flutter instalado, si el proyecto sobre el que trabajas es una app Flutter

## Instalacion

```bash
git clone https://github.com/madalolito22/<nombre-del-repo>.git
cd <nombre-del-repo>
pip install -r requirements.txt
```

## Configuracion

1. Copia `.env.example` a `.env`:

   ```bash
   copy .env.example .env      # Windows
   cp .env.example .env        # Linux/Mac
   ```

2. Rellena las variables en `.env`:

   | Variable | Descripcion |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | Token de tu bot, te lo da `@BotFather` con `/newbot` |
   | `ALLOWED_USER_IDS` | IDs de Telegram (no `@username`) autorizados a usar el bot, separados por comas. Averigua el tuyo hablando con `@userinfobot` |
   | `PROJECT_PATH` | Ruta absoluta al proyecto sobre el que Claude Code va a trabajar |
   | `CLAUDE_TIMEOUT_SECONDS` | Timeout en segundos para cada respuesta de Claude Code (por defecto 900) |
   | `BUILD_TIMEOUT_SECONDS` | Timeout en segundos para `/build` (por defecto 900) |
   | `DOWNLOAD_HOST` / `DOWNLOAD_PORT` | IP/hostname y puerto por el que tu movil llega a este PC para descargar el APK generado por `/build` (Tailscale, Radmin VPN, IP de LAN...) |

   Ninguno de estos valores va en el codigo: `.env` esta en `.gitignore` y nunca se sube a git.

3. Asegurate de que `claude` funciona desde una terminal normal en ese mismo PC (`claude --version`) antes de arrancar el bot.

## Uso

```bash
python bot.py
```

En Windows tambien puedes usar `run_bot.bat`, que lanza el bot en segundo plano con `pythonw` (sin ventana de consola).

Una vez arrancado, desde Telegram (con un usuario de `ALLOWED_USER_IDS`):

- Cualquier mensaje de texto se manda a Claude Code como prompt, ejecutado dentro de `PROJECT_PATH`. Las conversaciones mantienen sesion por chat (usando `--resume`), asi que puedes seguir hablando de forma continua.
- `/build` compila un APK de Flutter release desde `PROJECT_PATH` y te da un link de descarga (solo tiene sentido si tu proyecto es Flutter; si no, ignora este comando).
- `/cancel` aborta la ejecucion en curso (de Claude Code o del build).

## Notas de seguridad

- El bot filtra por `user.id` de Telegram, no por username (los usernames se pueden cambiar). Verifica el ID correcto con `@userinfobot`.
- `--dangerously-skip-permissions` significa que Claude Code puede ejecutar cualquier comando y tocar cualquier archivo dentro de `PROJECT_PATH` sin pedirte confirmacion. Usalo solo con proyectos y usuarios en los que confies.
- Los ficheros `.env`, `sessions.json`, `bot.log` y `releases/` contienen datos propios de tu instancia (tokens, IDs de sesion, logs, APKs compilados) y estan excluidos de git a proposito. No los compartas ni los subas a ningun repositorio.

## Licencia

MIT, ver [LICENSE](LICENSE).
