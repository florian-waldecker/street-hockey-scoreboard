# 🏒 Street Hockey Scoreboard System

Ein vollständiges, offline-fähiges Scoreboard-System mit FastAPI, WebSockets und reinen HTML5/CSS3/JS-Frontends.

## 🚀 Schnellstart

### 1. Abhängigkeiten installieren
```bash
pip install -r requirements.txt
```
*(Oder direkt: `pip install fastapi "uvicorn[standard]" websockets`)*

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
* **H:** Tor Heim (+1)
* **A:** Tor Gast (+1)
* **B:** Hupe / Buzzer auslösen
* **R:** Spieluhr zurücksetzen (auf Drittelzeit)

---

## ✨ Features
1. **Zwei-Bildschirm-Prinzip:**
   - `/control`: Übersichtliche Steuerung mit Schnellzugriff, Zeitkorrektur (+/- 10s, +/- 1m), Strafzeiten-Management und Hotkeys.
   - `/board`: High-Contrast Fullscreen-Scoreboard für Beamer oder TV ohne Scrollbalken oder störende Buttons.
2. **Echtzeit-Synchronisation:**
   - Alle Aktionen werden ohne Verzögerung via WebSockets an alle verbundenen Bildschirme übertragen.
3. **Präziser Backend-Timer:**
   - Die Spielzeit und Strafzeiten laufen serverseitig über `asyncio` – kein Drift durch Browser-Drosselung oder Tab-Wechsel.
4. **Strafzeiten (Penalties):**
   - 2-Minuten-Strafen mit Spielernummern, die synchron zur Spielzeit herunterzählen und nach Ablauf automatisch verschwinden.
5. **Integrierte Sound-Synthese:**
   - Echte Nebelhorn-/Buzzer-Sounds über die Web Audio API – 100% offline ohne Audio-Dateien oder CDNs.
