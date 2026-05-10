#!/usr/bin/env python3
"""Diagnóstico: muestra qué teclas detecta pynput. Pulsa ESC para salir."""
from pynput import keyboard

print("🔍 Pulsando ⌥ derecha (Right Option)?")
print("   Verás PRESS/RELEASE si pynput la detecta.")
print("   Si NO ves nada al pulsar = problema de permisos.")
print("   ESC para salir.\n", flush=True)

def on_press(key):
    try:
        print(f"PRESS  : {key}  (vk={getattr(key, 'vk', '?')})", flush=True)
    except Exception as e:
        print(f"PRESS error: {e}", flush=True)

def on_release(key):
    print(f"RELEASE: {key}", flush=True)
    if key == keyboard.Key.esc:
        return False

with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
    l.join()
