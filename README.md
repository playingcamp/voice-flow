# VoiceFlow

🌍 **Languages:** **English** · [Español](./README.es.md)

> Local *agentic* voice assistant for macOS. A [Wispr Flow](https://wisprflow.ai) alternative built in one afternoon with [Claude Code](https://claude.com/claude-code).
>
> **Cost:** ~$0/month. Whisper runs locally, Gemini uses the free tier.

Push-to-talk with `Right Option`: dictate text into any app, run actions (email, WhatsApp, calendar, reminders), and replace selected text using voice transformations.

## Features

- 🎙️ **Push-to-talk** with configurable hotkey (default `Right Option`)
- 🌍 **Auto multi-language** (ES, EN, mixed — via Whisper)
- 🧠 **AI cleanup** via Gemini: punctuation, accents, capitalization, lists
- 🧹 **Remove fillers** ("uh", "um", "like", "you know")
- ⏪ **Backtrack**: *"meet at 2... actually 3"* → *"meet at 3"*
- 📖 **Personal dictionary** for proper nouns and jargon
- 📋 **Local snippets** with exact match (~0 ms latency)
- ✏️ **Replace selected text** (`⌥`+`⌘` mode): select text and dictate an instruction to transform it
- 🤖 **8 agentic tools**: dictate, open/close apps, search Chrome, compose email, send WhatsApp, create calendar event, create reminder
- ✅ **Visual confirmation** before sending emails, WhatsApp messages, or creating events

## Stack

| Component | Role | Cost |
|---|---|---|
| [Whisper](https://github.com/openai/whisper) (`base` model, local) | Speech-to-text | Free, offline |
| [Gemini 2.5 Flash](https://ai.google.dev) | Routing + formatting + transformations | Free tier: 1,500 req/day |
| [pynput](https://github.com/moses-palmer/pynput) | Global hotkey + keyboard simulation | Free |
| [sounddevice](https://python-sounddevice.readthedocs.io) | Audio capture in RAM | Free |

## Requirements

- macOS (tested on Sequoia / Tahoe)
- Python 3.10+
- Free API key from [Google AI Studio](https://ai.google.dev/gemini-api/docs/api-key) → export as `GEMINI_API_KEY`
- ~500 MB free space (Whisper `base` model)

## Installation

```bash
git clone https://github.com/playingcamp/voice-flow.git
cd voice-flow

# Python environment (important: --symlinks so the .app wrapper works with TCC)
python3 -m venv --symlinks venv
source venv/bin/activate
pip install -r requirements.txt

# Gemini API key (free tier)
echo 'export GEMINI_API_KEY="your_key_here"' >> ~/.zshrc
source ~/.zshrc

# Configure dictionary and snippets to your liking
cp dictionary.example.json dictionary.json
cp snippets.example.json snippets.json
# edit both with your personal vocabulary and shortcuts

# Build the .app (generates VoiceFlow.app with your paths)
chmod +x build_app.sh run.sh
./build_app.sh

# Launch
open VoiceFlow.app
```

### macOS Permissions

The first time you press `⌥`, macOS will request permissions for **VoiceFlow.app**. Grant:

| Permission | Where | What for |
|---|---|---|
| **Accessibility** | System Settings → Privacy & Security → Accessibility | Simulate Cmd+V (paste) |
| **Input Monitoring** | System Settings → Privacy & Security → Input Monitoring | Detect the `⌥` key globally |
| **Microphone** | (requested automatically) | Capture audio |

After granting permissions, restart the app: `pkill -f voiceflow.py; sleep 1; open VoiceFlow.app`

### Auto-start at login (optional)

System Settings → General → Login Items → `+` → select `VoiceFlow.app`.

## Usage

| Shortcut | Function |
|---|---|
| `Right Option` (hold) | Records while held |
| Release `⌥` | Process and execute |
| `Right Option` + `⌘` (during recording) | **REPLACE mode**: transforms selected text |

### Examples

| You say | Result |
|---|---|
| "hello how are you" | Pastes *"Hello, how are you?"* (with correct punctuation) |
| "open Spotify" | Opens the app |
| "close Chrome" | Closes the app |
| "search for paella recipes" | Opens Chrome with the search |
| "send email to juan@x.com telling him I confirm the meeting" | Confirmation dialog → Gmail Web with ready draft |
| "send WhatsApp to +34666... saying I'll be there in 10 minutes" | Dialog → WhatsApp Desktop with pre-loaded message |
| "create event tomorrow at 5 with María about the project" | Dialog → Google Calendar prefilled |
| "remind me to call Pedro tomorrow at 9" | Appears in Reminders.app with date |

### REPLACE mode (the killer feature)

1. Select text in any app
2. Press and hold `Right Option`
3. Tap `⌘` (you'll hear a sound — replace mode active)
4. Speak the instruction ("more formal", "translate to English", "shorter", "fix errors")
5. Release `⌥` → text is replaced with the transformed version

## Customization

### Personal dictionary (`dictionary.json`)

```json
{
  "vocabulary": ["YourBrand", "ProperNoun", "TechnicalJargon"],
  "context": "Brief description of you and your work so Gemini contextualizes accordingly."
}
```

These terms are injected into:
- Whisper's `initial_prompt` → better transcription of proper nouns
- Gemini's system instruction → respects capitalization/spelling

### Snippets (`snippets.json`)

```json
{
  "snippets": {
    "email signature": "Best,\nYour Name",
    "my email": "you@email.com"
  }
}
```

If you dictate the exact key (case-insensitive), the value is pasted without going through Gemini → minimal latency.

### Change the Whisper model

In `voiceflow.py`:

```python
MODEL_NAME = "base"   # tiny | base | small | medium | large
```

- `tiny` / `base`: fast, ideal on 8 GB Macs
- `small`: more accuracy, ~250 MB extra RAM
- `medium` / `large`: maximum accuracy, ~2 GB RAM, recommended only with 16 GB+

### Change the hotkey

In `voiceflow.py`:

```python
HOTKEY = keyboard.Key.alt_r   # Right Option
# Others: keyboard.Key.cmd_r, keyboard.Key.shift_r, keyboard.Key.ctrl_r
```

## Operating the service

```bash
# Start
open VoiceFlow.app

# Stop
pkill -f voiceflow.py

# Restart
pkill -f voiceflow.py; sleep 1; open VoiceFlow.app

# Tail logs
tail -f voiceflow.log
```

## Troubleshooting

| Symptom | Solution |
|---|---|
| `This process is not trusted!` in err log | Enable VoiceFlow in both Accessibility **and** Input Monitoring |
| `⌥` key not detected after granting permissions | `tccutil reset Accessibility com.voiceflow.local`, reopen app, re-grant |
| `ModuleNotFoundError` on launch | venv broke after moving the folder. Rebuild: `python3 -m venv --clear --symlinks venv && pip install -r requirements.txt` |
| Whisper model download fails with SSL error | Your network intercepts certificates. Download the model manually from [openaipublic.azureedge.net](https://github.com/openai/whisper/blob/main/whisper/__init__.py) into `~/.cache/whisper/` |
| Bad transcription of proper nouns | Add them to `dictionary.json` and restart |
| Replace mode doesn't capture selection | Check that `Cmd+C` works in that app; some complex web apps don't support it standardly |

## Known limitations

- **macOS only**. Linux/Windows would require rewriting parts (TCC permissions, AppleScript, URL schemes).
- **TCC permissions are invalidated if you rebuild the app** with a different bundle ID. That's why `build_app.sh` always uses the stable `com.voiceflow.local`.
- **No Apple Developer signature**: the bundle is signed ad-hoc, which works but macOS Gatekeeper might warn the first time (Right-click → Open).
- **WhatsApp and email are semi-automatic** for safety: they open the client with the message pre-loaded, you confirm sending manually.
- **Gemini free tier**: 1,500 requests/day. Plenty for intensive personal use.

## Roadmap

- [ ] Menu bar indicator (rumps)
- [ ] Per-app styles (more formal in Gmail, casual in WhatsApp)
- [ ] Transcription history / repeat last
- [ ] Customizable tools via plugins
- [ ] Linux support (pynput + xdotool)

## License

MIT. See [LICENSE](./LICENSE).

## Credits

Built in one afternoon with [Claude Code](https://claude.com/claude-code). Inspired by [Wispr Flow](https://wisprflow.ai). Whisper from OpenAI, Gemini from Google.
