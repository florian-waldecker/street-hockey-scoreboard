
        const MAX_PLAYERS = 40;
        let ws;
        let currentState = {};
        let savedTeams = [];
        let pendingGoalTeam = null;
        let pendingPenaltyTeam = null;

        // ---------- helpers ----------
        // escapeHtml, safeUploadUrl, formatTime live in /static/common.js

        // Roster parsing: pull the jersey number out of entries like "10 Müller" / "#10 Max"
        function parseJerseyNumber(p) {
            const m = String(p).match(/\d+/);
            return m ? parseInt(m[0], 10) : null;
        }
        function splitPlayer(p) {
            const s = String(p).trim();
            const m = s.match(/^#?\s*(\d+)\s*[-.)]?\s*(.*)$/);
            if (m) return { num: parseInt(m[1], 10), name: m[2].trim() };
            return { num: parseJerseyNumber(s), name: s };
        }
        function sortRoster(list) {
            return [...list].sort((a, b) => {
                const na = parseJerseyNumber(a), nb = parseJerseyNumber(b);
                if (na === null && nb === null) return String(a).localeCompare(String(b), "de");
                if (na === null) return 1;
                if (nb === null) return -1;
                if (na !== nb) return na - nb;
                return String(a).localeCompare(String(b), "de");
            });
        }

        // Normalise free text ("7 Meier, 9 Krüger" or one per line) into "<nr> <name>" strings.
        function parseRosterText(text) {
            return String(text || "")
                .split(/[\n,;]+/)
                .map(s => s.trim())
                .filter(Boolean)
                .map(s => {
                    const { num, name } = splitPlayer(s);
                    if (num === null) return name || s;
                    return name ? `${num} ${name}` : String(num);
                });
        }

        // .txt files from Windows Notepad/Excel are often Windows-1252, not UTF-8.
        function decodeTextFile(buf) {
            const bytes = new Uint8Array(buf);
            let text = new TextDecoder("utf-8", { fatal: false }).decode(bytes);
            if (text.includes("�")) {
                try { text = new TextDecoder("windows-1252").decode(bytes); } catch (e) {}
            }
            return text;
        }

        // Growing roster list + bulk import. Returns { getPlayers, setPlayers, clear }.
        function createRosterEditor(mount) {
            let players = [];
            mount.classList.add("roster-editor");
            mount.innerHTML = `
                <div class="roster-add-row">
                    <input type="text" class="re-num" inputmode="numeric" maxlength="3" placeholder="Nr.">
                    <input type="text" class="re-name" maxlength="40" placeholder="Spielername">
                    <button type="button" class="btn btn-primary re-add" style="padding: 0.42rem 0.7rem;">+ Hinzufügen</button>
                </div>
                <div class="roster-list"></div>
                <div class="roster-foot">
                    <span class="re-count"></span>
                    <button type="button" class="btn re-sort" style="padding: 2px 8px; font-size: 0.75rem;">nach Nr. sortieren</button>
                    <span class="roster-warn re-warn" hidden></span>
                </div>
                <details class="roster-import">
                    <summary>Mehrere importieren (einf&uuml;gen oder .txt-Datei)</summary>
                    <textarea class="re-bulk input-text" placeholder="7 Meier, 9 Kr&uuml;ger, 10 Sch&auml;fer &hellip;"></textarea>
                    <input type="file" class="re-file" accept=".txt,text/plain" style="font-size: 0.78rem;">
                    <label style="font-size: 0.8rem; color: var(--text-dim);">
                        <input type="checkbox" class="re-replace" checked style="width: auto;"> Vorhandene Liste ersetzen
                    </label>
                    <div class="roster-foot"><span class="re-preview"></span></div>
                    <button type="button" class="btn re-apply" style="padding: 0.35rem 0.8rem;">&Uuml;bernehmen</button>
                </details>`;

            const listEl = mount.querySelector(".roster-list");
            const numEl = mount.querySelector(".re-num");
            const nameEl = mount.querySelector(".re-name");
            const countEl = mount.querySelector(".re-count");
            const warnEl = mount.querySelector(".re-warn");
            const bulkEl = mount.querySelector(".re-bulk");
            const fileEl = mount.querySelector(".re-file");
            const previewEl = mount.querySelector(".re-preview");

            function syncFromDom() {
                players = [...listEl.querySelectorAll(".roster-row")].map(row => {
                    const n = row.querySelector(".rr-num").value.trim();
                    const nm = row.querySelector(".rr-name").value.trim();
                    return (n ? n + " " : "") + nm;
                }).map(s => s.trim()).filter(Boolean);
            }

            function refreshMeta() {
                const rows = [...listEl.querySelectorAll(".roster-row")];
                const nums = rows.map(r => parseInt(r.querySelector(".rr-num").value, 10)).filter(n => !isNaN(n));
                const dupes = [...new Set(nums.filter((n, i) => nums.indexOf(n) !== i))];
                countEl.innerText = `${rows.length} / ${MAX_PLAYERS} Spieler`;
                const warns = [];
                if (rows.length > MAX_PLAYERS) warns.push(`Server kürzt auf ${MAX_PLAYERS}`);
                if (dupes.length) warns.push(`doppelte Nr.: ${dupes.join(", ")}`);
                warnEl.hidden = warns.length === 0;
                warnEl.textContent = warns.join("  ·  ");
                rows.forEach(r => {
                    const n = parseInt(r.querySelector(".rr-num").value, 10);
                    r.querySelector(".rr-num").classList.toggle("dupe", !isNaN(n) && dupes.includes(n));
                });
            }

            function renderList() {
                listEl.innerHTML = players.map(p => {
                    const { num, name } = splitPlayer(p);
                    return `<div class="roster-row">
                        <input class="rr-num" inputmode="numeric" maxlength="3" value="${escapeHtml(num === null ? "" : String(num))}">
                        <input class="rr-name" maxlength="40" value="${escapeHtml(name || p)}">
                        <button type="button" class="item-del rr-del">&times;</button>
                    </div>`;
                }).join("");
                refreshMeta();
            }

            function addFromInputs() {
                const n = numEl.value.trim();
                const nm = nameEl.value.trim();
                if (!n && !nm) return;
                syncFromDom();
                players.push(((n ? n + " " : "") + nm).trim());
                renderList();
                numEl.value = "";
                nameEl.value = "";
                numEl.focus();
            }

            mount.querySelector(".re-add").addEventListener("click", addFromInputs);
            nameEl.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); addFromInputs(); } });
            numEl.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); nameEl.focus(); } });

            mount.querySelector(".re-sort").addEventListener("click", () => {
                syncFromDom();
                players = sortRoster(players);
                renderList();
            });

            listEl.addEventListener("input", refreshMeta);
            listEl.addEventListener("click", e => {
                if (!e.target.classList.contains("rr-del")) return;
                e.target.closest(".roster-row").remove();
                syncFromDom();
                refreshMeta();
            });

            bulkEl.addEventListener("input", () => {
                const c = parseRosterText(bulkEl.value).length;
                previewEl.innerText = c ? `${c} Spieler erkannt` : "";
            });
            fileEl.addEventListener("change", async () => {
                const f = fileEl.files[0];
                if (!f) return;
                bulkEl.value = decodeTextFile(await f.arrayBuffer());
                bulkEl.dispatchEvent(new Event("input"));
                fileEl.value = "";
            });
            mount.querySelector(".re-apply").addEventListener("click", () => {
                const parsed = parseRosterText(bulkEl.value);
                if (!parsed.length) return;
                syncFromDom();
                players = mount.querySelector(".re-replace").checked ? parsed : players.concat(parsed);
                renderList();
                bulkEl.value = "";
                previewEl.innerText = "";
                mount.querySelector(".roster-import").open = false;
            });

            renderList();

            return {
                getPlayers() { addFromInputs(); syncFromDom(); return players.slice(); },
                setPlayers(arr) { players = (arr || []).map(String).map(s => s.trim()).filter(Boolean); renderList(); },
                clear() { players = []; renderList(); bulkEl.value = ""; previewEl.innerText = ""; }
            };
        }

        // WEBSOCKET
        function connectWS() {
            const loc = window.location;
            const wsProtocol = loc.protocol === "https:" ? "wss:" : "ws:";
            const wsUrl = `${wsProtocol}//${loc.host}/ws`;

            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                document.getElementById("statusDot").classList.add("online");
                document.getElementById("statusText").innerText = "Verbunden";
            };

            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                if (msg.type === "STATE_UPDATE") {
                    currentState = msg.state;
                    renderUI(msg.state);
                } else if (msg.type === "SPONSORS_UPDATE") {
                    fetchSponsors();
                } else if (msg.type === "AUDIO_STATUS") {
                    renderAudioBanner(msg);
                }
            };

            ws.onclose = () => {
                document.getElementById("statusDot").classList.remove("online");
                document.getElementById("statusText").innerText = "Getrennt (Reconnecting...)";
                setTimeout(connectWS, 1500);
            };
        }

        function sendCmd(action, data = {}) {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ action, ...data }));
            }
        }

        function renderAudioBanner(s) {
            const banner = document.getElementById("audioBanner");
            if (!banner) return;
            const boards = s.boards || 0;
            const ready = s.boards_audio_ready || 0;
            // Show only when at least one connected board still has audio locked.
            const show = boards > 0 && ready < boards;
            banner.hidden = !show;
            if (show) {
                const missing = boards - ready;
                document.getElementById("audioBannerText").innerText =
                    boards === 1
                        ? "Auf der Großanzeige ist noch kein Ton aktiviert"
                        : `${missing} von ${boards} Anzeigen haben noch keinen Ton aktiviert`;
            }
        }

        function setBreakDuration(minutes) {
            const m = Math.max(1, Math.min(60, parseInt(minutes, 10) || 5));
            sendCmd('BREAK_SET_DURATION', { duration: m * 60 });
        }

        function setOvertimeDuration(minutes) {
            const m = Math.max(1, Math.min(60, parseInt(minutes, 10) || 5));
            sendCmd('OVERTIME_DURATION_SET', { duration: m * 60 });
        }

        // ---- Strafen-Sound ----
        let penaltySoundSeconds = "";

        function onPenaltySoundPicked() {
            const input = document.getElementById("penaltySoundFile");
            const hint = document.getElementById("penaltySoundHint");
            const saveBtn = document.getElementById("penaltySoundSaveBtn");
            penaltySoundSeconds = "";
            saveBtn.disabled = true;
            const file = input.files[0];
            if (!file) { hint.textContent = ""; return; }
            const probe = new Audio();
            probe.preload = "metadata";
            probe.onloadedmetadata = () => {
                const dur = probe.duration || 0;
                URL.revokeObjectURL(probe.src);
                if (!isFinite(dur) || dur <= 0) {
                    hint.style.color = "#f87171";
                    hint.textContent = "Dauer konnte nicht gelesen werden – andere Datei versuchen.";
                    input.value = ""; return;
                }
                if (dur > 20.5) {
                    hint.style.color = "#f87171";
                    hint.textContent = `Zu lang: ${dur.toFixed(1)} s (max. 20 s).`;
                    input.value = ""; return;
                }
                penaltySoundSeconds = dur.toFixed(2);
                hint.style.color = "var(--text-dim)";
                hint.textContent = `Bereit: ${file.name} (${dur.toFixed(1)} s) – auf „Hochladen" klicken.`;
                saveBtn.disabled = false;
            };
            probe.onerror = () => {
                hint.style.color = "#f87171";
                hint.textContent = "Audiodatei kann nicht gelesen werden.";
                input.value = "";
            };
            probe.src = URL.createObjectURL(file);
        }

        async function uploadPenaltySound() {
            const file = document.getElementById("penaltySoundFile").files[0];
            if (!file) return;
            const fd = new FormData();
            fd.append("file", file);
            fd.append("audio_seconds", penaltySoundSeconds || "");
            try {
                const res = await fetch("/api/penalty-sound", { method: "POST", body: fd });
                if (!res.ok) {
                    let msg = "Upload fehlgeschlagen";
                    try { msg = (await res.json()).detail || msg; } catch (e) {}
                    alert(msg); return;
                }
                document.getElementById("penaltySoundFile").value = "";
                document.getElementById("penaltySoundSaveBtn").disabled = true;
                const hint = document.getElementById("penaltySoundHint");
                hint.style.color = "var(--text-dim)";
                hint.textContent = "Strafen-Sound gespeichert.";
            } catch (e) {
                alert("Upload fehlgeschlagen");
            }
        }

        async function deletePenaltySound() {
            if (!confirm("Strafen-Sound entfernen?")) return;
            try { await fetch("/api/penalty-sound", { method: "DELETE" }); } catch (e) {}
        }

        function setPenaltySoundLead(seconds) {
            const s = Math.max(0, Math.min(30, parseInt(seconds, 10) || 0));
            sendCmd("PENALTY_SOUND_SET", { lead_seconds: s });
        }

        function setTimeoutDuration(seconds) {
            const s = Math.max(5, Math.min(600, parseInt(seconds, 10) || 60));
            sendCmd('TIMEOUT_SET_DURATION', { seconds: s });
        }

        // Team colours: paint the strip above the tile + the score in the team's colour
        function isValidCssColor(c) {
            return typeof c === "string" && /^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(c.trim());
        }
        function applyTeamAccent(side, color) {
            const fallback = side === "home" ? "#ef4444" : "#00d2ff";
            const c = isValidCssColor(color) ? color.trim() : fallback;
            const panel = document.getElementById(side + "Panel");
            if (panel) panel.style.borderTopColor = c;
            const score = document.getElementById(side + "Score");
            if (score) score.style.color = c;
        }

        // UI RENDER
        function renderUI(state) {
            // Clock & Period
            document.getElementById("clockDisplay").innerText = formatTime(state.time_remaining);
            document.getElementById("periodBadge").innerText =
                state.period === "OT" ? "OVERTIME" : `Drittel ${state.period}`;

            const toggleBtn = document.getElementById("toggleBtn");
            if (state.timer_running) {
                toggleBtn.innerText = "⏸ PAUSE (Space)";
                toggleBtn.classList.remove("btn-primary");
                toggleBtn.classList.add("btn-danger");
            } else {
                toggleBtn.innerText = "▶ START (Space)";
                toggleBtn.classList.remove("btn-danger");
                toggleBtn.classList.add("btn-primary");
            }

            // Break Mode
            const breakBanner = document.getElementById("breakBanner");
            const breakToggleBtn = document.getElementById("breakToggleBtn");
            document.getElementById("breakClockDisplay").innerText = formatTime(state.break_time_remaining || 0);
            const breakDurInput = document.getElementById("breakDurationInput");
            if (breakDurInput && document.activeElement !== breakDurInput) {
                breakDurInput.value = Math.round((state.break_duration || 300) / 60);
            }

            if (state.break_mode) {
                breakBanner.classList.add("active");
                breakToggleBtn.innerText = state.break_timer_running ? "⏸ Pause stoppen" : "▶ Pause fortsetzen";
            } else {
                breakBanner.classList.remove("active");
                breakToggleBtn.innerText = "▶ Pause Start";
            }

            // Home Team
            if (document.activeElement !== document.getElementById("homeNameInput")) {
                document.getElementById("homeNameInput").value = state.home_name;
            }
            document.getElementById("homeScore").innerText = state.home_score;

            const homeLogo = document.getElementById("homeLogoPreview");
            if (state.home_logo) {
                homeLogo.src = state.home_logo;
                homeLogo.classList.add("has-logo");
            } else {
                homeLogo.classList.remove("has-logo");
            }

            // Away Team
            if (document.activeElement !== document.getElementById("awayNameInput")) {
                document.getElementById("awayNameInput").value = state.away_name;
            }
            document.getElementById("awayScore").innerText = state.away_score;

            const awayLogo = document.getElementById("awayLogoPreview");
            if (state.away_logo) {
                awayLogo.src = state.away_logo;
                awayLogo.classList.add("has-logo");
            } else {
                awayLogo.classList.remove("has-logo");
            }

            // Team colours on the tiles
            applyTeamAccent("home", state.home_color);
            applyTeamAccent("away", state.away_color);

            // Goalie (empty-net) toggles
            setGoalieBtn("home", state.home_goalie);
            setGoalieBtn("away", state.away_goalie);

            // Shots on goal - only shown when enabled
            const showShots = state.show_shots === true;
            document.getElementById("homeShotsBox").hidden = !showShots;
            document.getElementById("awayShotsBox").hidden = !showShots;
            if (showShots) {
                document.getElementById("homeShots").innerText = state.home_shots;
                document.getElementById("awayShots").innerText = state.away_shots;
            }
            const shotsCheck = document.getElementById("showShotsCheck");
            if (shotsCheck && document.activeElement !== shotsCheck) shotsCheck.checked = showShots;

            // Overtime duration (Vorbereitung)
            const otDur = state.overtime_duration || 300;
            const otDurInput = document.getElementById("overtimeDurationInput");
            if (otDurInput && document.activeElement !== otDurInput) otDurInput.value = Math.round(otDur / 60);
            const otDurCur = document.getElementById("overtimeDurationCurrent");
            if (otDurCur) otDurCur.innerText = "aktuell: " + formatTime(otDur);

            // Team time-out duration (Vorbereitung)
            const toDur = state.timeout_duration || 60;
            const toDurInput = document.getElementById("timeoutDurationInput");
            if (toDurInput && document.activeElement !== toDurInput) toDurInput.value = toDur;
            const toDurCur = document.getElementById("timeoutDurationCurrent");
            if (toDurCur) toDurCur.innerText = "aktuell: " + formatTime(toDur);

            // Penalty-expiry sound (Vorbereitung)
            const psHas = !!state.penalty_sound_url;
            const psTestBtn = document.getElementById("penaltySoundTestBtn");
            const psRemoveBtn = document.getElementById("penaltySoundRemoveBtn");
            if (psTestBtn) psTestBtn.hidden = !psHas;
            if (psRemoveBtn) psRemoveBtn.hidden = !psHas;
            const psLead = state.penalty_sound_lead_seconds || 0;
            const psLeadInput = document.getElementById("penaltySoundLeadInput");
            if (psLeadInput && document.activeElement !== psLeadInput) psLeadInput.value = psLead;
            const psLeadCur = document.getElementById("penaltySoundLeadCurrent");
            if (psLeadCur) {
                psLeadCur.textContent = psHas
                    ? (psLead === 0 ? "aktiv: bei Ablauf" : `aktiv: ${psLead} s vor Ablauf`)
                    : "kein Sound hinterlegt";
            }

            // Team time-out
            renderTimeout(state);

            // Shoot-out
            renderShootout(state);

            // Penalties
            renderPenalties("home", state.home_penalties);
            renderPenalties("away", state.away_penalties);

            // Goals
            renderGoalsList("home", state.home_goals || []);
            renderGoalsList("away", state.away_goals || []);

            // Aktuelle Aufstellung - Button-Zähler
            const hRb = document.getElementById("editHomeRosterBtn");
            const aRb = document.getElementById("editAwayRosterBtn");
            if (hRb) hRb.innerText = `Heim-Kader bearbeiten (${(state.home_players || []).length})`;
            if (aRb) aRb.innerText = `Gast-Kader bearbeiten (${(state.away_players || []).length})`;
        }

        function setGoalieBtn(team, val) {
            const on = val !== false;
            const b = document.getElementById(team + "GoalieBtn");
            if (!b) return;
            b.classList.toggle("off", !on);
            b.innerText = on ? "🥅 Torwart: AN" : "🚫 Ohne Torwart";
        }

        function renderTimeout(state) {
            const active = !!state.timeout_active;
            const banner = document.getElementById("timeoutBanner");
            banner.classList.toggle("active", active);
            if (active) {
                const tName = state.timeout_team === "home" ? state.home_name : state.away_name;
                document.getElementById("timeoutBannerTeam").innerText = tName || "";
                document.getElementById("timeoutBannerClock").innerText = formatTime(state.timeout_time_remaining || 0);
            }
            const hUsed = (state.home_timeouts_used || 0) >= 1;
            const aUsed = (state.away_timeouts_used || 0) >= 1;
            const hb = document.getElementById("timeoutHomeBtn");
            const ab = document.getElementById("timeoutAwayBtn");
            hb.disabled = active || hUsed;
            ab.disabled = active || aUsed;
            hb.innerText = hUsed ? "Timeout Heim ✓" : "Timeout Heim";
            ab.innerText = aUsed ? "Timeout Gast ✓" : "Timeout Gast";
        }

        function renderShootout(state) {
            const active = !!state.shootout_active;
            const h = state.home_shootout || [];
            const a = state.away_shootout || [];
            document.getElementById("shootoutControls").hidden = !active;
            // During a shoot-out the break / time-out controls are irrelevant - hide them for room.
            document.getElementById("breakBox").hidden = active;
            document.getElementById("timeoutBox").hidden = active;
            const btn = document.getElementById("shootoutToggleBtn");
            btn.innerText = active ? "Penaltyschießen beenden" : "Penaltyschießen starten";
            btn.classList.toggle("btn-danger", active);
            const hGoals = h.filter(x => x.scored).length;
            const aGoals = a.filter(x => x.scored).length;
            document.getElementById("shootoutTally").innerText = `${hGoals} : ${aGoals}`;

            const seq = document.getElementById("shootoutSequence");
            const rows = Math.max(h.length, a.length);
            if (rows === 0) {
                seq.innerHTML = '<span style="color: var(--text-dim); font-size: 0.8rem;">Noch keine Schüsse</span>';
                return;
            }
            let out = "";
            for (let i = 0; i < rows; i++) {
                const hs = h[i] ? (h[i].scored ? "✅" : "❌") : "·";
                const as = a[i] ? (a[i].scored ? "✅" : "❌") : "·";
                out += `<div class="item-row" style="border-left-color: var(--accent-purple);">` +
                       `<span>#${i + 1}</span><span>Heim ${hs} &nbsp; Gast ${as}</span></div>`;
            }
            seq.innerHTML = out;
        }

        function renderPenalties(team, list) {
            const container = document.getElementById(`${team}PenaltyList`);
            if (!list || list.length === 0) {
                container.innerHTML = '<span style="color: var(--text-dim); font-size: 0.8rem;">Keine Strafen</span>';
                return;
            }
            container.innerHTML = list.map((p, idx) => `
                <div class="item-row">
                    <span><strong>#${escapeHtml(p.player)}</strong> (${formatTime(p.remaining_seconds)})</span>
                    <button class="item-del" onclick="sendCmd('PENALTY_REMOVE', {team: '${team}', index: ${idx}})">✕</button>
                </div>
            `).join('');
        }

        function renderGoalsList(team, list) {
            const container = document.getElementById(`${team}GoalsList`);
            if (!list || list.length === 0) {
                container.innerHTML = '<span style="color: var(--text-dim); font-size: 0.8rem;">Keine Tore</span>';
                return;
            }
            container.innerHTML = list.map((g, idx) => `
                <div class="item-row" style="border-left-color: var(--accent-green);">
                    <span><strong>${escapeHtml(g.time)}</strong> (D${escapeHtml(g.period)}): ${escapeHtml(g.player)}</span>
                    <button class="item-del" onclick="sendCmd('GOAL_REMOVE', {team: '${team}', index: ${idx}})">✕</button>
                </div>
            `).join('');
        }

        // ================= PENALTY MODAL (player + duration) =================
        function penaltyDurationSeconds() {
            const m = Math.max(0, Math.min(99, parseInt(document.getElementById("penaltyMinInput").value, 10) || 0));
            const s = Math.max(0, Math.min(59, parseInt(document.getElementById("penaltySecInput").value, 10) || 0));
            return m * 60 + s;
        }

        function setPenaltyDuration(totalSeconds) {
            document.getElementById("penaltyMinInput").value = Math.floor(totalSeconds / 60);
            document.getElementById("penaltySecInput").value = totalSeconds % 60;
        }

        function openPenaltyModal(team, seconds) {
            pendingPenaltyTeam = team;
            const teamName = team === "home" ? currentState.home_name : currentState.away_name;
            const players = team === "home" ? (currentState.home_players || []) : (currentState.away_players || []);

            setPenaltyDuration(seconds && seconds > 0 ? seconds : 120);

            document.getElementById("penaltyModalTitle").innerText = `⏱️ Strafe für ${teamName}`;
            document.getElementById("manualPenaltyInput").value = "";

            const box = document.getElementById("penaltyRosterButtons");
            box.innerHTML = "";
            if (players.length > 0) {
                sortRoster(players).forEach(p => {
                    const { num, name } = splitPlayer(p);
                    const b = document.createElement("button");
                    b.type = "button";
                    b.className = "scorer-row";
                    b.innerHTML =
                        `<span class="scorer-num${num === null ? " no-num" : ""}">${num === null ? "–" : escapeHtml(String(num))}</span>` +
                        `<span>${escapeHtml(name || p)}</span>`;
                    b.addEventListener("click", () => submitPenalty(p));
                    box.appendChild(b);
                });
            } else {
                box.innerHTML = '<span style="color: var(--text-dim); font-size: 0.85rem;">Kein Kader hinterlegt. Spieler manuell eingeben:</span>';
            }

            document.getElementById("penaltyModal").classList.add("active");
            setTimeout(() => {
                const t = document.getElementById("manualPenaltyInput");
                t.focus();
                if (t.select) t.select();
            }, 100);
        }

        function submitPenalty(playerText) {
            const seconds = penaltyDurationSeconds();
            if (!seconds) {
                alert("Bitte eine Strafzeit größer als 0 eingeben.");
                return;
            }
            sendCmd("PENALTY_ADD", { team: pendingPenaltyTeam, player: playerText || "00", seconds });
            closePenaltyModal();
        }

        function confirmPenalty() {
            const manual = document.getElementById("manualPenaltyInput").value.trim();
            submitPenalty(manual || "00");
        }

        function closePenaltyModal() {
            document.getElementById("penaltyModal").classList.remove("active");
            pendingPenaltyTeam = null;
        }

        // ================= GOALIE / TIMEOUT / SHOOTOUT / CLOCK / RESET =================
        function closeModal(id) {
            document.getElementById(id).classList.remove("active");
        }

        function toggleGoalie(team) {
            const cur = team === "home" ? currentState.home_goalie : currentState.away_goalie;
            sendCmd("GOALIE_SET", { team, active: cur === false });
        }

        function openTimeSetModal() {
            const rem = currentState.time_remaining || 0;
            document.getElementById("timeSetMin").value = Math.floor(rem / 60);
            document.getElementById("timeSetSec").value = rem % 60;
            document.getElementById("timeSetModal").classList.add("active");
            setTimeout(() => {
                const el = document.getElementById("timeSetMin");
                el.focus();
                if (el.select) el.select();
            }, 100);
        }

        function confirmTimeSet() {
            const m = Math.max(0, Math.min(99, parseInt(document.getElementById("timeSetMin").value, 10) || 0));
            const s = Math.max(0, Math.min(59, parseInt(document.getElementById("timeSetSec").value, 10) || 0));
            sendCmd("TIMER_SET_REMAINING", { seconds: m * 60 + s });
            closeModal("timeSetModal");
        }

        function newGame() {
            if (!confirm("Spielstand, Uhr, Strafen, Tore, Timeouts und Penaltyschießen zurücksetzen?\nTeams, Kader und Sponsoren bleiben erhalten.")) return;
            sendCmd("GAME_RESET");
        }

        function requestTimeout(team) {
            if (currentState.timeout_active) return;
            const used = team === "home" ? (currentState.home_timeouts_used || 0) : (currentState.away_timeouts_used || 0);
            if (used >= 1) {
                alert("Dieses Team hat sein Timeout in diesem Spiel bereits genommen.");
                return;
            }
            sendCmd("TIMEOUT_START", { team });
        }

        function toggleShootout() {
            sendCmd("SHOOTOUT_MODE_SET", { active: !currentState.shootout_active });
        }

        function updateTeamDetails(team) {
            const name = document.getElementById(`${team}NameInput`).value.trim();
            sendCmd("TEAM_SET", {
                team,
                name: name || (team === "home" ? "HEIM" : "GAST")
            });
        }

        // ================= GOAL SCORER MODAL =================
        function openScorerModal(team, delta) {
            if (delta < 0) {
                sendCmd("SCORE_ADJUST", { team, delta: -1 });
                return;
            }
            pendingGoalTeam = team;
            const teamName = team === "home" ? currentState.home_name : currentState.away_name;
            const players = team === "home" ? (currentState.home_players || []) : (currentState.away_players || []);

            document.getElementById("scorerModalTitle").innerText = `🏒 Tor für ${teamName}`;
            document.getElementById("manualScorerInput").value = "";

            const rosterBox = document.getElementById("scorerRosterButtons");
            rosterBox.innerHTML = "";
            if (players.length > 0) {
                sortRoster(players).forEach(p => {
                    const { num, name } = splitPlayer(p);
                    const b = document.createElement("button");
                    b.type = "button";
                    b.className = "scorer-row";
                    b.innerHTML =
                        `<span class="scorer-num${num === null ? " no-num" : ""}">${num === null ? "–" : escapeHtml(String(num))}</span>` +
                        `<span>${escapeHtml(name || p)}</span>`;
                    b.addEventListener("click", () => selectScorerAndSubmit(p));
                    rosterBox.appendChild(b);
                });
            } else {
                rosterBox.innerHTML = '<span style="color: var(--text-dim); font-size: 0.85rem;">Kein Kader hinterlegt. Spieler manuell eingeben:</span>';
            }

            document.getElementById("scorerModal").classList.add("active");
            setTimeout(() => document.getElementById("manualScorerInput").focus(), 100);
        }

        function selectScorerAndSubmit(scorerText) {
            sendCmd("SCORE_ADJUST", { team: pendingGoalTeam, delta: 1, scorer: scorerText });
            closeScorerModal();
        }

        function confirmGoalScorer() {
            const manual = document.getElementById("manualScorerInput").value.trim();
            sendCmd("SCORE_ADJUST", { team: pendingGoalTeam, delta: 1, scorer: manual || "Tor" });
            closeScorerModal();
        }

        function closeScorerModal() {
            document.getElementById("scorerModal").classList.remove("active");
            pendingGoalTeam = null;
        }

        // ================= TEAMS PRESETS & API =================
        async function fetchTeams() {
            try {
                const res = await fetch("/api/teams");
                savedTeams = await res.json();
                renderTeamSelects();
                renderSavedTeamsFullList();
            } catch (e) {
                console.error("Error fetching teams:", e);
            }
        }

        function renderTeamSelects() {
            const homeSel = document.getElementById("homeTeamSelect");
            const awaySel = document.getElementById("awayTeamSelect");
            let opts = '<option value="">-- Team-Vorlage wählen --</option>';
            savedTeams.forEach(t => {
                opts += `<option value="${escapeHtml(t.id)}">${escapeHtml(t.name)}</option>`;
            });
            homeSel.innerHTML = opts;
            awaySel.innerHTML = opts;
        }

        function loadTeamPreset(targetSide, teamId) {
            if (!teamId) return;
            const t = savedTeams.find(item => item.id === teamId);
            if (!t) return;

            sendCmd("TEAM_SET", {
                team: targetSide,
                name: t.name,
                logo: t.logo_url || "",
                logo_border_mode: t.logo_border_mode || "none",
                logo_border_width: (t.logo_border_width ?? 4),
                logo_border_color: t.logo_border_color || "",
                color: t.color || (targetSide === 'home' ? '#ef4444' : '#00d2ff'),
                text_color: t.text_color || '#ffffff',
                anthem: t.anthem_url || "",
                players: t.players || []
            });
        }

        async function handleSaveTeam(e) {
            e.preventDefault();
            const id = document.getElementById("formTeamId").value;
            const name = document.getElementById("formTeamName").value.trim();
            const color = document.getElementById("formTeamColor").value;
            const textColor = document.getElementById("formTeamTextColor").value;
            const logoFile = document.getElementById("formTeamLogo").files[0];

            const borderMode = document.getElementById("formLogoBorderMode").value;
            const borderWidth = document.getElementById("formLogoBorderWidth").value || "0";
            const borderUsesTeamColor = document.getElementById("formLogoBorderTeamColor").checked;
            const borderColor = borderUsesTeamColor ? "" : document.getElementById("formLogoBorderColor").value;

            const playersArr = formRoster.getPlayers();

            const formData = new FormData();
            if (id) formData.append("id", id);
            formData.append("name", name);
            formData.append("color", color);
            formData.append("text_color", textColor);
            formData.append("logo_border_mode", borderMode);
            formData.append("logo_border_width", borderWidth);
            formData.append("logo_border_color", borderColor);
            formData.append("players_json", JSON.stringify(playersArr));
            if (logoFile) formData.append("logo_file", logoFile);

            const anthemFile = document.getElementById("formTeamAnthem").files[0];
            if (anthemFile) {
                formData.append("anthem_file", anthemFile);
                formData.append("anthem_seconds", document.getElementById("formAnthemSeconds").value || "");
            }
            if (document.getElementById("formAnthemRemove").value === "1") {
                formData.append("remove_anthem", "1");
            }

            try {
                const res = await fetch("/api/teams", { method: "POST", body: formData });
                if (!res.ok) {
                    let msg = "Fehler beim Speichern des Teams";
                    try { msg = (await res.json()).detail || msg; } catch (e) {}
                    alert(msg);
                    return;
                }
                resetTeamForm();
                await fetchTeams();
            } catch (err) {
                alert("Fehler beim Speichern des Teams");
            }
        }

        // ---- Torhymne: pick / validate (<= 40 s) / preview ----
        let formAnthemPreviewEl = null;
        let formAnthemExistingUrl = "";

        function stopAnthemPreview() {
            if (formAnthemPreviewEl) {
                formAnthemPreviewEl.pause();
                formAnthemPreviewEl = null;
            }
            const btn = document.getElementById("formAnthemPreviewBtn");
            if (btn) btn.innerText = "▶ Anhören";
        }

        function onAnthemFilePicked() {
            const input = document.getElementById("formTeamAnthem");
            const hint = document.getElementById("formAnthemHint");
            const previewBtn = document.getElementById("formAnthemPreviewBtn");
            const seconds = document.getElementById("formAnthemSeconds");
            stopAnthemPreview();
            seconds.value = "";
            const file = input.files[0];
            if (!file) { previewBtn.hidden = !formAnthemExistingUrl; return; }

            document.getElementById("formAnthemRemove").value = "";
            const probe = new Audio();
            probe.preload = "metadata";
            probe.onloadedmetadata = () => {
                const dur = probe.duration || 0;
                URL.revokeObjectURL(probe.src);
                if (!isFinite(dur) || dur <= 0) {
                    hint.textContent = "Dauer konnte nicht gelesen werden – andere Datei versuchen.";
                    input.value = ""; previewBtn.hidden = !formAnthemExistingUrl; return;
                }
                if (dur > 40.5) {
                    hint.style.color = "#f87171";
                    hint.textContent = `Zu lang: ${dur.toFixed(1)} s (max. 40 s). Bitte kürzere Datei wählen.`;
                    input.value = ""; previewBtn.hidden = !formAnthemExistingUrl; return;
                }
                hint.style.color = "var(--text-dim)";
                hint.textContent = `Neue Torhymne: ${file.name} (${dur.toFixed(1)} s)`;
                seconds.value = dur.toFixed(2);
                previewBtn.hidden = false;
            };
            probe.onerror = () => {
                hint.style.color = "#f87171";
                hint.textContent = "Audiodatei kann nicht gelesen werden.";
                input.value = ""; previewBtn.hidden = !formAnthemExistingUrl;
            };
            probe.src = URL.createObjectURL(file);
        }

        function toggleAnthemPreview() {
            const btn = document.getElementById("formAnthemPreviewBtn");
            if (formAnthemPreviewEl) { stopAnthemPreview(); return; }
            const file = document.getElementById("formTeamAnthem").files[0];
            const src = file ? URL.createObjectURL(file) : safeUploadUrl(formAnthemExistingUrl);
            if (!src) return;
            formAnthemPreviewEl = new Audio(src);
            formAnthemPreviewEl.onended = stopAnthemPreview;
            formAnthemPreviewEl.play().then(() => { btn.innerText = "⏹ Stop"; }).catch(() => stopAnthemPreview());
        }

        function markAnthemForRemoval() {
            stopAnthemPreview();
            formAnthemExistingUrl = "";
            document.getElementById("formTeamAnthem").value = "";
            document.getElementById("formAnthemSeconds").value = "";
            document.getElementById("formAnthemRemove").value = "1";
            document.getElementById("formAnthemPreviewBtn").hidden = true;
            document.getElementById("formAnthemRemoveBtn").hidden = true;
            const hint = document.getElementById("formAnthemHint");
            hint.style.color = "var(--text-dim)";
            hint.textContent = "Torhymne wird beim Speichern entfernt.";
        }

        function resetTeamForm() {
            document.getElementById("formTeamId").value = "";
            document.getElementById("formTeamName").value = "";
            document.getElementById("formTeamColor").value = "#ef4444";
            document.getElementById("formTeamTextColor").value = "#ffffff";
            document.getElementById("formTeamLogo").value = "";
            document.getElementById("formLogoBorderMode").value = "none";
            document.getElementById("formLogoBorderWidth").value = "4";
            document.getElementById("formLogoBorderColor").value = "#ffffff";
            document.getElementById("formLogoBorderTeamColor").checked = true;
            formRoster.clear();
            document.getElementById("formLogoPreview").hidden = true;
            document.getElementById("teamEditHint").hidden = true;
            document.getElementById("teamSaveBtn").innerText = "💾 Team speichern";
            stopAnthemPreview();
            formAnthemExistingUrl = "";
            document.getElementById("formTeamAnthem").value = "";
            document.getElementById("formAnthemSeconds").value = "";
            document.getElementById("formAnthemRemove").value = "";
            document.getElementById("formAnthemPreviewBtn").hidden = true;
            document.getElementById("formAnthemRemoveBtn").hidden = true;
            document.getElementById("formAnthemHint").textContent = "";
        }

        function editTeam(id) {
            const t = savedTeams.find(x => x.id === id);
            if (!t) return;
            document.getElementById("formTeamId").value = t.id;
            document.getElementById("formTeamName").value = t.name || "";
            document.getElementById("formTeamColor").value = t.color || "#ef4444";
            document.getElementById("formTeamTextColor").value = t.text_color || "#ffffff";
            document.getElementById("formTeamLogo").value = "";
            document.getElementById("formLogoBorderMode").value = t.logo_border_mode || "none";
            document.getElementById("formLogoBorderWidth").value = (t.logo_border_width ?? 4);
            const tBorderCol = t.logo_border_color || "";
            document.getElementById("formLogoBorderTeamColor").checked = !tBorderCol;
            document.getElementById("formLogoBorderColor").value = tBorderCol || t.color || "#ffffff";
            formRoster.setPlayers(t.players || []);
            const prev = document.getElementById("formLogoPreview");
            const url = safeUploadUrl(t.logo_url);
            if (url) { prev.src = url; prev.hidden = false; } else { prev.hidden = true; }
            document.getElementById("teamEditHint").hidden = !url;

            // Torhymne
            stopAnthemPreview();
            document.getElementById("formTeamAnthem").value = "";
            document.getElementById("formAnthemSeconds").value = "";
            document.getElementById("formAnthemRemove").value = "";
            formAnthemExistingUrl = safeUploadUrl(t.anthem_url);
            const anthemHint = document.getElementById("formAnthemHint");
            anthemHint.style.color = "var(--text-dim)";
            anthemHint.textContent = formAnthemExistingUrl
                ? "Torhymne vorhanden – neue Datei ersetzt sie."
                : "Keine Torhymne hinterlegt.";
            document.getElementById("formAnthemPreviewBtn").hidden = !formAnthemExistingUrl;
            document.getElementById("formAnthemRemoveBtn").hidden = !formAnthemExistingUrl;

            document.getElementById("teamSaveBtn").innerText = "💾 Änderungen speichern";
            closeAllTeamsModal();
            document.getElementById("teamUploadForm").scrollIntoView({ behavior: "smooth", block: "center" });
        }

        function openAllTeamsModal() {
            renderSavedTeamsFullList();
            document.getElementById("allTeamsModal").classList.add("active");
        }
        function closeAllTeamsModal() {
            document.getElementById("allTeamsModal").classList.remove("active");
        }

        function renderSavedTeamsFullList() {
            const container = document.getElementById("savedTeamsFullList");
            if (!savedTeams || savedTeams.length === 0) {
                container.innerHTML = '<span style="color: var(--text-dim);">Noch keine Teams gespeichert.</span>';
                return;
            }
            container.innerHTML = savedTeams.map(t => {
                const id = escapeHtml(t.id);
                const logo = escapeHtml(safeUploadUrl(t.logo_url));
                return `
                <div style="display: flex; justify-content: space-between; align-items: center; background: var(--card-bg); padding: 0.6rem 0.9rem; border-radius: 8px; border: 1px solid var(--border);">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        ${logo ? `<img src="${logo}" style="width: 32px; height: 32px; object-fit: contain;">` : ''}
                        <div>
                            <strong>${escapeHtml(t.name)}</strong>
                            <div style="font-size: 0.75rem; color: var(--text-dim);">${(t.players || []).length} Spieler im Kader${t.anthem_url ? ' · 🎵 Torhymne' : ''}</div>
                        </div>
                    </div>
                    <div style="display: flex; gap: 0.4rem;">
                        <button class="btn btn-primary" style="padding: 4px 8px; font-size: 0.75rem;" onclick="loadTeamPreset('home', '${id}'); closeAllTeamsModal();">Als Heim</button>
                        <button class="btn btn-info" style="padding: 4px 8px; font-size: 0.75rem;" onclick="loadTeamPreset('away', '${id}'); closeAllTeamsModal();">Als Gast</button>
                        <button class="btn" style="padding: 4px 8px; font-size: 0.75rem;" onclick="editTeam('${id}')">✏️</button>
                        <button class="btn btn-danger" style="padding: 4px 8px; font-size: 0.75rem;" onclick="deleteTeam('${id}')">🗑</button>
                    </div>
                </div>`;
            }).join('');
        }

        async function deleteTeam(id) {
            if (!confirm("Team wirklich löschen?")) return;
            await fetch(`/api/teams/${id}`, { method: "DELETE" });
            await fetchTeams();
        }

        // ================= AKTUELLE AUFSTELLUNG (live roster) =================
        let rosterModalSide = null;
        function openRosterModal(side) {
            rosterModalSide = side;
            const nm = side === "home" ? (currentState.home_name || "Heim") : (currentState.away_name || "Gast");
            document.getElementById("rosterModalTitle").innerText = `🧍 Kader – ${nm}`;
            modalRoster.setPlayers((side === "home" ? currentState.home_players : currentState.away_players) || []);
            document.getElementById("rosterModal").classList.add("active");
        }
        function applyRosterModal() {
            if (!rosterModalSide) return;
            sendCmd("TEAM_SET", { team: rosterModalSide, players: modalRoster.getPlayers() });
            closeModal("rosterModal");
            rosterModalSide = null;
        }

        // ================= SPONSORS API =================
        async function fetchSponsors() {
            try {
                const res = await fetch("/api/sponsors");
                const sponsors = await res.json();
                document.getElementById("sponsorCount").innerText = `${sponsors.length} Sponsoren`;
                const list = document.getElementById("sponsorsList");
                if (sponsors.length === 0) {
                    list.innerHTML = '<span style="color: var(--text-dim); font-size: 0.8rem;">Keine Logos hochgeladen</span>';
                    return;
                }
                list.innerHTML = sponsors.map(s => `
                    <div class="sponsor-item">
                        <img src="${escapeHtml(safeUploadUrl(s.url))}" alt="${escapeHtml(s.name || '')}">
                        <button class="sponsor-del" onclick="deleteSponsor('${escapeHtml(s.id)}')">✕</button>
                    </div>
                `).join('');
            } catch (e) {
                console.error("Error fetching sponsors:", e);
            }
        }

        async function handleUploadSponsor(e) {
            e.preventDefault();
            const fileInput = document.getElementById("sponsorFileInput");
            if (!fileInput.files[0]) return;

            const formData = new FormData();
            formData.append("file", fileInput.files[0]);

            await fetch("/api/sponsors", { method: "POST", body: formData });
            fileInput.value = "";
            await fetchSponsors();
        }

        async function deleteSponsor(id) {
            await fetch(`/api/sponsors/${id}`, { method: "DELETE" });
            await fetchSponsors();
        }

        // ================= TAB NAVIGATION =================
        function switchTab(name) {
            document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            const panel = document.getElementById("tab-" + name);
            const btn = document.getElementById("tabBtn-" + name);
            if (!panel || !btn) { return switchTab("live"); }
            panel.classList.add("active");
            btn.classList.add("active");
            document.body.classList.toggle("fit-live", name === "live");
            try { localStorage.setItem("controlTab", name); } catch (e) {}
        }

        // KEYBOARD SHORTCUTS
        window.addEventListener("keydown", (e) => {
            if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;

            if (e.code === "Space") {
                e.preventDefault();
                sendCmd("TIMER_TOGGLE");
            } else if (e.key === "h" || e.key === "H") {
                openScorerModal("home", 1);
            } else if (e.key === "a" || e.key === "A") {
                openScorerModal("away", 1);
            } else if (["1", "2", "3"].includes(e.key)) {
                sendCmd("PERIOD_SET", { period: e.key });
            }
        });

        // INIT
        const formRoster = createRosterEditor(document.getElementById("formRosterEditor"));
        const modalRoster = createRosterEditor(document.getElementById("rosterModalEditor"));

        let initialTab = "live";
        try { initialTab = localStorage.getItem("controlTab") || "live"; } catch (e) {}
        switchTab(initialTab);

        connectWS();
        fetchTeams();
        fetchSponsors();
    