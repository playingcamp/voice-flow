#!/bin/zsh
# Lanzador de voiceflow
cd "$(dirname "$0")"

# Cargar API keys del .zshrc (necesario cuando se lanza vía LaunchAgent)
if [ -f ~/.zshrc ]; then
    eval "$(grep -E '^export (GEMINI_API_KEY|GOOGLE_API_KEY)=' ~/.zshrc)"
fi

source venv/bin/activate
exec python3 voiceflow.py
