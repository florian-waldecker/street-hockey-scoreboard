# Sicherheitsmodell

Das Scoreboard ist für **ein vertrauenswürdiges lokales Netz** gebaut – der
Laptop an der Bande, per HDMI am TV, optional ein Tablet im selben WLAN als
zweites Bedienpult. Nicht mehr, nicht weniger.

## Bewusste Design-Entscheidungen

| Thema | Entscheidung | Begründung |
|---|---|---|
| **Kein Login** | Jeder, der `/control` erreicht, kann steuern. | Am Spieltag muss es ohne Passwort-Hickhack laufen. Der Schutz ist das Netz, nicht die App. |
| **Kein CSRF-Schutz** | REST-Endpunkte prüfen keinen Token. | Gleiches Modell – im vertrauenswürdigen LAN kein realistischer Angreifer. |
| **WebSocket ohne Auth** | `/ws` nimmt Kommandos von jedem Client an. | s. o. |
| **Audiolängen-Prüfung** | Client meldet die Dauer (`anthem_seconds` / `audio_seconds`); der Server glaubt ihr. | Bequemlichkeit. Die **Byte-Obergrenze** (`MAX_AUDIO_BYTES`, 8 MB) ist der echte, nicht umgehbare Riegel. |
| **SVG-Prüfung** | Substring-Blockliste (`<script`, `onload=` …) statt echtem Parser. | Defence-in-depth neben dem HTML-Escaping der Frontends. Reicht für den Einsatzzweck; ein bösartiges SVG käme ohnehin nur von jemandem mit Netzzugang. |

## Was **nicht** passieren darf

- **Den Server ins offene Internet stellen** (Portfreigabe, öffentliche
  Cloud-VM, Tunnel wie ngrok). Ohne Auth ist das eine offene Fernsteuerung
  samt Datei-Upload.
- Das `uploads/`-Verzeichnis als allgemeinen Dateispeicher missbrauchen.

## Was die App trotzdem tut

- Uploads: nur erlaubte Bild-/Audio-Endungen, Größenlimit, SVG-Blockliste,
  Dateinamen werden über `sanitise_id()` / feste Namen entschärft (kein
  Path-Traversal).
- Alle vom Nutzer kommenden Texte laufen durch `clean_text()` (Winkelklammern
  und Steuerzeichen raus) und werden im Frontend zusätzlich HTML-escaped.
- Response-Header: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- `data/` und `uploads/` liegen außerhalb der Versionskontrolle.

## Eine Lücke gefunden?

Bitte privat an den Repo-Inhaber melden (Kontakt: Git-Commit-Historie),
nicht als öffentliches Issue.
