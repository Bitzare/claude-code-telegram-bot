# Claude Code Telegram Bot

*[English version below](#claude-code-telegram-bot-english)*

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
   | `DEFAULT_MODEL` | Modelo por defecto para Claude Code (por defecto `sonnet`). Cada chat puede cambiarlo con `/model` |
   | `DEFAULT_EFFORT` | Effort por defecto (`low`, `medium`, `high`, `xhigh` o `max`; por defecto `medium`). Opus con effort alto consume muchisimos mas tokens que Sonnet con effort medio |

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
- `/model` muestra el modelo/effort actual de ese chat. `/model <modelo> [effort]` lo cambia (ej. `/model opus high`, `/model sonnet`). `/model reset` vuelve a los valores por defecto (`DEFAULT_MODEL`/`DEFAULT_EFFORT`). Por defecto el bot usa Sonnet con effort medio para no disparar el consumo de tokens; sube a `opus`/`high` solo cuando lo necesites.

## Notificacion de salida (Stop hook) — que Claude Code te avise a ti por Telegram

Lo de arriba es el flujo "entrante" (tu le hablas al bot desde Telegram). Tambien puedes montar el flujo contrario: que **cualquier sesion normal de Claude Code** (la del IDE, la terminal, etc. — no necesariamente lanzada por este bot) te mande un mensaje de Telegram cuando termina una tarea, usando el mismo `TELEGRAM_BOT_TOKEN` de este `.env`.

Esto se hace con un **hook `Stop`** en la configuracion de Claude Code (`~/.claude/settings.json` para que aplique a todas las sesiones, o `.claude/settings.json` de un proyecto concreto para limitarlo a ese repo):

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "set -a; . \"/ruta/absoluta/a/RushuuDevelopmentsAPI/.env\" 2>/dev/null; set +a; curl -s -X POST \"https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage\" --data-urlencode \"chat_id=TU_ID_DE_TELEGRAM\" --data-urlencode \"text=Claude Code finished a task in: $(pwd)\" >/dev/null 2>&1 || true"
          }
        ]
      }
    ]
  }
}
```

Notas:
- Cambia `/ruta/absoluta/a/RushuuDevelopmentsAPI/.env` por la ruta real donde tengas clonado este repo, y `TU_ID_DE_TELEGRAM` por tu ID (el mismo que usarias en `ALLOWED_USER_IDS`).
- El mensaje se manda en texto plano ASCII (sin emojis ni tildes) — en Windows con Git Bash, pasar caracteres UTF-8 especiales por la linea de comandos del hook puede llegar corrupto a la API de Telegram y Telegram lo rechaza (`400 Bad Request: strings must be encoded in UTF-8`).
- Tras anadir o editar el hook en un `settings.json` que ya existia al arrancar la sesion, puede hacer falta abrir `/hooks` una vez (o reiniciar Claude Code) para que se recargue.
- Este mecanismo es independiente del bot (`bot.py`) — no hace falta tenerlo corriendo para que el hook funcione, solo necesita el `TELEGRAM_BOT_TOKEN` del `.env`.

## Notas de seguridad

- El bot filtra por `user.id` de Telegram, no por username (los usernames se pueden cambiar). Verifica el ID correcto con `@userinfobot`.
- `--dangerously-skip-permissions` significa que Claude Code puede ejecutar cualquier comando y tocar cualquier archivo dentro de `PROJECT_PATH` sin pedirte confirmacion. Usalo solo con proyectos y usuarios en los que confies.
- Los ficheros `.env`, `sessions.json`, `models.json`, `bot.log` y `releases/` contienen datos propios de tu instancia (tokens, IDs de sesion, logs, APKs compilados) y estan excluidos de git a proposito. No los compartas ni los subas a ningun repositorio.

## Licencia

MIT, ver [LICENSE](LICENSE).

---

<a id="claude-code-telegram-bot-english"></a>
# Claude Code Telegram Bot (English)

*[Versión en español arriba](#claude-code-telegram-bot)*

A Telegram bot that lets you talk to [Claude Code](https://docs.claude.com/en/docs/claude-code) from your phone: you send the bot a message and Claude Code works on a project on your own PC (reads/edits files, runs commands, etc.). It also includes an optional `/build` command to compile a Flutter APK and download it from your phone.

## How it works (read this before using it)

This bot **does not use an Anthropic API key**. What it does is invoke the `claude` CLI you have installed and logged in on your own PC (`claude -p --dangerously-skip-permissions ...`). In other words:

- Anyone who wants to use this tool must **clone this repo and run their own instance** on their own machine, with their own Telegram bot and their own Claude Code session.
- There is no "centralized" version where several people share one bot with different keys: whoever runs the bot is the one paying for/using their own Claude Code account, and decides which `PROJECT_PATH` and which `ALLOWED_USER_IDS` get access.
- `--dangerously-skip-permissions` gives Claude Code full permission (Bash, editing files, etc.) over `PROJECT_PATH`. **Do not expose your bot to people you don't trust**, and do not add `ALLOWED_USER_IDS` you don't control yourself.

## Requirements

- Python 3.11+
- [Claude Code](https://docs.claude.com/en/docs/claude-code) installed and logged in (`claude` available on PATH)
- A Telegram bot (token from [@BotFather](https://t.me/BotFather))
- (Optional, only for `/build`) Flutter installed, if the project you're working on is a Flutter app

## Installation

```bash
git clone https://github.com/madalolito22/<repo-name>.git
cd <repo-name>
pip install -r requirements.txt
```

## Configuration

1. Copy `.env.example` to `.env`:

   ```bash
   copy .env.example .env      # Windows
   cp .env.example .env        # Linux/Mac
   ```

2. Fill in the variables in `.env`:

   | Variable | Description |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | Your bot's token, given by `@BotFather` via `/newbot` |
   | `ALLOWED_USER_IDS` | Telegram IDs (not `@username`) allowed to use the bot, comma-separated. Find yours by talking to `@userinfobot` |
   | `PROJECT_PATH` | Absolute path to the project Claude Code will work on |
   | `CLAUDE_TIMEOUT_SECONDS` | Timeout in seconds for each Claude Code response (default 900) |
   | `BUILD_TIMEOUT_SECONDS` | Timeout in seconds for `/build` (default 900) |
   | `DOWNLOAD_HOST` / `DOWNLOAD_PORT` | IP/hostname and port your phone uses to reach this PC to download the APK generated by `/build` (Tailscale, Radmin VPN, LAN IP...) |
   | `DEFAULT_MODEL` | Default model for Claude Code (default `sonnet`). Each chat can override it with `/model` |
   | `DEFAULT_EFFORT` | Default effort (`low`, `medium`, `high`, `xhigh` or `max`; default `medium`). Opus at high effort burns far more tokens than Sonnet at medium effort |

   None of these values live in the code: `.env` is in `.gitignore` and never gets committed.

3. Make sure `claude` works from a regular terminal on that same PC (`claude --version`) before starting the bot.

## Usage

```bash
python bot.py
```

On Windows you can also use `run_bot.bat`, which launches the bot in the background with `pythonw` (no console window).

Once running, from Telegram (as a user in `ALLOWED_USER_IDS`):

- Any text message is sent to Claude Code as a prompt, run inside `PROJECT_PATH`. Conversations keep a per-chat session (using `--resume`), so you can keep talking continuously.
- `/build` compiles a Flutter release APK from `PROJECT_PATH` and gives you a download link (only useful if your project is Flutter; otherwise ignore this command).
- `/cancel` aborts whatever is currently running (Claude Code or the build).
- `/model` shows the current model/effort for that chat. `/model <model> [effort]` changes it (e.g. `/model opus high`, `/model sonnet`). `/model reset` restores the defaults (`DEFAULT_MODEL`/`DEFAULT_EFFORT`). The bot defaults to Sonnet at medium effort to keep token usage down — bump to `opus`/`high` only when you actually need it.

## Outbound notification (Stop hook) — have Claude Code message you on Telegram

Everything above is the "inbound" flow (you talk to the bot from Telegram). You can also set up the reverse flow: have **any regular Claude Code session** (IDE, terminal, etc. — not necessarily launched by this bot) send you a Telegram message when it finishes a task, reusing the same `TELEGRAM_BOT_TOKEN` from this `.env`.

This is done with a **`Stop` hook** in Claude Code's config (`~/.claude/settings.json` to apply to every session, or a project's `.claude/settings.json` to scope it to just that repo):

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "set -a; . \"/absolute/path/to/RushuuDevelopmentsAPI/.env\" 2>/dev/null; set +a; curl -s -X POST \"https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage\" --data-urlencode \"chat_id=YOUR_TELEGRAM_ID\" --data-urlencode \"text=Claude Code finished a task in: $(pwd)\" >/dev/null 2>&1 || true"
          }
        ]
      }
    ]
  }
}
```

Notes:
- Replace `/absolute/path/to/RushuuDevelopmentsAPI/.env` with wherever you actually cloned this repo, and `YOUR_TELEGRAM_ID` with your ID (same one you'd use in `ALLOWED_USER_IDS`).
- The message is sent as plain ASCII (no emoji/accents) — on Windows with Git Bash, passing special UTF-8 characters through the hook's command line can arrive corrupted at the Telegram API, which then rejects it (`400 Bad Request: strings must be encoded in UTF-8`).
- After adding/editing the hook in a `settings.json` that already existed when the session started, you may need to open `/hooks` once (or restart Claude Code) for it to reload.
- This mechanism is independent of the bot (`bot.py`) — it doesn't need to be running for the hook to work, it only needs the `TELEGRAM_BOT_TOKEN` from `.env`.

## Security notes

- The bot filters by Telegram `user.id`, not by username (usernames can change). Verify the correct ID with `@userinfobot`.
- `--dangerously-skip-permissions` means Claude Code can run any command and touch any file inside `PROJECT_PATH` without asking for confirmation. Only use this with projects and users you trust.
- The files `.env`, `sessions.json`, `models.json`, `bot.log` and `releases/` hold data specific to your instance (tokens, session IDs, logs, compiled APKs) and are intentionally excluded from git. Do not share them or upload them to any repository.

## License

MIT, see [LICENSE](LICENSE).
