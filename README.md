# Audio über LAN: macOS → Windows

Direkte Mikrofonübertragung über ein lokales Ethernet-Netzwerk ohne zusätzlichen
Server. Python-Sender für macOS und Empfänger für Windows, mit festen IP-Adressen:

| Gerät | Adresse |
|---|---|
| Windows-Empfänger | `192.168.10.1/24` |
| macOS-Sender | `192.168.10.2/24` |

UDP-Port: **5000**. Standard: Mono, PCM 16 Bit, 48 kHz, 10-ms-Pakete.

## Herunterladen und starten

Das vollständige [Paket für Mac und Windows](Audio_LAN_Mac_Windows.zip)
herunterladen und auf beiden Geräten entpacken. Alternativ dieses Repository
klonen oder über **Code → Download ZIP** herunterladen.

Python 3.10 oder neuer verwenden.

**Windows**

1. `Installieren_Windows.cmd` ausführen.
2. `Empfaenger_Sprache.cmd` starten und die Device-ID des Audioausgangs auswählen.
3. Lautstärke und Stummschaltung in Windows prüfen.

**macOS**

1. `Installieren_macOS.command` ausführen.
2. `Sender_macOS.command` starten und das tatsächlich angeschlossene Mikrofon bzw.
   Audiointerface auswählen.
3. Den Mikrofonzugriff für das Terminal erlauben, wenn macOS danach fragt.

Falls die Mac-Dateien nicht ausführbar sind, im entpackten Ordner ausführen:

```sh
chmod +x *.command
./Installieren_macOS.command
./Sender_macOS.command
```

Genau einen Sender und einen Empfänger starten. Beenden mit **Strg+C**.
Für ein isoliertes Ethernet-Netz sind kein Gateway und kein DNS nötig;
die Windows-Firewall muss den Empfang auf UDP-Port 5000 erlauben.

## Funktionen

- Begrenzter Jitterpuffer, standardmäßig 120 ms.
- Ausgleich kleiner Unterschiede zwischen den Audiotakten.
- Erkennung von Sender-Neustarts und Formatwechseln.
- Sanfte Übergänge bei Paketlücken und erneutes Vorpuffern nach Unterbrechungen.
- Sitzungskennung, Sequenznummern und CRC32 in Protokoll 2.
- Kompatibilität mit dem älteren AUD0-Sender.
- Originalprofil und schonendes Sprachprofil mit einer schmalen 50-Hz-Sperre.
- Keine Sperren für Sprach-Oberwellen und kein Noise-Gate im Standardbetrieb.
- Anzeigen für Paketlücken, Audio-Unterläufe, Pegel und Aufnahmefehler.

## Stand und Fehlersuche

**Die Softwaretests bestehen; klare Sprache auf der konkreten Mikrofonstrecke
ist noch nicht bestätigt.** Die erste, aggressive Filterversion hat den Hörtest
nicht bestanden und wurde ersetzt. Im ankommenden Originalsignal wurde starkes
50-Hz-Brummen gemessen. Ein Netzwerkpuffer behebt kein bereits aufgenommenes Brummen.

1. `Mikrofontest_macOS.command` zeichnet direkt am Mac auf und spielt lokal ab,
   vollständig ohne Netzwerk und Empfänger. Damit zuerst den Aufnahmeweg prüfen.
2. `Testton_macOS.command` erzeugt einen digitalen Testton ohne Mikrofon und prüft
   anschließend die Übertragungsstrecke.
3. `Empfaenger_Original.cmd` gibt ungefiltertes Audio zum Vergleich aus.

Die endgültige Einrichtung des neuen Senders auf macOS und der spätere
USB-C-/XLR-Ausgang benötigen noch einen Test an der tatsächlichen Hardware.

## Tests

```sh
python -m pip install -r requirements.txt
python -m unittest test_audio_system test_audio_filters -v
```

19 automatische Tests prüfen unter anderem bitgenaue UDP-Übertragung in zwei
Prozessen, Paketfehler, Neustarts, Reihenfolge, Pufferung und den Erhalt von
Stimmanteilen. Ein separater Ausgabetest verwendet ein echtes Audiogerät:

```sh
python audio_receiver.py --list-devices
python verify_audio.py --device 8
```

Device-ID `8` ist ein Beispiel und muss zur lokalen Geräteauswahl passen.

Ausführliche Einrichtung: [ANLEITUNG.md](ANLEITUNG.md).
Messungen und Grenzen der Prüfung: [TESTBERICHT.md](TESTBERICHT.md).

Mikrofonaufnahmen, Diagnoseprotokolle, lokale Sicherungen und virtuelle Umgebungen
werden nicht veröffentlicht. Das Protokoll ist für ein vertrauenswürdiges lokales
Netz gedacht und enthält keine Verschlüsselung oder Senderauthentifizierung.
