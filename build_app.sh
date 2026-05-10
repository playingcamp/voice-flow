#!/bin/zsh
# build_app.sh — compila VoiceFlow.app para auto-arranque al login con permisos macOS.
#
# Crea una pequeña app AppleScript que ejecuta run.sh. macOS asocia los
# permisos TCC (Accesibilidad, Input Monitoring, Micrófono) a la .app
# por su bundle ID, así que el wrapper es necesario para que las teclas
# globales y el simulado de Cmd+V funcionen.

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$PROJECT_DIR/VoiceFlow.app"
SCRIPT_TMP="$(mktemp -t voiceflow_launcher).applescript"

cat > "$SCRIPT_TMP" <<EOF
on run
	do shell script "exec '$PROJECT_DIR/run.sh' > '$PROJECT_DIR/voiceflow.log' 2> '$PROJECT_DIR/voiceflow.err.log'"
end run
EOF

# Eliminar versión previa si existe
if [ -d "$APP_PATH" ]; then
    rm -rf "$APP_PATH"
fi

# Compilar AppleScript a .app
osacompile -o "$APP_PATH" "$SCRIPT_TMP"
rm "$SCRIPT_TMP"

# Configurar Info.plist:
#  - CFBundleIdentifier estable (para que TCC asocie permisos)
#  - LSUIElement true (sin icono en Dock)
plutil -insert CFBundleIdentifier -string "com.voiceflow.local" "$APP_PATH/Contents/Info.plist" 2>/dev/null || \
    plutil -replace CFBundleIdentifier -string "com.voiceflow.local" "$APP_PATH/Contents/Info.plist"
plutil -insert LSUIElement -bool true "$APP_PATH/Contents/Info.plist" 2>/dev/null || \
    plutil -replace LSUIElement -bool true "$APP_PATH/Contents/Info.plist"
plutil -replace CFBundleName -string "VoiceFlow" "$APP_PATH/Contents/Info.plist"
plutil -insert CFBundleDisplayName -string "VoiceFlow" "$APP_PATH/Contents/Info.plist" 2>/dev/null || \
    plutil -replace CFBundleDisplayName -string "VoiceFlow" "$APP_PATH/Contents/Info.plist"

# Re-firmar (ad-hoc) para que TCC reconozca la app consistentemente
codesign --force --deep --sign - "$APP_PATH"

echo "✅ VoiceFlow.app construida en: $APP_PATH"
echo ""
echo "Siguiente paso:"
echo "  open '$APP_PATH'"
echo ""
echo "La primera vez macOS pedirá permisos (Accesibilidad, Input Monitoring, Micrófono)."
echo "Concédelos y reinicia con:"
echo "  pkill -f voiceflow.py; sleep 1; open '$APP_PATH'"
