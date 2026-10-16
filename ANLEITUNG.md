# Audio zwischen Mac und Windows

Die Verbindung bleibt direkt und braucht keinen Server. Feste Adressen:

| Gerät | IPv4 | Subnetzmaske |
|---|---|---|
| Windows-Empfänger | 192.168.10.1 | 255.255.255.0 |
| macOS-Sender | 192.168.10.2 | 255.255.255.0 |

Für dieses getrennte LAN sind kein Gateway und kein DNS nötig. UDP-Port 5000
muss auf dem Empfänger erreichbar sein. Die Skripte verwenden diese Adressen
automatisch, einschließlich Bindung an die richtige Netzwerkkarte.

## Einrichten und starten

Python 3.10 oder neuer verwenden. Das vollständige Paket auf beide Geräte kopieren;
Sender und Empfänger brauchen die gemeinsamen Python-Dateien.

1. Windows: einmal `Installieren_Windows.cmd` ausführen.
2. Mac: einmal `Installieren_macOS.command` ausführen.
3. Windows: `Empfaenger_Sprache.cmd` starten und die **Device-ID** des gewünschten
   Audioausgangs eingeben. Für Mikrofone ist das Sprachprofil vorgesehen.
4. Mac: `Sender_macOS.command` starten und die **Device-ID** des tatsächlich
   angeschlossenen Mikrofon-/USB-/XLR-Interfaces auswählen.
5. macOS bei der ersten Aufnahme den Mikrofonzugriff für das Terminal erlauben.
6. Pro Gerät genau eine Instanz starten. Beenden mit **Strg+C**.

Falls Codex hier bereits einen Empfänger im Hintergrund gestartet hat, vor dem
Doppelklick auf eine neue Startdatei `Hintergrund_Empfaenger_Stoppen.cmd` ausführen.

Falls macOS die Dateien nach dem Entpacken nicht als ausführbar erkennt, im Terminal
im entpackten Ordner ausführen:

```sh
chmod +x *.command
./Installieren_macOS.command
./Sender_macOS.command
```

Falls ein Mehrkanal-Interface den Mikrofoneingang beispielsweise auf Kanal 2 hat:

```sh
.venv/bin/python audio_sender.py --device 3 --input-channel 2
```

Die Device-ID `3` ist hier nur ein Beispiel. Auflisten mit:

```sh
.venv/bin/python audio_sender.py --list-devices
```

Windows-Ausgänge auflisten: `python audio_receiver.py --list-devices`.
Bevorzugt die passende **Windows WASAPI**-Variante verwenden. Die Software erlaubt
auch einen 44,1-kHz-Sender an einem Windows-Ausgang mit 48-kHz-Systemformat.
Die Software ändert Lautstärke und Stummschaltung des Betriebssystems nicht.

## Rauschen und Brummen gezielt unterscheiden

**Wenn Sprache fehlt oder verzerrt klingt: `Mikrofontest_macOS.command` auf dem Mac
starten.** Den tatsächlich benutzten Eingang wählen, acht Sekunden sprechen und
danach einen Ausgang zur lokalen Wiedergabe auswählen. Das umgeht Netzwerk und
Empfänger vollständig. Ist schon diese Aufnahme gestört, zunächst Mikrofonquelle,
Eingangskanal und Audioanschluss am Mac korrigieren. Die Aufnahme und Messwerte
liegen danach unter `diagnostics/mikrofon_lokal.wav` und `mikrofon_lokal.json`.

Wenn die Aufnahme lokal klar ist, mit `Testton_macOS.command` die Übertragung und
den Empfänger prüfen. So lassen sich Aufnahme- und Ausgabefehler getrennt testen.

`Empfaenger_Original.cmd` überträgt ungefiltert und ist für Musik und Referenztests
geeignet. `Empfaenger_Sprache.cmd` senkt tiefe Störungen sanft ab und verwendet eine
einzelne schmale 50-Hz-Sperre. Die früheren Sperren für Oberwellen bis 8 kHz sind
entfernt: Sie haben auch Stimmanteile verändert. Ein Noise-Gate ist standardmäßig
aus, damit leise Sprache erhalten bleibt. Nur bei ausdrücklicher Auswahl von
`--gate-db -55` wird es aktiviert. Es gibt keine automatische Verstärkung, die
Hintergrundrauschen hochzieht. Diese schonende Filterung kann stark gestörte
Aufnahmen nicht vollständig von Brummen oder Rauschen trennen.

**Zur Fehlersuche am Mac zunächst den Mikrofon-Sender beenden und
`Testton_macOS.command` starten.** Der Testton entsteht digital und umgeht den
Mikrofoneingang. Ist der Ton sauber, aber das Mikrofon brummt, liegt die verbleibende
Störung im Aufnahmeweg. Ist auch der Testton gestört, den Empfänger-Ausgang und die
analoge Verbindung zur Anlage prüfen. Ein Test über Kopfhörer direkt am PC hilft,
PC-Ausgabe und nachgeschaltete Verkabelung zu unterscheiden.

Die bisherigen Messungen mit Switch zeigten starke 50-Hz-Anteile bereits in den
empfangenen PCM-Daten. Ein Netzwerkpuffer repariert solche aufgenommenen Störungen
nicht. Dafür können eine andere Mikrofonquelle, das korrekte Interface, passender
Eingangspegel oder eine Korrektur der analogen Verkabelung erforderlich sein.

Bei mehrkanaligen Ausgängen prüfen, ob beide identischen Stereokanäle zur Verkabelung
passen. Zum Test nur links ausgeben: `python audio_receiver.py --channel left`.

## Verhalten und Anzeigen

- Sender: 48 kHz, Mono, explizit PCM 16 Bit little endian, 10-ms-Pakete.
- Protokoll 2: neue Sitzungskennung bei jedem Start, Sequenznummern und CRC32 über
  Header und Nutzdaten. Beschädigte Pakete werden verworfen. Keine Verschlüsselung.
- Empfänger versteht zusätzlich das alte AUD0-Protokoll des bisherigen Senders.
- 120 ms Netzwerkpuffer, begrenzt statt dauerhaft wachsender Verzögerung.
- Sanftes Aus-/Einblenden an Lücken und erneutes Puffern nach Unterbrechungen.
- Kleine Unterschiede der Audiotakte werden durch langsame Interpolation
  ausgeglichen. Die Gesamtlatenz enthält zusätzlich die Audiogeräte-Puffer.
- Sender-Neustarts und Formatwechsel werden automatisch erkannt.
- Keine Netzwerkarbeit, Filter oder Konsolenausgabe im Aufnahme-Callback.
- Exklusive Bindung verhindert parallele Empfänger am gleichen Port unter Windows.

Am Sender **Aufnahmeüberläufe**, **Verworfen**, **Netzwerkfehler** und **Clipping**
beobachten. Der Spitzenpegel beim Sprechen sollte grob -12 bis -6 dBFS erreichen.
Clipping am Eingang lässt sich am Empfänger nicht zurücknehmen.

Am Empfänger sollten **Fehlend** und **Unterläufe** bei einer stabilen LAN-Verbindung
bei null bleiben. **Neustarts** zählt neue Sendersitzungen. Bei längerem Ausfall
wird Stille ausgegeben und auf neue Pakete gewartet. **Puffer** zählt Netzwerkpakete,
nicht die zusätzliche Latenz der Soundkarte.

Puffer bei Bedarf ändern: `python audio_receiver.py --buffer-ms 200`.
Kein QoS, Multicast, Router oder Internetzugang ist für die Audioübertragung nötig.

## Reproduzierbare Tests

Ausgabetest mit digital erzeugtem Ton über einen eigenen lokalen Testport:
`python verify_audio.py --device 8`. Dabei werden echte UDP-Sockets und das
ausgewählte Audiogerät verwendet. Analysiert werden die an PortAudio geschriebenen
Samples; Lautsprecher, Stummschaltung und externe Verkabelung sind damit akustisch
noch nicht vermessen. Der Test hinterlässt WAV- und JSON-Dateien unter `diagnostics`.

```sh
python -m unittest test_audio_system test_audio_filters -v
```

Der Integrationstest startet Sender und Empfänger als getrennte Prozesse über
echtes UDP auf Loopback. Eine bekannte WAV wird bitgenau mit der empfangenen WAV
verglichen. Weitere Tests prüfen Paketfehler, Reihenfolge, Verluste, Neustarts,
Pufferbegrenzung, Taktkorrektur und Brummfilter. Loopback ersetzt keinen Hörtest
der Mikrofon- und Anlagenverkabelung und keinen Lauf des neuen Senders unter macOS.

Empfang mit dem angeschlossenen Sender für 30 Sekunden messen:

```sh
python audio_receiver.py --device 8 --profile speech --duration 30 --stats-json diagnostics/test.json
```

Device-ID `8` gilt nur, solange die Gerätezuordnung auf diesem Windows-PC gleich
bleibt. `--duration` enthält auch die Wartezeit auf den Sender.

Mit `--record diagnostics/original.wav` werden akzeptierte Originalpakete vor
Filtern in Empfangsreihenfolge gesichert. Dies ist eine Diagnoseaufnahme: Lücken
werden darin nicht mit Stille aufgefüllt und bei Paketumordnung wird nicht
nachträglich sortiert. Bei Änderung der Sample-Rate wird die Aufnahme in einer
weiteren WAV fortgesetzt. Beide Dateien können Mikrofonaufnahmen enthalten.

Alte Skripte liegen nur im ursprünglichen lokalen Arbeitsordner unter
`backups/vor_neuaufbau`. Repository und verteilbares ZIP enthalten keine
Mikrofonaufnahmen, lokalen Sicherungen oder lokalen Diagnoseprotokolle.
