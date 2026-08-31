# 🏒 Scoreboard – Anleitung für den Spieltag

## Der einfachste Aufbau (empfohlen): 1 Laptop + HDMI-Kabel

Kein Netzwerk, keine IP-Adressen, nichts einzustellen.

1. **Laptop mit dem Beamer / TV per HDMI-Kabel verbinden.**
2. Windows-Taste + **P** drücken → **„Erweitern"** wählen
   (Laptop-Bild und TV-Bild sind dann getrennt).
3. Auf dem Laptop die Datei **`Scoreboard-starten.bat`** doppelklicken.
   - Ein schwarzes Fenster geht auf – **offen lassen!**
   - Nach ein paar Sekunden öffnen sich **zwei Browser-Tabs** von selbst.
4. **Tab „board"** (Großanzeige): mit der Maus auf den **TV-Bildschirm ziehen**,
   dann einmal auf **„▶ Los geht's"** klicken.
   → Geht automatisch in Vollbild und schaltet den Ton frei.
5. **Tab „control"** (Bedienfeld): bleibt auf dem Laptop – hier wird gesteuert.

**Fertig.** Am Spielende einfach das schwarze Fenster schließen.

---

## Das allererste Mal (einmalig, mit Internet)

Beim ersten Doppelklick auf **`Scoreboard-starten.bat`** richtet sich alles
selbst ein:

- fehlt Python, wird es **automatisch installiert** – dabei ggf. **einmal „Ja"**
  bei der Windows-Abfrage klicken;
- danach werden die benötigten Pakete geladen.

Das dauert ein paar Minuten und braucht **einmalig Internet**. Jeder weitere
Start geht in Sekunden und **ohne Internet**.

> Klappt die automatische Python-Installation nicht (z. B. sehr altes Windows),
> sagt das schwarze Fenster Bescheid. Dann von Hand von
> <https://www.python.org/downloads/> installieren (**Haken bei „Add Python to
> PATH"**) und die `.bat` erneut starten.

---

## Häufige Fragen

**Das schwarze Fenster meldet, dass die Python-Installation nicht geklappt hat.**
→ Einmal von Hand installieren: <https://www.python.org/downloads/>, Haken bei
„Add Python to PATH" setzen, Computer neu starten, `.bat` nochmal doppelklicken.

**Die Browser-Tabs zeigen einen Fehler / „nicht erreichbar".**
→ Kurz warten und die Seite neu laden (F5). Das schwarze Fenster muss offen sein.

**Oben im Bedienfeld steht ein roter Balken „kein Ton aktiviert".**
→ Auf der Großanzeige einmal klicken bzw. „▶ Los geht's" drücken. Der Balken
verschwindet dann von selbst.

**Kein Ton bei Tor / Strafe.**
→ Gleiche Ursache: einmal auf die Großanzeige klicken. Und Lautstärke am
TV/Beamer prüfen.

**Die Großanzeige ist nicht im Vollbild.**
→ Auf die Anzeige klicken (Start-Knopf) oder Taste **F11** drücken.

**Bedienfeld auf einem zweiten Gerät (Tablet/zweiter Laptop) statt am selben Laptop:**
→ Beide Geräte ins **gleiche WLAN**. Im schwarzen Fenster steht die Adresse;
auf dem zweiten Gerät im Browser `http://<IP-des-Laptops>:8000/control` öffnen.
Die IP zeigt Windows unter *Einstellungen → Netzwerk → WLAN → Eigenschaften*
(„IPv4-Adresse", z. B. `192.168.1.42`). Nur im eigenen, vertrauenswürdigen
Netz benutzen – nicht ins offene Internet stellen.

**Nach einem Absturz / Neustart:** einfach die `.bat` wieder starten. Spielstand,
Uhr und Strafen werden automatisch wiederhergestellt; die Uhr steht dann pausiert.
