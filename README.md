# 🏒 Street Hockey Scoreboard System

Ein vollständiges, offline-fähiges Scoreboard-System mit FastAPI, WebSockets und reinen HTML5/CSS3/JS-Frontends.

## 🚀 Schnellstart

### 1. Abhängigkeiten installieren
```bash
pip install -r requirements.txt
```
*(Oder direkt: `pip install fastapi "uvicorn[standard]" websockets python-multipart`)*

### 2. Server starten
Im Projektordner ausführen:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Aufrufen im Browser
* **Bedienfeld (Laptop / Zeitnehmer):** [http://localhost:8000/control](http://localhost:8000/control)
* **Beamer-Anzeige (Großbildschirm):** [http://localhost:8000/board](http://localhost:8000/board)
* **Übersicht / Startseite:** [http://localhost:8000](http://localhost:8000)

---

## ⌨️ Tastatur-Shortcuts im Bedienfeld (`/control`)
* **Leertaste (`Space`):** Spielzeit Start / Pause
* **H:** Tor Heim (Torschützen-Dialog)
* **A:** Tor Gast (Torschützen-Dialog)
* **1 / 2 / 3:** Drittel setzen

---

## ✨ Features
1. **Zwei-Bildschirm-Prinzip:**
   - `/control`: Übersichtliche Steuerung mit Schnellzugriff, Zeitkorrektur (+/- 10s, +/- 1m), Strafzeiten-Management und Hotkeys.
   - `/board`: High-Contrast Fullscreen-Scoreboard für Beamer oder TV ohne Scrollbalken oder störende Buttons. Die Torzahlen folgen der eingestellten **Textfarbe** des Teams; die Kästchen um die Zahlen und um die Spielzeit bekommen einen leichten Glow in der jeweiligen **Teamfarbe**.
2. **Echtzeit-Synchronisation:**
   - Alle Aktionen werden ohne Verzögerung via WebSockets an alle verbundenen Bildschirme übertragen.
3. **Präziser Backend-Timer:**
   - Die Spielzeit und Strafzeiten laufen serverseitig über `asyncio` – kein Drift durch Browser-Drosselung oder Tab-Wechsel.
4. **Strafzeiten (Penalties):**
   - Über einen Dialog: Spieler aus dem Kader wählen (nach Nummer sortiert) und Strafzeit frei einstellen (Presets 2/5/10 min). Läuft synchron zur Spielzeit herunter, max. 2 aktiv pro Team (Rest gestapelt), nach Ablauf automatisch weg.
4a. **Ligafunktionen:**
   - **Timeout** je Team (1×/Spiel, 60 s) mit Vollbild-Anzeige auf `/board`.
   - **Penaltyschießen**-Modus mit Treffer/Fehlschuss je Team und Sequenzanzeige.
   - **„Ohne Torwart"**-Umschalter je Team (Empty Net) – Badge auf `/board`, Empty-Net-Hinweis im Tor-Overlay.
   - **Spielzeit exakt setzen** (mm:ss) und **„Neues Spiel"** (Spielstand zurücksetzen, Teams bleiben).
   - **Schüsse** (Shots on Goal) per Schalter in „Vorbereitung" ein-/ausblendbar (Standard: aus), wirkt auf Bedienfeld und Großanzeige.
5. **Tor-Overlay & Sponsoren-Slideshow:**
   - 6-Sekunden-Vollbild-Tor-Animation im „Arena"-Stil, komplett aus den Teamfarben aufgebaut: weißer Impact-Blitz, schräge Lichtstreifen, ein einschlagendes Schräg-Panel mit „GOAL!" (Fill-Wipe von links), konzentrische Tunnel-Ringe, Buchstaben auf einzelnen Farb-Latten und als Abschluss eine „Logo · GOAL!"-Marquee-Wand: volle Reihen, jede Reihe läuft gegenläufig zur Reihe darüber. Kontrast-Tinte (schwarz/weiß) wird je nach Teamfarbe automatisch gewählt.
   - Auf der Bühne stehen nur „GOAL!" und der **Torschützenname** (auf einem eigenen Schräg-Panel im selben Stil, wischt von links ein, skaliert mit dem Viewport und bricht bei langen Namen um) – kein Teamlogo, kein Teamname.
   - **Drittelpause** und **Auszeit** teilen sich dieselbe Bildsprache: gedämpft driftende Lichtstreifen und ein schräges, kursives Titel-Panel. Die Auszeit ist mit der Farbe des Teams eingefärbt, das sie genommen hat.
   - In der Drittelpause läuft eine Sponsoren-Slideshow auf `/board`; im Kopfbereich werden zusätzlich beide Teamlogos mit Name und Spielstand angezeigt. Sponsorenlogos bekommen einen sehr dezenten, weichen Schein, damit auch dunkle Logos (schwarze Schriftzüge o. Ä.) nicht im dunklen Hintergrund verschwinden – gilt für die Pausen-Slideshow und den Sponsor-Slot im Unterband.
   - Die `/board`-Anzeige ist **komplett stumm** – keine Hupe, kein Horn, keine Töne.
6. **Persistenter Spielstand:**
   - Der komplette Spielzustand (Score, Uhr, Strafzeiten, Tore) wird laufend nach `data/game_state.json` geschrieben und beim Serverstart wiederhergestellt. Die Uhr startet nach einem Neustart pausiert.

---

## 🔒 Betrieb & Sicherheit

* **Kein Login:** Jeder im selben Netzwerk kann `/control` bedienen. Das System ist für den Betrieb in einem **vertrauenswürdigen lokalen Netz** (z. B. eigener Router/Hotspot an der Bande) gedacht – nicht ins offene Internet stellen.
* **Uploads:** Nur Bilddateien (PNG/JPG/GIF/WEBP/SVG) bis 5 MB werden angenommen; SVGs mit aktiven Inhalten (Skripten/Event-Handlern) werden abgelehnt.
* **Laufzeitdaten:** `data/` und `uploads/` werden zur Laufzeit angelegt und sind per `.gitignore` vom Repo ausgenommen.
