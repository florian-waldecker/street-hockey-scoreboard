
        (function () {
            const ov = document.getElementById("startOverlay");
            if (!ov) return;
            function hide() { ov.style.display = "none"; }
            function start() {
                try {
                    const el = document.documentElement;
                    if (!document.fullscreenElement && el.requestFullscreen) el.requestFullscreen().catch(() => {});
                } catch (e) {}
                if (typeof enableBoardSound === "function") enableBoardSound();
                hide();
            }
            ov.addEventListener("click", start);
            document.addEventListener("keydown", start, { once: true });
            document.addEventListener("fullscreenchange", () => { if (document.fullscreenElement) hide(); });
            // Already fullscreen (Kiosk-Modus)? Dann nicht im Weg stehen.
            if (document.fullscreenElement ||
                (window.innerHeight >= (screen.height - 2) && window.innerWidth >= (screen.width - 2))) {
                hide();
            }
        })();
    

        let ws;
        let sponsorsList = [];
        let sponsorIndex = 0;
        let sponsorInterval = null;
        let goalTimeout = null;

        // ---- Audio-Freischaltung (goal anthem / penalty sound) ----
        let boardSoundEnabled = false;
        let soundToastTimer = null;

        // WICHTIG: pro Sound genau EIN wiederverwendetes <audio>-Element.
        // Niemals `new Audio()` je Wiedergabe - abgebrochene Instanzen spielen
        // sonst kurz weiter und ueberlagern sich (Klang wird "blechern").
        const goalAnthemAudio = new Audio();
        const penaltySfxAudio = new Audio();
        [goalAnthemAudio, penaltySfxAudio].forEach(a => { a.preload = "auto"; });

        function safeAudioUrl(url) {
            const u = String(url || "");
            return u.startsWith("/uploads/") ? u : "";
        }

        function playClip(audioEl, url) {
            const src = safeAudioUrl(url);
            if (!src) return;
            try {
                const abs = new URL(src, location.href).href;
                if (audioEl.src !== abs) audioEl.src = abs;   // nur bei Wechsel neu laden
                audioEl.pause();
                try { audioEl.currentTime = 0; } catch (e) {}
                audioEl.play().catch(flashSoundToast);
            } catch (e) {}
        }

        function playGoalAnthem(url)  { playClip(goalAnthemAudio, url); }
        function playPenaltySound(url) { playClip(penaltySfxAudio, url); }

        function enableBoardSound() {
            const wasEnabled = boardSoundEnabled;
            boardSoundEnabled = true;
            if (!wasEnabled) {
                // Einmal im User-Gesten-Kontext die (noch leeren) Elemente
                // anstossen, damit spaeteres play() vom Browser erlaubt wird.
                [goalAnthemAudio, penaltySfxAudio].forEach(a => {
                    if (!a.src) { try { a.play().then(() => a.pause()).catch(() => {}); } catch (e) {} }
                });
            }
            const t = document.getElementById("soundToast");
            if (t) t.hidden = true;
            if (!wasEnabled && ws && ws.readyState === WebSocket.OPEN) {
                try { ws.send(JSON.stringify({ action: "BOARD_AUDIO_READY", ready: true })); } catch (e) {}
            }
        }
        // Any interaction in this tab counts as the unlock gesture.
        ["pointerdown", "keydown", "touchstart"].forEach(evt =>
            window.addEventListener(evt, enableBoardSound, { once: true }));
        document.addEventListener("fullscreenchange", enableBoardSound, { once: true });

        function flashSoundToast() {
            const t = document.getElementById("soundToast");
            if (!t) return;
            t.hidden = false;
            if (soundToastTimer) clearTimeout(soundToastTimer);
            soundToastTimer = setTimeout(() => { t.hidden = true; }, 5000);
        }

        function escapeHtml(s) {
            return String(s == null ? "" : s).replace(/[&<>"']/g, c => (
                { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
            ));
        }

        function safeUploadUrl(url) {
            const u = String(url || "");
            return (u.startsWith("/uploads/") || u.startsWith("data:image/")) ? u : "";
        }

        function safeColor(c) {
            const v = String(c || "").trim();
            return /^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+|rgba?\([\d.,\s%]+\))$/.test(v) ? v : "";
        }

        // team-logo border / glow (set per team on the control desk). The logos are
        // transparent PNGs, so both looks are built from drop-shadow (alpha-shape
        // aware) rather than a rectangular CSS border.
        const LOGO_BASE_SHADOW = "drop-shadow(0 3px 12px rgba(0, 0, 0, 0.55))";
        function applyLogoBorder(imgEl, mode, width, color, teamColor) {
            if (!imgEl) return;
            const w = Math.max(0, Math.min(40, parseFloat(width) || 0));
            const c = safeColor(color) || safeColor(teamColor) || "#ffffff";
            if (!mode || mode === "none" || w === 0) {
                imgEl.style.filter = LOGO_BASE_SHADOW;
                return;
            }
            if (mode === "glow") {
                imgEl.style.filter =
                    `drop-shadow(0 0 ${w}px ${c}) drop-shadow(0 0 ${w * 2}px ${c}) ${LOGO_BASE_SHADOW}`;
                return;
            }
            // solid: chained hard shadows in the four directions. drop-shadow
            // filters compound (each acts on the previous result), so four steps
            // are enough to grow an even contour that also fills the corners.
            const d = Math.max(1, w).toFixed(2);
            imgEl.style.filter = [
                `${d}px 0 0 ${c}`, `-${d}px 0 0 ${c}`,
                `0 ${d}px 0 ${c}`, `0 -${d}px 0 ${c}`,
            ].map(s => `drop-shadow(${s})`).join(" ") + " " + LOGO_BASE_SHADOW;
        }

        // "20 Max Meermann" / "#20 Max Meermann" -> { num: "#20", name: "Max Meermann" }
        function splitPlayer(p) {
            const str = String(p == null ? "" : p).trim();
            const m = /^#?(\d+)[\s.]*(.*)$/.exec(str);
            if (m && m[1]) return { num: "#" + m[1], name: (m[2] || "").trim() || ("#" + m[1]) };
            return { num: "", name: str };
        }

        function connectWS() {
            const loc = window.location;
            const wsProtocol = loc.protocol === "https:" ? "wss:" : "ws:";
            const wsUrl = `${wsProtocol}//${loc.host}/ws`;
            ws = new WebSocket(wsUrl);
            ws.onopen = () => {
                // Announce this page as a board + whether audio is already unlocked,
                // so the timekeeper desk can warn when a board still can't play sound.
                try { ws.send(JSON.stringify({ action: "BOARD_HELLO", audio_ready: boardSoundEnabled })); } catch (e) {}
            };
            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                if (msg.type === "STATE_UPDATE") renderState(msg.state);
                else if (msg.type === "goal") showGoalOverlay(msg);
                else if (msg.type === "penalty_sound") playPenaltySound(msg.sound);
                else if (msg.type === "SPONSORS_UPDATE") loadSponsors();
            };
            ws.onclose = () => setTimeout(connectWS, 1500);
        }

        function formatTime(sec) {
            const m = Math.floor(sec / 60);
            const s = sec % 60;
            return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
        }

        function renderPeriodDots(s) {
            const el = document.getElementById("periodDots");
            if (!el) return;
            if (s.shootout_active) { el.innerHTML = ""; return; }
            const isOT = s.period === "OT";
            const cur = isOT ? 4 : (parseInt(s.period, 10) || 1);
            let html = "";
            for (let i = 1; i <= 3; i++) {
                const cls = i < cur ? "done" : (i === cur ? "active" : "");
                html += `<span class="sb-dot ${cls}"></span>`;
            }
            if (isOT) html += `<span class="sb-dot ot active"></span>`;
            el.innerHTML = html;
        }

        // board3: the shoot-out module - shootout_active folds the score boxes &
        // timing module away (via .is-shootout on the topbar) and shows a row of
        // markers per team: 5 to begin with, one more per attempt in sudden
        // death; green = converted, red = missed, dim = not yet taken.
        function shootoutDots(list) {
            const n = Math.max(5, Math.ceil(list.length / 5) * 5);   // always fill out to a full row of 5
            let html = "";
            for (let i = 0; i < n; i++) {
                const a = list[i];
                const cls = !a ? "" : (a.scored ? "is-goal" : "is-miss");
                html += `<span class="sb-so-dot ${cls}"></span>`;
            }
            return html;
        }

        function renderShootoutBoard(s) {
            const topbar = document.querySelector(".sb-topbar");
            const wrap = document.getElementById("shootoutBoard");
            const active = !!s.shootout_active;
            topbar.classList.toggle("is-shootout", active);
            wrap.hidden = !active;
            if (!active) return;
            const home = s.home_shootout || [];
            const away = s.away_shootout || [];
            document.getElementById("shootoutHomeScore").innerText = home.filter(a => a.scored).length;
            document.getElementById("shootoutAwayScore").innerText = away.filter(a => a.scored).length;
            document.getElementById("shootoutHomeTrack").innerHTML = shootoutDots(home);
            document.getElementById("shootoutAwayTrack").innerHTML = shootoutDots(away);
        }

        function renderState(s) {
            document.getElementById("clockDisplay").innerText = formatTime(s.time_remaining);
            if (s.shootout_active) {
                const hg = (s.home_shootout || []).filter(a => a.scored).length;
                const ag = (s.away_shootout || []).filter(a => a.scored).length;
                document.getElementById("periodDisplay").innerText = `PENALTYSCHIESSEN ${hg} : ${ag}`;
            } else {
                document.getElementById("periodDisplay").innerText = s.period === "OT" ? "OVERTIME" : `DRITTEL ${s.period}`;
            }
            renderPeriodDots(s);
            renderShootoutBoard(s);

            const showShots = s.show_shots === true;
            document.getElementById("homeStatsRow").style.display = showShots ? "flex" : "none";
            document.getElementById("awayStatsRow").style.display = showShots ? "flex" : "none";

            document.getElementById("homeEmptyNet").classList.toggle("active", s.home_goalie === false);
            document.getElementById("awayEmptyNet").classList.toggle("active", s.away_goalie === false);

            const hTO = (s.home_timeouts_used || 0) > 0;
            const aTO = (s.away_timeouts_used || 0) > 0;
            document.getElementById("homeTimeout").hidden = !hTO;
            document.getElementById("awayTimeout").hidden = !aTO;
            document.getElementById("homeTimeoutChip").classList.toggle("used", hTO);
            document.getElementById("awayTimeoutChip").classList.toggle("used", aTO);

            const toOverlay = document.getElementById("timeoutOverlay");
            if (s.timeout_active) {
                const tt = s.timeout_team === "away" ? "away" : "home";
                toOverlay.style.setProperty("--arena-color",
                    safeColor(s[tt + "_color"]) ||
                    (tt === "away" ? "var(--accent-away)" : "var(--accent-home)"));
                toOverlay.style.setProperty("--arena-ink", readableInk(safeColor(s[tt + "_color"])));
                const tTeamEl = document.getElementById("timeoutHeroTeam");
                tTeamEl.innerText = tt === "away" ? s.away_name : s.home_name;
                tTeamEl.style.color = safeColor(s[tt + "_text_color"]) || "var(--text-main)";
                document.getElementById("timeoutHeroClock").innerText = formatTime(s.timeout_time_remaining || 0);
                toOverlay.classList.add("active");
            } else {
                toOverlay.classList.remove("active");
            }

            // Home identity
            document.getElementById("homeName").innerText = s.home_name;
            document.getElementById("homeName").style.color = safeColor(s.home_text_color) || 'var(--text-main)';
            document.getElementById("homeScore").innerText = s.home_score;
            document.getElementById("homeShots").innerText = s.home_shots;
            document.getElementById("homeScore").style.color = safeColor(s.home_text_color) || 'var(--text-main)';
            document.getElementById("boardPanel").style.setProperty('--home-color', safeColor(s.home_color) || 'var(--accent-home)');
            document.getElementById("boardPanel").style.setProperty('--home-ink', readableInk(safeColor(s.home_color)));
            document.getElementById("boardPanel").style.setProperty('--home-text', safeColor(s.home_text_color) || 'var(--text-main)');
            document.querySelector(".sb-topbar").style.setProperty('--home-color', safeColor(s.home_color) || 'var(--accent-home)');

            const homeLogo = document.getElementById("homeLogo");
            if (s.home_logo) { homeLogo.src = s.home_logo; homeLogo.classList.add("has-logo"); }
            else homeLogo.classList.remove("has-logo");
            applyLogoBorder(homeLogo, s.home_logo_border_mode, s.home_logo_border_width, s.home_logo_border_color, s.home_color);

            // Away identity
            document.getElementById("awayName").innerText = s.away_name;
            document.getElementById("awayName").style.color = safeColor(s.away_text_color) || 'var(--text-main)';
            document.getElementById("awayScore").innerText = s.away_score;
            document.getElementById("awayShots").innerText = s.away_shots;
            document.getElementById("awayScore").style.color = safeColor(s.away_text_color) || 'var(--text-main)';
            document.getElementById("boardPanel").style.setProperty('--away-color', safeColor(s.away_color) || 'var(--accent-away)');
            document.getElementById("boardPanel").style.setProperty('--away-ink', readableInk(safeColor(s.away_color)));
            document.getElementById("boardPanel").style.setProperty('--away-text', safeColor(s.away_text_color) || 'var(--text-main)');
            document.querySelector(".sb-topbar").style.setProperty('--away-color', safeColor(s.away_color) || 'var(--accent-away)');

            const awayLogo = document.getElementById("awayLogo");
            if (s.away_logo) { awayLogo.src = s.away_logo; awayLogo.classList.add("has-logo"); }
            else awayLogo.classList.remove("has-logo");
            applyLogoBorder(awayLogo, s.away_logo_border_mode, s.away_logo_border_width, s.away_logo_border_color, s.away_color);

            renderTeamEvents("home", s.home_goals || []);
            renderTeamEvents("away", s.away_goals || []);
            renderPenaltyZone("home", s.home_penalties || []);
            renderPenaltyZone("away", s.away_penalties || []);

            const breakView = document.getElementById("breakView");
            if (s.break_mode) {
                if (!breakView.classList.contains("active")) loadSponsors();
                breakView.classList.add("active");
                document.getElementById("breakClockDisplay").innerText = formatTime(s.break_time_remaining || 0);
                renderBreakTeam("home", s);
                renderBreakTeam("away", s);
                startSponsorSlideshow();
            } else {
                breakView.classList.remove("active");
                stopSponsorSlideshow();
            }
        }

        function renderBreakTeam(side, s) {
            const cap = side.charAt(0).toUpperCase() + side.slice(1);
            const fallback = side === "home" ? "HEIM" : "GAST";
            document.getElementById("break" + cap + "Name").innerText = s[side + "_name"] || fallback;
            const scoreEl = document.getElementById("break" + cap + "Score");
            scoreEl.innerText = s[side + "_score"];
            scoreEl.style.color = safeColor(s[side + "_color"]) ||
                (side === "home" ? "var(--accent-home)" : "var(--accent-away)");
            const logo = document.getElementById("break" + cap + "Logo");
            const src = s[side + "_logo"];
            if (src) { logo.src = src; logo.hidden = false; }
            else { logo.hidden = true; logo.removeAttribute("src"); }
        }

        // ================= LIST CARDS =================
        const MAX_GOAL_ROWS = 24;      // full scrollback carried by the ticker
        const MAX_PEN_PILLS = 12;      // board3: per zone, hero chips + up to this many queued-penalty pills
        const GOAL_START_HOLD_MS = 3000; // initial dwell before the ticker starts stepping
        const GOAL_STEP_HOLD_MS  = 3000; // dwell on each page of scorers
        const GOAL_STEP_ROWS     = 3;    // scorers to advance per step
        const GOAL_RETURN_PX_PER_MS = 1.8; // speed of the quick roll back to the top

        function renderTeamEvents(side, goals) {
            const gs = [...goals].reverse().slice(0, MAX_GOAL_ROWS).map(g => {
                const sp = splitPlayer(g.player);
                return { time: String(g.time || ""), num: sp.num, name: sp.name };
            });
            renderRows(side + "Goal", gs);
        }

        // board3: one penalty zone per team (away mirrored via CSS). The zone's
        // up-to-two RUNNING penalties render as full hero chips; the stacked
        // rest trail as number pills. MAX_CONCURRENT_PENALTIES on the server is
        // 2, so array index < 2 == running, index >= 2 == still stacked.
        function collectPenalties(list) {
            return (list || []).map((p, i) => {
                const sp = splitPlayer(p.player);
                const rem = Math.max(0, parseInt(p.remaining_seconds, 10) || 0);
                const init = Math.max(rem, parseInt(p.initial, 10) || rem || 1);
                return {
                    num: sp.num || "#?",
                    name: sp.name,
                    rem,
                    pct: Math.max(0, Math.min(100, rem / init * 100)),
                    queued: i >= 2,
                };
            });
        }

        function renderPenaltyZone(side, list) {
            const feed = document.getElementById(side + "PenaltyFeed");
            if (!feed) return;

            const all = collectPenalties(list)
                .sort((a, b) => (a.queued - b.queued) || (a.rem - b.rem));

            if (all.length === 0) {
                feed.innerHTML = `<div class="sb-pen-empty">&ndash;</div>`;
                return;
            }

            const heroes = all.slice(0, 2);
            const pills = all.slice(2, 2 + MAX_PEN_PILLS);

            const heroesHtml = heroes.map(h => `
                <div class="sb-pen-hero">
                    <span class="sb-pen-hero-num">${escapeHtml(h.num)}</span>
                    <span class="sb-pen-hero-body">
                        <span class="sb-pen-hero-name">${escapeHtml(h.name)}</span>
                        <span class="sb-pen-hero-time">${formatTime(h.rem)}</span>
                    </span>
                    <span class="sb-pen-hero-bar" style="--pct:${h.pct.toFixed(1)}%"></span>
                </div>`).join("");

            const pillsHtml = pills.length
                ? `<div class="sb-pen-pills">` + pills.map(p => `
                    <span class="sb-pen-pill" style="--pct:${p.pct.toFixed(1)}%">${escapeHtml(p.num.replace(/^#/, ""))}</span>`).join("") + `</div>`
                : "";

            feed.innerHTML = heroesHtml + pillsHtml;
        }

        function rowHtml(r) {
            return `
                <div class="sb-row">
                    <span class="sb-tag">
                        <span class="sb-time">${escapeHtml(r.time)}</span>
                        ${r.num ? `<span class="sb-num">${escapeHtml(r.num)}</span>` : ``}
                    </span>
                    <span class="sb-name-txt">${escapeHtml(r.name)}</span>
                </div>`;
        }

        // goal tracks roll like a newsticker; penalty tracks render straight
        const goalTick = {};   // key -> { sig }

        function renderRows(key, rows) {
            const body = document.getElementById(key + "Track");
            if (!body) return;

            if (key.endsWith("Goal")) {
                const st = goalTick[key] || (goalTick[key] = { sig: null });
                const sig = rows.map(r => r.time + "~" + r.num + "~" + r.name).join("|");
                if (sig === st.sig) return;   // unchanged -> let the roll keep running
                st.sig = sig;
                paintGoalTicker(key, rows);
                return;
            }

            body.innerHTML = rows.length === 0
                ? `<div class="sb-row sb-row--empty">&ndash;</div>`
                : rows.map(rowHtml).join('');
        }

        function paintGoalTicker(key, rows) {
            const body = document.getElementById(key + "Track");
            if (!body) return;

            // stop any roll cycle left over from the previous render
            const st = goalTick[key] || (goalTick[key] = { sig: null });
            if (st.timer) { clearTimeout(st.timer); st.timer = null; }

            body.classList.remove("is-rolling");
            if (rows.length === 0) {
                body.innerHTML = `<div class="sb-row sb-row--empty">&ndash;</div>`;
                return;
            }
            const listHtml = rows.map(rowHtml).join('');
            body.innerHTML = `<div class="sb-ticker">${listHtml}</div>`;
            const track = body.firstElementChild;

            const reduceMotion = window.matchMedia &&
                window.matchMedia("(prefers-reduced-motion: reduce)").matches;

            const startRollIfNeeded = () => {
                if (reduceMotion) return;                       // long list just shows the top
                const viewport = body.clientHeight;
                const firstRow = track.firstElementChild;
                const rowH = firstRow ? firstRow.getBoundingClientRect().height : 0;
                if (viewport <= 0 || rowH <= 0) return;
                if (track.scrollHeight <= viewport + 2) return; // fits -> no roll

                const totalRows = rows.length;
                const visibleRows = Math.max(1, Math.floor((viewport + 2) / rowH));
                if (totalRows <= visibleRows) return;
                const maxOffset = totalRows - visibleRows;      // last page hugs the final rows

                track.classList.add("stepping");
                body.classList.add("is-rolling");

                let offset = 0;
                const step = () => {
                    if (offset >= maxOffset) {
                        // reached the end -> roll quickly back down to the top,
                        // then hold before starting the cycle over
                        const back = Math.round(offset * rowH);
                        const backMs = Math.min(1100, Math.max(350,
                            Math.round(back / GOAL_RETURN_PX_PER_MS)));
                        track.style.transition = `transform ${backMs}ms cubic-bezier(0.4, 0, 0.2, 1)`;
                        track.style.transform = "translateY(0)";
                        offset = 0;
                        st.timer = setTimeout(() => {
                            track.style.transition = "";        // back to the per-step transition
                            st.timer = setTimeout(step, GOAL_START_HOLD_MS);
                        }, backMs);
                        return;
                    }
                    offset = Math.min(offset + GOAL_STEP_ROWS, maxOffset);
                    track.style.transform = `translateY(-${Math.round(offset * rowH)}px)`;
                    st.timer = setTimeout(step, GOAL_STEP_HOLD_MS);
                };
                st.timer = setTimeout(step, GOAL_START_HOLD_MS);
            };
            requestAnimationFrame(startRollIfNeeded);
        }

        // ================= GOAL OVERLAY =================
        function readableInk(color) {
            const m = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.exec(String(color || "").trim());
            if (!m) return "#ffffff";
            let h = m[1];
            if (h.length === 3) h = h.split("").map(c => c + c).join("");
            const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
            const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
            return lum > 0.62 ? "#0b0f19" : "#ffffff";
        }

        function showGoalOverlay(data) {
            const overlay = document.getElementById("goalOverlay");
            const scorerEl = document.getElementById("goalHeroScorer");
            const tilesEl = document.getElementById("goalTiles");
            const goalColor = safeColor(data.color) ||
                (data.team === "away" ? "var(--accent-away)" : "var(--accent-home)");
            overlay.style.setProperty("--goal-color", goalColor);
            overlay.style.setProperty("--goal-ink", readableInk(safeColor(data.color)));

            const scorerBits = [];
            if (data.scorer) scorerBits.push(String(data.scorer));
            if (data.empty_net) scorerBits.push("Empty Net");
            scorerEl.innerText = scorerBits.join("  ·  ");

            const logoSrc = safeUploadUrl(data.team_logo);
            const cell = logoSrc
                ? `<span class="goal-tile"><img src="${escapeHtml(logoSrc)}" alt=""><b>GOAL!</b></span>`
                : `<span class="goal-tile"><b>GOAL!</b></span>`;
            const rowInner = cell.repeat(28);
            let rows = "";
            for (let i = 0; i < 16; i++) {
                rows += `<div class="goal-tile-row ${i % 2 ? "rtl" : "ltr"}" style="--dur:${18 + (i % 4) * 4}s">${rowInner}</div>`;
            }
            tilesEl.innerHTML = rows;

            overlay.classList.remove("active");
            void overlay.offsetWidth;
            overlay.classList.add("active");
            playGoalAnthem(data.anthem);
            if (goalTimeout) clearTimeout(goalTimeout);
            goalTimeout = setTimeout(() => overlay.classList.remove("active"), 6000);
        }

        // ================= SPONSORS =================
        async function loadSponsors() {
            try {
                const res = await fetch("/api/sponsors", { cache: "no-store" });
                sponsorsList = await res.json();
                sponsorIndex = 0;
                buildSponsorElements();
                if (document.getElementById("breakView").classList.contains("active")) {
                    stopSponsorSlideshow();
                    startSponsorSlideshow();
                }
                updateBoardSponsors();
            } catch (e) {
                console.error("Error loading sponsors:", e);
            }
        }

        let boardSponsorIndex = 0;
        let boardSponsorInterval = null;
        const BOARD_SPONSOR_MS = 7000;

        function updateBoardSponsors() {
            const slot = document.getElementById("boardSponsorSlot");
            const panel = document.getElementById("boardPanel");
            const list = sponsorsList || [];
            panel.classList.toggle("has-sponsor", list.length > 0);
            stopBoardSponsorRotation();
            if (list.length === 0) { slot.innerHTML = ""; return; }
            boardSponsorIndex = 0;
            slot.innerHTML = list.map((sp, i) => `
                <img src="${escapeHtml(safeUploadUrl(sp.url))}" alt="${escapeHtml(sp.name || '')}"
                     class="board-sponsor-slide ${i === 0 ? 'visible' : ''}" id="boardSponsor_${i}">
            `).join('');
            startBoardSponsorRotation();
        }

        function startBoardSponsorRotation() {
            if (boardSponsorInterval || (sponsorsList || []).length <= 1) return;
            boardSponsorInterval = setInterval(() => {
                const total = sponsorsList.length;
                if (total <= 1) return;
                const prev = document.getElementById(`boardSponsor_${boardSponsorIndex}`);
                if (prev) prev.classList.remove("visible");
                boardSponsorIndex = (boardSponsorIndex + 1) % total;
                const next = document.getElementById(`boardSponsor_${boardSponsorIndex}`);
                if (next) next.classList.add("visible");
            }, BOARD_SPONSOR_MS);
        }

        function stopBoardSponsorRotation() {
            if (boardSponsorInterval) { clearInterval(boardSponsorInterval); boardSponsorInterval = null; }
        }

        function buildSponsorElements() {
            const stage = document.getElementById("sponsorStage");
            if (!sponsorsList || sponsorsList.length === 0) {
                stage.innerHTML = '<div style="color: var(--text-dim); font-size: 1.5vw;" id="noSponsorsNotice">Präsentiert von unseren Sponsoren</div>';
                return;
            }
            stage.innerHTML = sponsorsList.map((s, idx) => `
                <img src="${escapeHtml(safeUploadUrl(s.url))}" alt="${escapeHtml(s.name || '')}" class="sponsor-slide ${idx === 0 ? 'visible' : ''}" id="sponsorSlide_${idx}">
            `).join('');
        }

        function startSponsorSlideshow() {
            if (sponsorInterval || sponsorsList.length <= 1) return;
            sponsorInterval = setInterval(() => {
                const total = sponsorsList.length;
                if (total <= 1) return;
                const prev = document.getElementById(`sponsorSlide_${sponsorIndex}`);
                if (prev) prev.classList.remove("visible");
                sponsorIndex = (sponsorIndex + 1) % total;
                const next = document.getElementById(`sponsorSlide_${sponsorIndex}`);
                if (next) next.classList.add("visible");
            }, 4000);
        }

        function stopSponsorSlideshow() {
            if (sponsorInterval) { clearInterval(sponsorInterval); sponsorInterval = null; }
        }

        connectWS();
        loadSponsors();
    