import asyncio
import functools
import http.server
import json
import logging
import logging.handlers
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER_IDS = {
    int(uid.strip()) for uid in os.environ["ALLOWED_USER_IDS"].split(",") if uid.strip()
}
PROJECT_PATH = os.environ["PROJECT_PATH"]
CLAUDE_TIMEOUT_SECONDS = int(os.environ.get("CLAUDE_TIMEOUT_SECONDS", "900"))
BUILD_TIMEOUT_SECONDS = int(os.environ.get("BUILD_TIMEOUT_SECONDS", "900"))
STATUS_UPDATE_SECONDS = 4
SESSIONS_FILE = Path(__file__).parent / "sessions.json"
RELEASES_DIR = Path(__file__).parent / "releases"
RELEASES_DIR.mkdir(exist_ok=True)
RELEASES_TO_KEEP = 5

# IP/hostname por el que el movil llega al PC (Tailscale, Radmin, IP de LAN...).
# Ajusta esto en .env segun la VPN/red que uses.
DOWNLOAD_HOST = os.environ.get("DOWNLOAD_HOST", "localhost")
DOWNLOAD_PORT = int(os.environ.get("DOWNLOAD_PORT", "8765"))

LOG_FILE = Path(__file__).parent / "bot.log"

_handlers = [logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")]
if os.environ.get("PYTHONW") != "1":
    _handlers.append(logging.StreamHandler())

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
    handlers=_handlers,
)
log = logging.getLogger("bot")

lock = asyncio.Lock()

# Solo hay una ejecucion de Claude a la vez (protegida por `lock`), asi que
# guardar el proceso activo en una variable global es seguro.
current_proc: asyncio.subprocess.Process | None = None


def load_sessions() -> dict[str, str]:
    if SESSIONS_FILE.exists():
        return json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
    return {}


def save_sessions(sessions: dict[str, str]) -> None:
    SESSIONS_FILE.write_text(json.dumps(sessions, indent=2), encoding="utf-8")


sessions = load_sessions()


class ActivityState:
    """Ultima actividad conocida de Claude, compartida entre run_claude (que la
    actualiza leyendo el stream de eventos) y keep_status_updated (que la
    muestra cada pocos segundos)."""

    def __init__(self, label: str) -> None:
        self.label = label


def _describe_tool_use(block: dict) -> str:
    name = block.get("name", "?")
    tool_input = block.get("input") or {}

    if name in ("Edit", "Write", "NotebookEdit"):
        path = tool_input.get("file_path", "")
        return f"Editando {Path(path).name}" if path else f"Editando ({name})"
    if name == "Read":
        path = tool_input.get("file_path", "")
        return f"Leyendo {Path(path).name}" if path else "Leyendo archivo"
    if name == "Bash":
        command = (tool_input.get("command") or "").strip().replace("\n", " ")
        return f"Ejecutando: {command[:50]}"
    if name in ("Grep", "Glob"):
        pattern = tool_input.get("pattern", "")
        return f"Buscando: {pattern[:50]}"
    if name == "TodoWrite":
        return "Actualizando plan de tareas"
    return f"Usando herramienta {name}"


_CODE_BLOCK_RE = re.compile(r"```(?:\w*\n)?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+?)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _convert_inline(text: str) -> str:
    text = _escape_html(text)
    text = _INLINE_CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", text)
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_RE.sub(r"<i>\1</i>", text)
    return text


def markdown_to_telegram_html(text: str) -> str:
    """Convierte un subconjunto de markdown (el que suele devolver Claude) a
    HTML soportado por Telegram, para que negritas, listas y bloques de
    codigo se vean formateados en vez de con asteriscos/backticks literales."""
    out = []
    last_end = 0
    for match in _CODE_BLOCK_RE.finditer(text):
        out.append(_convert_inline(text[last_end:match.start()]))
        out.append(f"<pre>{_escape_html(match.group(1))}</pre>")
        last_end = match.end()
    out.append(_convert_inline(text[last_end:]))
    return "".join(out)


def split_markdown_chunks(text: str, limit: int = 3500) -> list[str]:
    """Trocea texto largo en fragmentos <= limit sin cortar un bloque de
    codigo ``` a la mitad (lo cierra y lo reabre en el siguiente fragmento)."""
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    in_code = False
    fence = "```"

    for line in lines:
        if line.strip().startswith("```"):
            in_code = not in_code
            if in_code:
                fence = line.strip()

        line_len = len(line) + 1
        if current_len + line_len > limit and current:
            if in_code:
                current.append("```")
            chunks.append("\n".join(current))
            current = []
            current_len = 0
            if in_code:
                current.append(fence)
                current_len = len(fence) + 1

        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current))
    return chunks or [""]


async def send_result_message(
    context: ContextTypes.DEFAULT_TYPE,
    message,
    status_message,
    header: str,
    body: str,
) -> None:
    """Manda el resultado troceado y formateado como HTML; si el HTML
    generado no es valido para Telegram, cae a texto plano en vez de fallar."""
    chunks = split_markdown_chunks(body)

    first_text = f"{header}\n\n{markdown_to_telegram_html(chunks[0])}"
    try:
        await context.bot.edit_message_text(
            chat_id=status_message.chat_id,
            message_id=status_message.message_id,
            text=first_text,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        try:
            await context.bot.edit_message_text(
                chat_id=status_message.chat_id,
                message_id=status_message.message_id,
                text=f"{header}\n\n{chunks[0]}",
            )
        except Exception:
            await message.reply_text(f"{header}\n\n{chunks[0]}")

    for chunk in chunks[1:]:
        try:
            await message.reply_text(markdown_to_telegram_html(chunk), parse_mode=ParseMode.HTML)
        except Exception:
            await message.reply_text(chunk)


async def run_claude(chat_id: int, prompt: str, activity: ActivityState) -> str:
    global current_proc

    session_id = sessions.get(str(chat_id))
    if session_id:
        session_args = ["--resume", session_id]
    else:
        session_id = str(uuid.uuid4())
        session_args = ["--session-id", session_id]

    # En Windows "claude" es un shim .cmd de npm: CreateProcess no puede
    # ejecutarlo directamente, hay que pasar por cmd.exe. El prompt se
    # manda por stdin (no como argumento) para que el texto del usuario
    # nunca forme parte de la linea de comandos que cmd.exe interpreta.
    # stream-json permite ir leyendo que herramienta esta usando Claude
    # mientras trabaja, en vez de esperar a ciegas hasta que termine.
    proc = await asyncio.create_subprocess_exec(
        "cmd", "/c", "claude", "-p", "--dangerously-skip-permissions",
        "--output-format", "stream-json", "--verbose", *session_args,
        cwd=PROJECT_PATH,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        limit=1024 * 1024,  # 1 MB; default 64 KB overflows on long stream-json lines
    )
    current_proc = proc

    async def _consume() -> tuple[str, str]:
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()

        result_text = ""
        async for raw_line in proc.stdout:
            line = raw_line.decode(errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")
            if event_type == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        activity.label = _describe_tool_use(block)
            elif event_type == "result":
                result_text = event.get("result") or ""

        stderr_bytes = await proc.stderr.read()
        await proc.wait()
        return result_text, stderr_bytes.decode(errors="replace").strip()

    try:
        output, error = await asyncio.wait_for(_consume(), timeout=CLAUDE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        return f"Se agoto el tiempo esperando a Claude Code (>{CLAUDE_TIMEOUT_SECONDS // 60} min)."
    finally:
        current_proc = None

    if proc.returncode == -9 or proc.returncode == 1 and "cancel" in error.lower():
        return "Cancelado por el usuario."

    if proc.returncode != 0:
        # Si la sesion guardada ya no existe (proyecto reiniciado, cache
        # borrada, etc.) empezamos una nueva en el siguiente mensaje en vez
        # de quedarnos atascados repitiendo el mismo error.
        if "session" in error.lower() and str(chat_id) in sessions:
            del sessions[str(chat_id)]
            save_sessions(sessions)
        return f"Claude Code fallo (codigo {proc.returncode}):\n{error or output}"

    sessions[str(chat_id)] = session_id
    save_sessions(sessions)

    return output or "(Claude Code no devolvio salida)"


async def keep_status_updated(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, start: float, activity: ActivityState
) -> None:
    try:
        while True:
            await asyncio.sleep(STATUS_UPDATE_SECONDS)
            elapsed = int(time.monotonic() - start)
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"{activity.label}... ({elapsed}s). Manda /cancel para abortar.",
                )
            except Exception:
                pass  # el mensaje puede no haber cambiado, Telegram lo rechaza sin importancia
    except asyncio.CancelledError:
        pass


def _prune_old_releases() -> None:
    apks = sorted(RELEASES_DIR.glob("*.apk"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in apks[RELEASES_TO_KEEP:]:
        stale.unlink(missing_ok=True)


async def run_flutter_build() -> tuple[bool, str, str | None]:
    global current_proc

    proc = await asyncio.create_subprocess_exec(
        "cmd", "/c", "flutter", "build", "apk", "--release",
        cwd=PROJECT_PATH,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    current_proc = proc
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=BUILD_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        return False, f"Se agoto el tiempo compilando (>{BUILD_TIMEOUT_SECONDS // 60} min).", None
    finally:
        current_proc = None

    output = stdout.decode(errors="replace").strip()
    error = stderr.decode(errors="replace").strip()

    if proc.returncode == -9:
        return False, "Build cancelado por el usuario.", None

    if proc.returncode != 0:
        tail = (error or output)[-3500:]
        return False, f"El build fallo (codigo {proc.returncode}):\n{tail}", None

    apk_path = Path(PROJECT_PATH) / "build" / "app" / "outputs" / "flutter-apk" / "app-release.apk"
    if not apk_path.exists():
        return False, "El build termino bien pero no encuentro el APK generado en la ruta esperada.", None

    token = uuid.uuid4().hex[:12]
    dest = RELEASES_DIR / f"{token}.apk"
    shutil.copy2(apk_path, dest)
    _prune_old_releases()

    url = f"http://{DOWNLOAD_HOST}:{DOWNLOAD_PORT}/{token}.apk"
    return True, "Build completado.", url


class _NoListingHandler(http.server.SimpleHTTPRequestHandler):
    def list_directory(self, path):
        self.send_error(403, "Directory listing disabled")
        return None

    def log_message(self, fmt, *args):
        log.info("download-server: " + fmt, *args)


def start_download_server() -> None:
    handler = functools.partial(_NoListingHandler, directory=str(RELEASES_DIR))
    server = http.server.ThreadingHTTPServer(("0.0.0.0", DOWNLOAD_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("Servidor de descargas escuchando en 0.0.0.0:%s (%s)", DOWNLOAD_PORT, RELEASES_DIR)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message

    if user is None or user.id not in ALLOWED_USER_IDS:
        log.warning("Mensaje ignorado de user_id no autorizado: %s", user.id if user else None)
        return

    prompt = message.text
    if not prompt:
        return

    if lock.locked():
        await message.reply_text("Ya estoy procesando otro mensaje, espera a que termine.")
        return

    async with lock:
        start = time.monotonic()
        activity = ActivityState("Procesando")
        status_message = await message.reply_text(f"{activity.label}... (0s). Manda /cancel para abortar.")
        updater_task = asyncio.create_task(
            keep_status_updated(context, status_message.chat_id, status_message.message_id, start, activity)
        )
        try:
            result = await run_claude(update.effective_chat.id, prompt, activity)
        except Exception as exc:
            log.exception("Error ejecutando Claude Code")
            result = f"Error inesperado: {exc}"
        finally:
            updater_task.cancel()

        elapsed = int(time.monotonic() - start)
        await send_result_message(context, message, status_message, f"Listo ({elapsed}s)", result)


async def handle_build(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message

    if user is None or user.id not in ALLOWED_USER_IDS:
        return

    if lock.locked():
        await message.reply_text("Ya estoy procesando otro mensaje, espera a que termine.")
        return

    async with lock:
        start = time.monotonic()
        activity = ActivityState("Compilando")
        status_message = await message.reply_text(f"{activity.label}... (0s). Manda /cancel para abortar.")
        updater_task = asyncio.create_task(
            keep_status_updated(context, status_message.chat_id, status_message.message_id, start, activity)
        )
        try:
            success, text, url = await run_flutter_build()
        except Exception as exc:
            log.exception("Error compilando el APK")
            success, text, url = False, f"Error inesperado: {exc}", None
        finally:
            updater_task.cancel()

        elapsed = int(time.monotonic() - start)
        if success:
            final_text = f"Listo ({elapsed}s)\n\n{text}\n\nDescarga e instala desde el movil:\n{url}"
        else:
            final_text = f"Fallo ({elapsed}s)\n\n{text}"

        first_chunk = final_text[:4000]
        try:
            await context.bot.edit_message_text(
                chat_id=status_message.chat_id,
                message_id=status_message.message_id,
                text=first_chunk,
            )
        except Exception:
            await message.reply_text(first_chunk)

        for chunk_start in range(4000, len(final_text), 4000):
            await message.reply_text(final_text[chunk_start:chunk_start + 4000])


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or user.id not in ALLOWED_USER_IDS:
        return

    if current_proc is None or current_proc.returncode is not None:
        await update.effective_message.reply_text("No hay nada en ejecucion ahora mismo.")
        return

    current_proc.kill()
    await update.effective_message.reply_text("Cancelando...")


def main() -> None:
    start_download_server()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("cancel", handle_cancel))
    app.add_handler(CommandHandler("build", handle_build))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    log.info("Bot arrancado, escuchando mensajes de user_ids=%s sobre %s", ALLOWED_USER_IDS, PROJECT_PATH)
    app.run_polling()


if __name__ == "__main__":
    main()
