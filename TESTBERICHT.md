# Prüfstand: 16. Oktober 2026

Nach der Sprachkorrektur: **19 automatische Tests bestanden**.

## Software und Übertragung

- Automatische Tests: Protokoll einschließlich CRC und Altformat, Paketumordnung,
  Sequenzüberlauf, Paketlücken mit weichem Übergang, Neu-Puffern, begrenzter Speicher,
  Sender-Neustarts, atomarer Formatwechsel, exklusiver UDP-Port, Audiokanäle,
  Filterkontinuität und Nutzsignalerhalt. Nach der Sprachkorrektur sind zusätzlich
  typische Stimmtonhöhen von 100 bis 250 Hz und sehr leise Sprache getestet.
- Taktkorrektur: zwei Minuten virtuelle Echtzeit mit 500 ppm schnellerem Senderquarz;
  keine fehlenden Pakete und kein Pufferüberlauf.
- Zwei echte Prozesse auf Loopback: 200 UDP-Pakete mit einer bekannten WAV;
  empfangene PCM-Daten bitgenau identisch, keine ungültigen Pakete.
- Neuer Sender mit 1-kHz-Testton und echter Realtek-/WASAPI-Ausgabe:
  keine fehlenden oder ungültigen Pakete, keine Audio-Unterläufe.
  Störleistung außerhalb des Tonbereichs in den an PortAudio geschriebenen Daten:
  etwa **-63 dB relativ zum Testton**. Das ist eine digitale Messung vor dem
  analogen Ausgang, keine akustische Vermessung der Lautsprecher.

## Vorhandene Verbindung zum Mac

Der neue Empfänger wurde mit dem noch laufenden alten Sender auf
192.168.10.2 geprüft. Format: 44,1 kHz, 441 Frames, AUD0/Version 1.
Die Wiedergabe läuft ohne fehlende Pakete und ohne Audio-Unterläufe.
Während der ersten Initialisierung werden alte Startpakete bewusst verworfen,
damit die Verzögerung nicht dauerhaft anwächst. Das wird getrennt als
`startup_discarded` gezählt.

Im Originalsignal ist starkes 50-Hz-Brummen mit Oberwellen messbar.
Die erste, aggressive Filterversion senkte im aufgenommenen Testmaterial:

- die gemessenen Brummbänder bis 8 kHz um etwa **48 dB**;
- den gesamten Pegel des überwiegend gestörten Signals um etwa **23 dB**.

**Diese Filterversion hat den Hörtest nicht bestanden:** Der Benutzer meldete
fehlende oder verzerrte Sprache. Ein zusätzlicher Test zeigte bis zu 7 dB Verlust
bei sprachähnlichen Signalen. Die obigen Rauschwerte sind daher kein Qualitätsbeleg
für verständliche Sprachübertragung und beschreiben nicht den aktuellen Filter.

Der aktuelle Filter ist deutlich schonender: Hochpass bei 65 Hz und nur eine
schmale Sperre bei der Netzgrundfrequenz. Kein Gate im Standardbetrieb, kein
Kammfilter und keine doppelte Filterung. Typische Stimmtonhöhen bleiben in den
automatischen Tests innerhalb von 1 dB erhalten; auch sehr leise Stimme wird nicht
ausgeblendet. Der erneute Hörtest mit tatsächlicher Sprache ist noch offen.

Das analoge Eingangssignal kann dadurch nicht vollständig rekonstruiert werden.

Eine weitere 40-Sekunden-Messung nach der Sprachkorrektur lief mit 3.818
Wiedergabeblöcken, ohne Paketlücken und ohne Audio-Unterläufe. Im unveränderten
Originalsignal lagen rund 88 Prozent der Energie zwischen 45 und 55 Hz.
Die erneute lokale Mikrofonprüfung am Mac steht aus; dafür enthält das Paket
`Mikrofontest_macOS.command`, das ohne Netzwerk aufnimmt und lokal wiedergibt.

## Noch am Mac erforderlich

Das neue Senderprogramm wurde lokal mit Testsignal und UDP geprüft. Es wurde
noch nicht auf dem Mac installiert oder mit dessen CoreAudio-/Mikrofonhardware
ausgeführt. Dafür das Paket auf den Mac kopieren, installieren und den richtigen
Mikrofoneingang auswählen. Mit `Testton_macOS.command` lässt sich anschließend die
gesamte physische Strecke mit einem sauberen digitalen Signal prüfen.

Ein vollständiger Hörtest hängt außerdem von Windows-Lautstärke, gewähltem
Ausgang, Kabeln und angeschlossener Anlage ab. Die Software prüft und zählt
Netzwerk- und Gerätefehler; aufgenommenes Brummen kann weiterhin eine Änderung
am Mikrofon- oder analogen Anschluss erfordern.

Messprotokolle und Audioaufnahmen liegen lokal unter `diagnostics` und werden
nicht in das verteilbare ZIP aufgenommen.
