"use strict";

const log = (s) => {
    const el = document.getElementById("log");
    el.textContent += s + "\n";
    el.scrollTop = el.scrollHeight;
};

let session = null, uploaded = [], reference = null;

async function postForm(url, data) {
    const res = await fetch(url, { method: "POST", body: data });
    if (!res.ok) {
        throw new Error(await res.text());
    }
    return res.json();
}

document.addEventListener("DOMContentLoaded", () => {
    const uploadBtn = document.getElementById("btnUpload");
    uploadBtn.onclick = onUpload;
});

async function onUpload() {
    const fd = new FormData();
    const files = document.getElementById("files").files;
    if (!files.length) {
        return log("Select at least one CSV/XLSX.");
    }
    for (const f of files) fd.append("files", f);
    const r = document.getElementById("ref").files[0];
    if (r) fd.append("reference_json", r);

    try {
        const out = await postForm("/api/upload", fd);
        session = out.session;
        uploaded = out.files;
        reference = out.reference;
        log(`Uploaded. Session: ${session}`);
        renderFiles();
    } catch (e) {
        log("ERR upload: " + e.message);
    }
}

function renderFiles() {
    const area = document.getElementById("filesArea");
    area.innerHTML = uploaded
        .map(
            (f) => `
    <div class="row">
      <b>${f.filename}</b>
      <button onclick="scan('${f.filename}')">Scan</button>
      <button onclick="applyFix('${f.filename}')">Change All & Download</button>
      ${reference ? `<button onclick="compareToJson('${f.filename}')">Compare to JSON</button>` : ""}
    </div>
    <div id="issues-${css(f.filename)}"></div>
  `
        )
        .join("");
}

function css(s) {
    return s.replace(/[^a-z0-9]/gi, "_");
}

async function scan(filename) {
    const fd = new FormData();
    fd.append("session", session);
    fd.append("filename", filename);
    try {
        const out = await postForm("/api/scan", fd);
        log(`Scan ${filename}: ${out.issues.length} issues found.`);

        const div = document.getElementById("issues-" + css(filename));
        const maxShown = 150;
        const items = out.issues.slice(0, maxShown).map(card).join("");

        div.innerHTML = `
      <div class="issues-list">
        ${items || '<div class="muted">No issues.</div>'}
      </div>
      ${out.issues.length > maxShown ? '<div class="warn">Showing first ' + maxShown + '…</div>' : ''}
    `;
    } catch (e) {
        log("ERR scan: " + e.message);
    }
}

function card(i) {
    return `
  <div class="issue-card">
    <div class="issue-meta">
      <span class="pill">#${i.id}</span>
      <span class="pill">row ${i.row}</span>
      <span class="pill">col ${i.col ?? i.column}</span>
      ${i.column ? `<span class="pill muted">header: ${escapeHtml(i.column)}</span>` : ``}
    </div>
    <div class="issue-body">
      <div class="kv">
        <div class="k bad">Before</div>
        <div class="v mono">${escapeHtml(i.before)}</div>
      </div>
      <div class="arrow">→</div>
      <div class="kv">
        <div class="k ok">After</div>
        <div class="v mono">${escapeHtml(i.after)}</div>
      </div>
    </div>
  </div>`;
}

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

async function applyFix(filename) {
    const fd = new FormData();
    fd.append("session", session);
    fd.append("filename", filename);
    fd.append("change_all", "true");
    fd.append("apply_ids", "[]");
    fd.append("export", document.getElementById("exportFmt").value);
    try {
        const out = await postForm("/api/apply", fd);
        log(`Applied. Downloading ${out.corrected} & ${out.issues_report}`);
        window.open(`/api/download/${session}/${out.corrected}`, "_blank");
        window.open(`/api/download/${session}/${out.issues_report}`, "_blank");
    } catch (e) {
        log("ERR apply: " + e.message);
    }
}

async function compareToJson(filename) {
    const fd = new FormData();
    fd.append("session", session);
    fd.append("filename", filename);
    fd.append("reference", reference);
    fd.append("export", document.getElementById("exportFmt").value);
    try {
        const out = await postForm("/api/compare", fd);
        log(
            `Compare meta: missing=${out.meta.missing_count}, extra=${out.meta.extra_count}, samples=${out.meta.sample_count}`
        );
        window.open(`/api/download/${session}/${out.report}`, "_blank");
    } catch (e) {
        log("ERR compare: " + e.message);
    }
}

// make functions callable from inline handlers
window.scan = scan;
window.applyFix = applyFix;
window.compareToJson = compareToJson;

