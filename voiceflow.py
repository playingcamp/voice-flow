#!/usr/bin/env python3
"""
voiceflow.py — Push-to-talk dictation con Whisper local + Gemini function calling.

Uso: mantén pulsada Right Option (⌥ derecha) mientras hablas.
- Si dictas prosa o lista → se pega donde está el cursor (con formato corregido).
- Si dictas un comando → Gemini elige la tool adecuada (open app, búsqueda,
  email, WhatsApp, evento de calendario, recordatorio).
- Las tools que envían algo (email, WhatsApp, evento) abren un diálogo de
  confirmación antes de actuar.
"""

import os
import sys
import time
import json
import queue
import threading
import subprocess
import unicodedata
import urllib.parse
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import whisper
from pynput import keyboard
import pyperclip

# ─── Config ──────────────────────────────────────────────────────────────────
MODEL_NAME = "base"           # tiny | base | small | medium
SAMPLE_RATE = 16000
CHANNELS = 1
LANGUAGE = None               # None = auto-detect
MIN_DURATION_SEC = 0.3
HOTKEY = keyboard.Key.alt_r   # Right Option (⌥ derecha)

GEMINI_ENABLED = os.environ.get("VOICEFLOW_ENHANCE", "1") != "0"
GEMINI_MODEL = "gemini-2.5-flash"

SCRIPT_DIR = Path(__file__).resolve().parent
DICTIONARY_PATH = SCRIPT_DIR / "dictionary.json"
SNIPPETS_PATH = SCRIPT_DIR / "snippets.json"

# ─── Estado global ───────────────────────────────────────────────────────────
recording = False
audio_queue: "queue.Queue[np.ndarray]" = queue.Queue()
recording_start_time = 0.0
model = None
gemini_client = None
dictionary_data = {"vocabulary": [], "context": ""}
snippets_data: dict = {}

# Modo replace: se activa si pulsas ⌘ mientras mantienes ⌥
replace_mode_requested = False
replace_mode_announced = False  # para anunciar solo 1 vez por grabación

CLIPBOARD_MARKER = "___VOICEFLOW_NO_SELECTION___"


# ─── Dictionary + Snippets ───────────────────────────────────────────────────
def load_dictionary() -> None:
    """Carga dictionary.json con vocabulario y contexto del usuario."""
    global dictionary_data
    try:
        with open(DICTIONARY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        dictionary_data = {
            "vocabulary": data.get("vocabulary", []),
            "context": data.get("context", ""),
        }
        n = len(dictionary_data["vocabulary"])
        print(f"📖 Dictionary: {n} términos cargados.", flush=True)
    except FileNotFoundError:
        print("ℹ️  Sin dictionary.json (opcional).", flush=True)
    except Exception as e:
        print(f"⚠️  Error leyendo dictionary.json: {e}", flush=True)


def load_snippets() -> None:
    """Carga snippets.json. Las keys se normalizan para matching insensible."""
    global snippets_data
    try:
        with open(SNIPPETS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("snippets", {})
        # Normalizar las claves para matching robusto
        snippets_data = {_normalize_text(k): v for k, v in raw.items()}
        print(f"📋 Snippets: {len(snippets_data)} atajos cargados.", flush=True)
    except FileNotFoundError:
        print("ℹ️  Sin snippets.json (opcional).", flush=True)
    except Exception as e:
        print(f"⚠️  Error leyendo snippets.json: {e}", flush=True)


def _normalize_text(s: str) -> str:
    """Lowercase + sin acentos + sin puntuación final, para matching tolerante."""
    s = s.strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    # quitar puntuación al final
    while s and s[-1] in ".,!?¡¿;:":
        s = s[:-1]
    return s.strip()


def match_snippet(text: str) -> str | None:
    """Si el texto matchea exactamente un snippet, devuelve el valor. None si no."""
    if not snippets_data:
        return None
    key = _normalize_text(text)
    return snippets_data.get(key)


def whisper_initial_prompt() -> str | None:
    """Construye un initial_prompt corto para Whisper con vocabulario clave.

    Whisper usa este prompt como contexto, mejorando la transcripción de
    nombres propios poco comunes. Lo mantenemos breve (~200 chars) para
    no introducir sesgos.
    """
    vocab = dictionary_data.get("vocabulary", [])
    if not vocab:
        return None
    # Limita a primeros 15 términos para que el prompt no domine el contexto
    sample = ", ".join(vocab[:15])
    return f"Vocabulario: {sample}."


# ─── Permisos macOS ──────────────────────────────────────────────────────────
def request_accessibility_permission():
    """Fuerza el diálogo de TCC para Accesibilidad la primera vez."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        options = {"AXTrustedCheckOptionPrompt": True}
        trusted = AXIsProcessTrustedWithOptions(options)
        if trusted:
            print("✅ Permiso de Accesibilidad concedido.", flush=True)
        else:
            print("⚠️  Sin permiso de Accesibilidad — concédelo en el diálogo de macOS y reinicia la app.", flush=True)
        return trusted
    except Exception as e:
        print(f"⚠️  No se pudo solicitar permiso AX: {e}", flush=True)
        return None


# ─── Helpers de sistema ──────────────────────────────────────────────────────
def play_sound(name: str) -> None:
    sounds = {
        "start": "/System/Library/Sounds/Tink.aiff",
        "stop": "/System/Library/Sounds/Pop.aiff",
        "cmd": "/System/Library/Sounds/Glass.aiff",
        "ok": "/System/Library/Sounds/Hero.aiff",
        "error": "/System/Library/Sounds/Basso.aiff",
    }
    path = sounds.get(name)
    if path and Path(path).exists():
        subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def paste_text_at_cursor(text: str) -> None:
    """Copia al portapapeles y simula Cmd+V para pegar donde está el cursor."""
    try:
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = None
        pyperclip.copy(text)
        time.sleep(0.05)
        ctrl = keyboard.Controller()
        with ctrl.pressed(keyboard.Key.cmd):
            ctrl.press('v')
            ctrl.release('v')
        if previous is not None:
            def restore():
                time.sleep(0.5)
                try:
                    pyperclip.copy(previous)
                except Exception:
                    pass
            threading.Thread(target=restore, daemon=True).start()
    except Exception as e:
        print(f"❌ Error al pegar: {e}", flush=True)
        play_sound("error")


def _applescript_escape(s: str) -> str:
    """Escapa una string para que sea segura dentro de un literal AppleScript."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def confirm_dialog(title: str, message: str, ok_label: str = "Enviar", cancel_label: str = "Cancelar") -> bool:
    """Muestra un diálogo nativo de macOS con dos botones. Devuelve True si pulsa OK."""
    msg = _applescript_escape(message)
    title_safe = _applescript_escape(title)
    script = (
        f'display dialog "{msg}" with title "{title_safe}" '
        f'buttons {{"{cancel_label}", "{ok_label}"}} default button "{ok_label}" with icon note'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120
        )
        return f"button returned:{ok_label}" in (result.stdout or "")
    except Exception:
        return False


# ─── Implementación de tools ────────────────────────────────────────────────
def tool_paste_text(text: str) -> str:
    print(f"📝 {text}", flush=True)
    paste_text_at_cursor(text)
    return "pegado"


def tool_open_app(app_name: str) -> str:
    print(f"🚀 Abriendo: {app_name}", flush=True)
    subprocess.Popen(["open", "-a", app_name])
    play_sound("cmd")
    return f"abriendo {app_name}"


def tool_close_app(app_name: str) -> str:
    """Cierra una app vía AppleScript. Si hay cambios sin guardar, la app pregunta."""
    print(f"🛑 Cerrando: {app_name}", flush=True)
    name_esc = _applescript_escape(app_name)
    script = f'tell application "{name_esc}" to quit'
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        if result.returncode != 0 and result.stderr:
            # Fallback: System Events kill
            print(f"   AppleScript falló, intento pkill: {result.stderr.strip()}", flush=True)
            subprocess.run(["pkill", "-x", app_name], capture_output=True)
        play_sound("cmd")
        return f"cerrando {app_name}"
    except Exception as e:
        play_sound("error")
        return f"error: {e}"


def tool_search_web(query: str) -> str:
    url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
    print(f"🔍 Buscando en Chrome: {query}", flush=True)
    # Forzar Chrome (si está instalado); fallback al navegador por defecto
    chrome_path = "/Applications/Google Chrome.app"
    if Path(chrome_path).exists():
        subprocess.Popen(["open", "-a", "Google Chrome", url])
    else:
        subprocess.Popen(["open", url])
    play_sound("cmd")
    return f"buscando {query}"


def tool_compose_email(to: str, subject: str, body: str) -> str:
    """Abre Gmail Web con el email pre-redactado para revisión y envío manual."""
    summary = f"Para: {to}\nAsunto: {subject}\n\n{body}"
    if not confirm_dialog("¿Abrir borrador de email?", summary, ok_label="Abrir Gmail"):
        print("✖️  Email cancelado por el usuario", flush=True)
        return "cancelado"

    url = (
        "https://mail.google.com/mail/?view=cm&fs=1"
        f"&to={urllib.parse.quote(to)}"
        f"&su={urllib.parse.quote(subject)}"
        f"&body={urllib.parse.quote(body)}"
    )
    chrome_path = "/Applications/Google Chrome.app"
    if Path(chrome_path).exists():
        subprocess.Popen(["open", "-a", "Google Chrome", url])
    else:
        subprocess.Popen(["open", url])
    print(f"📧 Abriendo Gmail con borrador para {to}", flush=True)
    play_sound("ok")
    return "borrador abierto"


def tool_send_whatsapp(contact: str, message: str) -> str:
    """Abre WhatsApp con mensaje pre-cargado. Si contact es un número, lo precarga."""
    summary = f"A: {contact}\n\n{message}"
    if not confirm_dialog("¿Abrir WhatsApp con este mensaje?", summary, ok_label="Abrir WhatsApp"):
        print("✖️  WhatsApp cancelado por el usuario", flush=True)
        return "cancelado"

    # Detectar si contact es un número (con o sin +)
    digits = "".join(c for c in contact if c.isdigit())
    if digits and len(digits) >= 7:
        # Número detectado → URL scheme con phone
        url = f"whatsapp://send?phone={digits}&text={urllib.parse.quote(message)}"
    else:
        # Es un nombre → solo precarga texto, usuario elige contacto
        url = f"whatsapp://send?text={urllib.parse.quote(message)}"

    subprocess.Popen(["open", url])
    print(f"💬 Abriendo WhatsApp para {contact}", flush=True)
    play_sound("ok")
    return "whatsapp abierto"


def tool_create_calendar_event(
    title: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: str = "",
) -> str:
    """Abre Google Calendar Web con el evento pre-rellenado para confirmación."""
    summary_lines = [
        f"Título: {title}",
        f"Inicio: {start}",
        f"Fin: {end}",
    ]
    if location:
        summary_lines.append(f"Lugar: {location}")
    if attendees:
        summary_lines.append(f"Invitados: {attendees}")
    if description:
        summary_lines.append(f"Descripción: {description}")
    summary = "\n".join(summary_lines)

    if not confirm_dialog("¿Crear evento en Google Calendar?", summary, ok_label="Crear evento"):
        print("✖️  Evento cancelado por el usuario", flush=True)
        return "cancelado"

    # Convertir ISO 8601 a formato Google Calendar (YYYYMMDDTHHMMSS)
    def iso_to_gcal(iso_str: str) -> str:
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", ""))
            return dt.strftime("%Y%m%dT%H%M%S")
        except Exception:
            return iso_str.replace("-", "").replace(":", "").split(".")[0]

    start_gcal = iso_to_gcal(start)
    end_gcal = iso_to_gcal(end)

    params = {
        "text": title,
        "dates": f"{start_gcal}/{end_gcal}",
    }
    if description:
        params["details"] = description
    if location:
        params["location"] = location
    if attendees:
        params["add"] = attendees

    url = "https://calendar.google.com/calendar/r/eventedit?" + urllib.parse.urlencode(params)
    chrome_path = "/Applications/Google Chrome.app"
    if Path(chrome_path).exists():
        subprocess.Popen(["open", "-a", "Google Chrome", url])
    else:
        subprocess.Popen(["open", url])
    print(f"📅 Abriendo Calendar con evento: {title}", flush=True)
    play_sound("ok")
    return "evento abierto"


def tool_create_reminder(title: str, due_date: str = "") -> str:
    """Crea un recordatorio en la app Recordatorios de macOS via AppleScript."""
    print(f"📌 Creando recordatorio: {title}" + (f" ({due_date})" if due_date else ""), flush=True)
    title_esc = _applescript_escape(title)

    if due_date:
        try:
            dt = datetime.fromisoformat(due_date.replace("Z", ""))
            # AppleScript date format: "Friday, May 15, 2026 at 5:00:00 PM"
            applescript_date = dt.strftime("%A, %B %d, %Y at %I:%M:%S %p")
            script = (
                f'tell application "Reminders" to make new reminder '
                f'with properties {{name:"{title_esc}", '
                f'due date:date "{applescript_date}"}}'
            )
        except Exception:
            script = f'tell application "Reminders" to make new reminder with properties {{name:"{title_esc}"}}'
    else:
        script = f'tell application "Reminders" to make new reminder with properties {{name:"{title_esc}"}}'

    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        play_sound("ok")
        return "recordatorio creado"
    except Exception as e:
        print(f"❌ Error creando recordatorio: {e}", flush=True)
        play_sound("error")
        return f"error: {e}"


# ─── Tool dispatcher ────────────────────────────────────────────────────────
TOOL_HANDLERS = {
    "paste_text": tool_paste_text,
    "open_app": tool_open_app,
    "close_app": tool_close_app,
    "search_web": tool_search_web,
    "compose_email": tool_compose_email,
    "send_whatsapp": tool_send_whatsapp,
    "create_calendar_event": tool_create_calendar_event,
    "create_reminder": tool_create_reminder,
}


def execute_tool(name: str, args: dict) -> str:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        print(f"⚠️  Tool desconocida: {name}", flush=True)
        return "tool no encontrada"
    try:
        return handler(**args)
    except TypeError as e:
        print(f"❌ Argumentos inválidos para {name}: {e}", flush=True)
        play_sound("error")
        return f"error: {e}"
    except Exception as e:
        print(f"❌ Error ejecutando {name}: {e}", flush=True)
        play_sound("error")
        return f"error: {e}"


# ─── Tool definitions para Gemini ───────────────────────────────────────────
def build_tools():
    """Construye las definiciones de tools en el formato del SDK google-genai."""
    from google.genai import types

    Schema = types.Schema
    Type = types.Type

    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="paste_text",
            description=(
                "Pega texto refinado donde está el cursor. ÚSALA SIEMPRE que el "
                "input sea dictado normal (prosa, lista, redacción) y NO sea un "
                "comando ejecutable claro. Arregla puntuación, acentos y "
                "mayúsculas. NO traduzcas ni reformules el contenido."
            ),
            parameters=Schema(
                type=Type.OBJECT,
                properties={
                    "text": Schema(
                        type=Type.STRING,
                        description="Texto formateado. Si el usuario dictó una lista explícita, formato markdown.",
                    ),
                },
                required=["text"],
            ),
        ),
        types.FunctionDeclaration(
            name="open_app",
            description="Abre una aplicación de macOS por su nombre.",
            parameters=Schema(
                type=Type.OBJECT,
                properties={
                    "app_name": Schema(type=Type.STRING, description="Nombre de la app (ej: Spotify, Chrome, Notion, WhatsApp)"),
                },
                required=["app_name"],
            ),
        ),
        types.FunctionDeclaration(
            name="close_app",
            description=(
                "Cierra una aplicación de macOS. Usar para 'cierra X', 'sal de X', "
                "'quit X', 'apaga X'. Si la app tiene cambios sin guardar, "
                "preguntará al usuario antes de cerrar."
            ),
            parameters=Schema(
                type=Type.OBJECT,
                properties={
                    "app_name": Schema(type=Type.STRING, description="Nombre de la app a cerrar"),
                },
                required=["app_name"],
            ),
        ),
        types.FunctionDeclaration(
            name="search_web",
            description="Abre Google Chrome y busca en Google.",
            parameters=Schema(
                type=Type.OBJECT,
                properties={
                    "query": Schema(type=Type.STRING, description="Términos de búsqueda"),
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="compose_email",
            description=(
                "Abre Gmail Web con un email pre-redactado para que el usuario "
                "lo revise y envíe. NO envía automáticamente. Usar cuando el "
                "usuario diga 'manda email a X' o similar."
            ),
            parameters=Schema(
                type=Type.OBJECT,
                properties={
                    "to": Schema(type=Type.STRING, description="Email del destinatario, o varios separados por coma"),
                    "subject": Schema(type=Type.STRING, description="Asunto del email"),
                    "body": Schema(type=Type.STRING, description="Cuerpo del email, bien redactado y con puntuación"),
                },
                required=["to", "subject", "body"],
            ),
        ),
        types.FunctionDeclaration(
            name="send_whatsapp",
            description=(
                "Abre WhatsApp con un mensaje pre-cargado para que el usuario "
                "lo revise y envíe. NO envía automáticamente. Usar cuando el "
                "usuario diga 'manda whatsapp a X' o 'manda WA a X'. "
                "Si el usuario menciona un número, ponlo en 'contact' con "
                "código de país (ej: +34666123456). Si solo da nombre, pon el nombre tal cual."
            ),
            parameters=Schema(
                type=Type.OBJECT,
                properties={
                    "contact": Schema(type=Type.STRING, description="Número con código país, o nombre del contacto"),
                    "message": Schema(type=Type.STRING, description="Mensaje a enviar"),
                },
                required=["contact", "message"],
            ),
        ),
        types.FunctionDeclaration(
            name="create_calendar_event",
            description=(
                "Crea un evento en Google Calendar abriendo el formulario web "
                "pre-rellenado. Convierte fechas/horas relativas ('mañana a las 5') "
                "a ISO 8601 absoluto basándote en la fecha y hora actuales que se "
                "te proporcionan en el contexto."
            ),
            parameters=Schema(
                type=Type.OBJECT,
                properties={
                    "title": Schema(type=Type.STRING, description="Título del evento"),
                    "start": Schema(type=Type.STRING, description="Inicio en ISO 8601, ej: 2026-05-15T17:00:00"),
                    "end": Schema(type=Type.STRING, description="Fin en ISO 8601, ej: 2026-05-15T18:00:00. Si no se especifica duración, asume 1 hora."),
                    "description": Schema(type=Type.STRING, description="Descripción opcional"),
                    "location": Schema(type=Type.STRING, description="Lugar opcional"),
                    "attendees": Schema(type=Type.STRING, description="Emails de invitados separados por coma, opcional"),
                },
                required=["title", "start", "end"],
            ),
        ),
        types.FunctionDeclaration(
            name="create_reminder",
            description=(
                "Crea un recordatorio en la app Recordatorios de macOS. "
                "Usar para 'recuérdame X', 'añade tarea X'."
            ),
            parameters=Schema(
                type=Type.OBJECT,
                properties={
                    "title": Schema(type=Type.STRING, description="Texto del recordatorio"),
                    "due_date": Schema(type=Type.STRING, description="Fecha/hora ISO 8601 opcional, ej: 2026-05-15T09:00:00"),
                },
                required=["title"],
            ),
        ),
    ])]


def build_system_instruction() -> str:
    now = datetime.now()

    user_context = dictionary_data.get("context", "")
    vocab = dictionary_data.get("vocabulary", [])
    vocab_block = ""
    if vocab:
        vocab_block = (
            "\nVOCABULARIO PERSONAL (escribe estos términos con su mayúscula/ortografía exacta):\n"
            + ", ".join(vocab) + "\n"
        )

    user_block = ""
    if user_context:
        user_block = f"\nCONTEXTO DEL USUARIO:\n{user_context}\n"

    return (
        "Eres el cerebro de un asistente de voz para macOS. Recibes texto "
        "transcrito de la voz del usuario (español, inglés o mezcla).\n\n"
        "TU ÚNICA TAREA es decidir qué FUNCIÓN llamar y con qué argumentos.\n\n"
        "REGLAS PRINCIPALES:\n"
        "- Si es DICTADO (prosa, lista, redacción) → `paste_text` con el texto "
        "limpio. NO traduzcas. NO añadas información. Conserva el contenido.\n"
        "- Si es un COMANDO claro (abrir/cerrar app, buscar, email, WA, evento, "
        "recordatorio) → llama a la función adecuada.\n"
        "- Si el comando es ambiguo → `paste_text` con el texto literal.\n\n"
        "REGLAS DE LIMPIEZA DE TEXTO (al usar paste_text):\n"
        "1. Quita muletillas (eh, este, o sea, vale, tipo, um, uh, like, you know) "
        "salvo que cambien el sentido.\n"
        "2. Aplica autocorrecciones / backtrack: si el usuario rectifica "
        "('quedamos a las 2... mejor a las 3') escribe SOLO la versión final "
        "('Quedamos a las 3').\n"
        "3. Arregla puntuación, acentos, mayúsculas y separación de frases.\n"
        "4. Si dictó marcadores explícitos de lista (punto A/B/C, primero/segundo) "
        "formatea como lista markdown.\n"
        "5. Conserva el idioma original del dictado. NO traduzcas a otro idioma "
        "salvo que el usuario lo pida expresamente.\n"
        f"{vocab_block}{user_block}"
        f"\nCONTEXTO TEMPORAL:\n"
        f"- Fecha actual: {now.strftime('%A %d de %B de %Y')}\n"
        f"- Hora actual: {now.strftime('%H:%M')}\n"
        f"- ISO ahora: {now.isoformat(timespec='seconds')}\n"
        "Convierte fechas relativas ('mañana', 'el viernes', 'en 2 horas') a "
        "ISO 8601 absoluto basándote en este contexto.\n\n"
        "SIEMPRE llama a EXACTAMENTE UNA función. No respondas con texto plano."
    )


# ─── Replace selected text ───────────────────────────────────────────────────
def is_cmd_key(key) -> bool:
    """True si la tecla es cualquier variante de Command."""
    for attr in ("cmd", "cmd_r", "cmd_l"):
        k = getattr(keyboard.Key, attr, None)
        if k is not None and key == k:
            return True
    return False


def capture_selection() -> str | None:
    """Hace Cmd+C, lee el portapapeles, restaura el clipboard previo.

    Devuelve la selección (string) o None si no hay nada seleccionado.
    Usa un marker para distinguir 'no había selección' de 'clipboard vacío'.
    """
    try:
        previous = pyperclip.paste()
    except Exception:
        previous = ""

    # Marker para detectar si Cmd+C no copió nada
    try:
        pyperclip.copy(CLIPBOARD_MARKER)
    except Exception:
        pass
    time.sleep(0.05)

    ctrl = keyboard.Controller()
    with ctrl.pressed(keyboard.Key.cmd):
        ctrl.press('c')
        ctrl.release('c')

    # Esperar a que macOS procese el Cmd+C
    time.sleep(0.18)

    try:
        new_clip = pyperclip.paste()
    except Exception:
        new_clip = ""

    # Restaurar clipboard original en background
    def restore():
        time.sleep(0.6)
        try:
            pyperclip.copy(previous)
        except Exception:
            pass
    threading.Thread(target=restore, daemon=True).start()

    if not new_clip or new_clip == CLIPBOARD_MARKER:
        return None
    return new_clip


def gemini_replace_selection(instruction: str, selected_text: str) -> None:
    """Manda selección + instrucción a Gemini y reemplaza con el resultado."""
    if not gemini_client:
        print("⚠️  Gemini no disponible — modo replace abortado", flush=True)
        play_sound("error")
        return

    prompt = (
        "Eres un editor de texto guiado por voz. Estos son los datos:\n\n"
        "TEXTO SELECCIONADO (delimitado por <<<>>>):\n"
        f"<<<{selected_text}>>>\n\n"
        "INSTRUCCIÓN HABLADA DEL USUARIO:\n"
        f"{instruction}\n\n"
        "REGLAS:\n"
        "- Aplica la instrucción al texto seleccionado.\n"
        "- Devuelve SOLO el texto modificado, sin explicaciones, sin comillas, sin "
        "markdown extra (a menos que el original ya tuviera markdown).\n"
        "- NO cambies más de lo que se pide. Conserva el formato y la longitud "
        "aproximada salvo que se pida explícitamente acortar/extender.\n"
        "- Si la instrucción es 'tradúcelo a X', traduce. Si es 'más formal' / "
        "'más casual', ajusta el tono. Si es 'corrige errores', solo corrige.\n"
        "- Conserva el idioma original salvo que se pida traducir."
    )

    try:
        from google.genai import types
        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            temperature=0.2,
        )
        r = gemini_client.models.generate_content(
            model=GEMINI_MODEL, contents=prompt, config=config,
        )
        new_text = (r.text or "").strip()
    except Exception as e:
        print(f"❌ Gemini error en replace: {e}", flush=True)
        play_sound("error")
        return

    if not new_text:
        print("⚠️  Gemini devolvió vacío — selección NO modificada", flush=True)
        play_sound("error")
        return

    preview_orig = selected_text[:60].replace("\n", "↵")
    preview_new = new_text[:60].replace("\n", "↵")
    print(f"✏️  Replace:\n   antes: {preview_orig}…\n   después: {preview_new}…", flush=True)

    # Cmd+V reemplaza la selección (si sigue activa) con el nuevo texto
    paste_text_at_cursor(new_text)
    play_sound("ok")


# ─── Gemini routing ─────────────────────────────────────────────────────────
def init_gemini():
    global gemini_client
    if not GEMINI_ENABLED:
        print("ℹ️  Gemini desactivado. Modo transcripción pura.", flush=True)
        return None
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("⚠️  No hay GEMINI_API_KEY/GOOGLE_API_KEY. Gemini desactivado.", flush=True)
        return None
    try:
        from google import genai
        gemini_client = genai.Client(api_key=api_key)
        print("✅ Gemini conectado.", flush=True)
        return gemini_client
    except Exception as e:
        print(f"⚠️  Gemini no disponible: {e}", flush=True)
        return None


def gemini_route_and_execute(text: str) -> None:
    """Manda el texto a Gemini con tools. Ejecuta la tool elegida."""
    if not gemini_client:
        # Sin Gemini → fallback a transcripción pura
        tool_paste_text(text)
        return

    try:
        from google.genai import types
        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            temperature=0.1,
            tools=build_tools(),
            system_instruction=build_system_instruction(),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            ),
        )
        r = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=text,
            config=config,
        )
    except Exception as e:
        print(f"⚠️  Gemini error, fallback a texto plano: {e}", flush=True)
        tool_paste_text(text)
        return

    # Buscar function_call en la respuesta
    fc = None
    try:
        for cand in (r.candidates or []):
            for part in (cand.content.parts or []):
                if getattr(part, "function_call", None):
                    fc = part.function_call
                    break
            if fc:
                break
    except Exception:
        fc = None

    if fc:
        name = fc.name
        # args puede ser dict o MapComposite — convertir a dict
        try:
            args = dict(fc.args) if fc.args else {}
        except Exception:
            args = {}
        print(f"🛠️  Tool: {name}({', '.join(f'{k}={v!r}' for k,v in args.items())})", flush=True)
        execute_tool(name, args)
    else:
        # No hubo tool call → tratamos el texto literal como dictado
        fallback_text = (r.text or text).strip()
        tool_paste_text(fallback_text)


# ─── Audio + Whisper ────────────────────────────────────────────────────────
def audio_callback(indata, frames, time_info, status):
    if status:
        print(f"[audio] {status}", file=sys.stderr)
    if recording:
        audio_queue.put(indata.copy())


def start_recording():
    global recording, recording_start_time
    if recording:
        return
    while not audio_queue.empty():
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            break
    recording = True
    recording_start_time = time.time()
    print("🎙️  Grabando…", flush=True)
    play_sound("start")


def stop_recording_and_route(replace_mode: bool = False):
    global recording
    if not recording:
        return
    recording = False
    duration = time.time() - recording_start_time
    play_sound("stop")

    if duration < MIN_DURATION_SEC:
        print(f"⏱️  Pulsación muy corta ({duration:.2f}s) — ignorada", flush=True)
        return

    chunks = []
    while not audio_queue.empty():
        try:
            chunks.append(audio_queue.get_nowait())
        except queue.Empty:
            break
    if not chunks:
        print("⚠️  Sin audio capturado", flush=True)
        return

    # En modo replace: capturamos la selección AHORA (antes de procesar audio)
    # para que la selección siga activa visualmente cuando hagamos Cmd+C.
    selection = None
    if replace_mode:
        selection = capture_selection()
        if selection is None:
            print("⚠️  Modo replace pedido pero NO hay selección — fallback a dictado normal", flush=True)
        else:
            preview = selection[:80].replace("\n", "↵")
            print(f"📑 Selección capturada ({len(selection)} chars): {preview}…", flush=True)

    audio = np.concatenate(chunks, axis=0).flatten().astype(np.float32)
    print(f"🔊 {duration:.2f}s capturados → transcribiendo…", flush=True)

    try:
        result = model.transcribe(
            audio,
            language=LANGUAGE,
            fp16=False,
            task="transcribe",
            initial_prompt=whisper_initial_prompt(),
        )
        text = (result.get("text") or "").strip()
    except Exception as e:
        print(f"❌ Whisper error: {e}", flush=True)
        play_sound("error")
        return

    if not text:
        print("⚠️  Transcripción vacía", flush=True)
        return

    print(f"🗣️  Whisper → {text!r}", flush=True)

    # Modo REPLACE: selección + instrucción → Gemini → reemplazar
    if replace_mode and selection:
        threading.Thread(
            target=gemini_replace_selection,
            args=(text, selection),
            daemon=True,
        ).start()
        return

    # Snippet lookup local
    snippet_value = match_snippet(text)
    if snippet_value is not None:
        print(f"📋 Snippet match → pegando atajo", flush=True)
        tool_paste_text(snippet_value)
        return

    # Modo NORMAL: routing por tools
    threading.Thread(target=gemini_route_and_execute, args=(text,), daemon=True).start()


def on_press(key):
    global replace_mode_requested, replace_mode_announced
    if key == HOTKEY:
        # Reset flags al empezar nueva grabación
        replace_mode_requested = False
        replace_mode_announced = False
        start_recording()
    elif recording and is_cmd_key(key):
        replace_mode_requested = True
        if not replace_mode_announced:
            replace_mode_announced = True
            print("🔄 Modo replace activado (⌥+⌘)", flush=True)
            play_sound("cmd")


def on_release(key):
    if key == HOTKEY:
        stop_recording_and_route(replace_mode=replace_mode_requested)
    return True


def main():
    global model

    request_accessibility_permission()
    load_dictionary()
    load_snippets()

    print(f"⏳ Cargando Whisper '{MODEL_NAME}'…", flush=True)
    t0 = time.time()
    model = whisper.load_model(MODEL_NAME)
    print(f"✅ Modelo cargado en {time.time()-t0:.1f}s", flush=True)

    init_gemini()

    print(f"🎧 Listo. Atajos:", flush=True)
    print(f"   ⌥ derecha               → dictado / comando", flush=True)
    print(f"   ⌥ derecha + ⌘ (durante) → modo REPLACE: transforma texto seleccionado", flush=True)
    print(f"   Modelo: {MODEL_NAME}  ·  Idioma: {LANGUAGE or 'auto'}  ·  Gemini: {'on' if gemini_client else 'off'}", flush=True)
    print(f"   Tools: {', '.join(TOOL_HANDLERS.keys())}", flush=True)
    print(f"   Ctrl+C para salir.\n", flush=True)

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        callback=audio_callback,
        blocksize=int(SAMPLE_RATE * 0.05),
    )
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)

    with stream:
        listener.start()
        try:
            listener.join()
        except KeyboardInterrupt:
            print("\n👋 Saliendo…", flush=True)


if __name__ == "__main__":
    main()
