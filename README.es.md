# VoiceFlow

🌍 **Idiomas:** [English](./README.md) · **Español**

> Asistente de voz local y *agentic* para macOS. Alternativa a [Wispr Flow](https://wisprflow.ai) construida en una tarde con [Claude Code](https://claude.com/claude-code).
>
> **Coste:** ~0 €/mes. Whisper corre en local, Gemini usa free tier.

Push-to-talk con `⌥` derecha: dicta texto en cualquier app, ejecuta acciones (email, WhatsApp, calendar, recordatorios), y reemplaza texto seleccionado con transformaciones de voz.

## Features

- 🎙️ **Push-to-talk** con tecla configurable (por defecto `⌥` derecha)
- 🌍 **Multi-idioma automático** (ES, EN, mezcla — vía Whisper)
- 🧠 **AI cleanup** vía Gemini: puntuación, acentos, mayúsculas, listas
- 🧹 **Remove fillers** ("eh", "este", "o sea", "um", "uh")
- ⏪ **Backtrack**: *"a las 2... mejor a las 3"* → *"a las 3"*
- 📖 **Diccionario personal** para nombres propios y jerga
- 📋 **Snippets** locales con matching exacto (~0 ms)
- ✏️ **Replace selected text** (modo `⌥`+`⌘`): selecciona texto y dicta instrucción para transformarlo
- 🤖 **8 tools agentic**: dictar, abrir/cerrar apps, buscar en Chrome, redactar email, mandar WhatsApp, crear evento de calendar, crear recordatorio
- ✅ **Confirmación visual** antes de mandar emails, WhatsApp o crear eventos

## Stack

| Componente | Para qué | Coste |
|---|---|---|
| [Whisper](https://github.com/openai/whisper) (modelo `base`, local) | Speech-to-text | Gratis, offline |
| [Gemini 2.5 Flash](https://ai.google.dev) | Routing + formato + transformaciones | Free tier: 1.500 req/día |
| [pynput](https://github.com/moses-palmer/pynput) | Hotkey global + simulación teclado | Gratis |
| [sounddevice](https://python-sounddevice.readthedocs.io) | Captura de audio en RAM | Gratis |

## Requisitos

- macOS (Sequoia / Tahoe testado)
- Python 3.10+
- API key gratis de [Google AI Studio](https://ai.google.dev/gemini-api/docs/api-key) → exporta como `GEMINI_API_KEY`
- ~500 MB libres (modelo Whisper `base`)

## Instalación

```bash
git clone https://github.com/<tu-usuario>/voice-flow.git
cd voice-flow

# Entorno Python (importante: --symlinks para que el wrapper .app funcione con TCC)
python3 -m venv --symlinks venv
source venv/bin/activate
pip install -r requirements.txt

# API key de Gemini (free tier)
echo 'export GEMINI_API_KEY="tu_clave_aquí"' >> ~/.zshrc
source ~/.zshrc

# Configurar dictionary y snippets a tu gusto
cp dictionary.example.json dictionary.json
cp snippets.example.json snippets.json
# edita ambos con tu vocabulario y atajos personales

# Build de la .app (genera VoiceFlow.app con tus paths)
chmod +x build_app.sh run.sh
./build_app.sh

# Lanzar
open VoiceFlow.app
```

### Permisos macOS

La primera vez que pulses `⌥`, macOS pedirá permisos a **VoiceFlow.app**. Concede:

| Permiso | Dónde | Para qué |
|---|---|---|
| **Accesibilidad** | Configuración → Privacidad y Seguridad → Accesibilidad | Simular Cmd+V (pegar texto) |
| **Monitorización de entrada** | Configuración → Privacidad y Seguridad → Monitorización de entrada | Detectar la tecla `⌥` globalmente |
| **Micrófono** | (se pedirá automáticamente) | Capturar audio |

Tras conceder, reinicia la app: `pkill -f voiceflow.py; sleep 1; open VoiceFlow.app`

### Auto-arranque al login (opcional)

Configuración del Sistema → General → Elementos de inicio de sesión → `+` → selecciona `VoiceFlow.app`.

## Uso

| Atajo | Función |
|---|---|
| `⌥ derecha` (mantener) | Graba mientras la mantengas pulsada |
| Soltar `⌥` | Procesa y ejecuta |
| `⌥ derecha` + `⌘` (durante grabación) | **Modo REPLACE**: transforma el texto seleccionado |

### Ejemplos

| Dictas | Resultado |
|---|---|
| "hola qué tal estás" | Pega *"Hola, ¿qué tal estás?"* (con puntuación correcta) |
| "abre Spotify" | Abre la app |
| "cierra Chrome" | Cierra la app |
| "busca recetas de paella" | Abre Chrome con la búsqueda |
| "manda email a juan@x.com diciéndole que confirmo la reunión" | Diálogo de confirmación → Gmail Web con borrador listo |
| "manda WhatsApp al +34666... diciendo llego en 10 minutos" | Diálogo → WhatsApp Desktop con mensaje pre-cargado |
| "crea evento mañana a las 5 con María sobre el proyecto" | Diálogo → Google Calendar con todo prellenado |
| "recuérdame llamar a Pedro mañana a las 9" | Aparece en Recordatorios.app con fecha |

### Modo REPLACE (la killer feature)

1. Selecciona un texto en cualquier app
2. Pulsa `⌥` derecha y mantén
3. Toca `⌘` (oirás un sonido — modo replace activo)
4. Habla la instrucción ("más formal", "tradúcelo al inglés", "más corto", "corrige errores")
5. Suelta `⌥` → el texto se reemplaza con la versión transformada

## Personalización

### Diccionario personal (`dictionary.json`)

```json
{
  "vocabulary": ["TuMarca", "NombrePropio", "JergaTécnica"],
  "context": "Breve descripción de ti y tu trabajo, para que Gemini contextualice."
}
```

Estos términos se inyectan en:
- `initial_prompt` de Whisper → mejor transcripción de nombres propios
- System instruction de Gemini → respeta mayúsculas/ortografía

### Snippets (`snippets.json`)

```json
{
  "snippets": {
    "firma mail": "Un saludo,\nTu Nombre",
    "mi email": "tu@email.com"
  }
}
```

Si dictas la clave exacta (case-insensitive), se pega el valor sin pasar por Gemini → latencia mínima.

### Cambiar el modelo de Whisper

En `voiceflow.py`:

```python
MODEL_NAME = "base"   # tiny | base | small | medium | large
```

- `tiny` / `base`: rápidos, ideal en Mac de 8 GB de RAM
- `small`: más precisión, ~250 MB extra RAM
- `medium` / `large`: máxima precisión, ~2 GB RAM, recomendado solo con 16 GB+

### Cambiar el hotkey

En `voiceflow.py`:

```python
HOTKEY = keyboard.Key.alt_r   # Right Option
# Otras: keyboard.Key.cmd_r, keyboard.Key.shift_r, keyboard.Key.ctrl_r
```

## Operar el servicio

```bash
# Iniciar
open VoiceFlow.app

# Parar
pkill -f voiceflow.py

# Reiniciar
pkill -f voiceflow.py; sleep 1; open VoiceFlow.app

# Ver logs en vivo
tail -f voiceflow.log
```

## Troubleshooting

| Síntoma | Solución |
|---|---|
| `This process is not trusted!` en err log | Activa VoiceFlow en Accesibilidad **y** Monitorización de entrada |
| Tecla `⌥` no detectada tras conceder permisos | `tccutil reset Accessibility com.voiceflow.local`, reabrir app, reconceder |
| `ModuleNotFoundError` al lanzar | El venv se rompió al mover la carpeta. Recrea: `python3 -m venv --clear --symlinks venv && pip install -r requirements.txt` |
| Whisper descarga modelo falla con SSL | Tu red intercepta certificados. Descarga manualmente el modelo desde [openaipublic.azureedge.net](https://github.com/openai/whisper/blob/main/whisper/__init__.py) a `~/.cache/whisper/` |
| Transcripción mala con nombres propios | Añádelos a `dictionary.json` y reinicia |
| Modo replace no captura selección | Comprueba que `Cmd+C` funciona en esa app; algunas web apps complejas no lo soportan estándar |

## Limitaciones conocidas

- **Solo macOS**. Linux/Windows requerirían reescribir partes (TCC permissions, AppleScript, URL schemes).
- **Permisos TCC se invalidan si recompilas la app** con distinto bundle ID. Por eso `build_app.sh` usa siempre `com.voiceflow.local` estable.
- **Sin firma de Apple Developer**: el bundle se firma ad-hoc, lo cual funciona pero macOS Gatekeeper podría avisar la primera vez (Click derecho → Abrir).
- **WhatsApp y email son semi-automáticos** por seguridad: abren el cliente con el mensaje pre-cargado, tú confirmas el envío manualmente.
- **Gemini free tier**: 1.500 requests/día. Suficiente para uso personal intensivo.

## Roadmap

- [ ] Indicador en barra de menú (rumps)
- [ ] Estilos por app (más formal en Gmail, casual en WhatsApp)
- [ ] Historial de transcripciones / repetir última
- [ ] Tools personalizables vía plugins
- [ ] Soporte para Linux (pynput + xdotool)

## Licencia

MIT. Ver [LICENSE](./LICENSE).

## Créditos

Construido en una tarde con [Claude Code](https://claude.com/claude-code). Inspirado por [Wispr Flow](https://wisprflow.ai). Whisper de OpenAI, Gemini de Google.
