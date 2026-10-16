"""Gemeinsame, plattformübergreifende Audiogeräte-Auswahl."""
import sounddevice as sd


def list_devices(kind):
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    devices = [(i, d) for i, d in enumerate(sd.query_devices()) if d[key] > 0]
    for index, device in devices:
        api = sd.query_hostapis(device["hostapi"])["name"]
        print(f"ID {index:2}: {device['name']} | {api} | {int(device[key])} Kanäle | {device['default_samplerate']:.0f} Hz")
    return devices


def choose_device(kind, requested=None):
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    if requested is not None:
        device = sd.query_devices(requested, kind)
        if device[key] < 1:
            raise ValueError("Das ausgewählte Gerät unterstützt diese Richtung nicht")
        return int(device["index"]), device
    devices = list_devices(kind)
    if not devices:
        raise ValueError("Kein passendes Audiogerät gefunden")
    # Explizite Auswahl verhindert, dass macOS versehentlich das interne Mikrofon nutzt.
    while True:
        value = input("Gewünschte Device-ID: ").strip()
        if value.isdigit() and any(i == int(value) for i, _ in devices):
            index = int(value)
            return index, sd.query_devices(index, kind)
        print("Bitte eine Device-ID aus der Liste eingeben.")


def platform_settings(device):
    api = sd.query_hostapis(device["hostapi"])["name"]
    return sd.WasapiSettings(auto_convert=True) if api == "Windows WASAPI" else None
