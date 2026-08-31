// Shared helpers for board.js and control.js.
// Loaded before the page script on both /board and /control.

function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
}

function safeUploadUrl(url) {
    const u = String(url || "");
    return (u.startsWith("/uploads/") || u.startsWith("data:image/")) ? u : "";
}

function formatTime(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}
