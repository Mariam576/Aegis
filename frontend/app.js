// ---------- helpers ----------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : "#");

let stream = null;          // the open EventSource
let fullMarkdown = "";      // report + references, for copy/download
let lastComparison = null;
const sources = new Map();  // "S1" -> source info

// ---------- backend status badge ----------
fetch("/api/health")
  .then((r) => r.json())
  .then((h) => {
    const b = $("#status");
    if (!h.llm_ready) { b.textContent = "GEMINI_API_KEY missing"; b.classList.add("bad"); return; }
    b.textContent = `Gemini + ${h.search === "tavily" ? "Tavily" : "DuckDuckGo"}`;
    b.classList.add("ok");
  })
  .catch(() => { $("#status").textContent = "Backend offline"; $("#status").classList.add("bad"); });

// ---------- tabs & form ----------
$$(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
function showTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".tab-body").forEach((b) => b.classList.toggle("hidden", b.id !== `tab-${name}`));
}

$$(".example").forEach((b) => b.addEventListener("click", () => {
  $("#topic").value = b.textContent;
  $("#topic").focus();
}));

$("#form").addEventListener("submit", (e) => {
  e.preventDefault();
  const topic = $("#topic").value.trim();
  if (topic.length >= 3) start(topic, $("#depth").value);
});

// ---------- run the agent ----------
function start(topic, depth) {
  if (stream) stream.close();
  resetUI();
  setBusy(true);

  stream = new EventSource(`/api/research?topic=${encodeURIComponent(topic)}&depth=${depth}`);
  const on = (name, fn) => stream.addEventListener(name, (e) => fn(JSON.parse(e.data)));

  on("stage", ({ stage, status }) => {
    const li = $(`#stages li[data-stage="${stage}"]`);
    if (li) li.className = status;
  });
  on("log", ({ message }) => log(message));
  on("plan", renderPlan);
  on("sources", ({ sources: list }) => { list.forEach((s) => sources.set(s.id, s)); renderSources(); });
  on("source_analyzed", (s) => { sources.set(s.id, s); renderSources(); });
  on("comparison", renderComparison);
  on("report", renderReport);
  on("failed", ({ message }) => {
    log(message, "err");
    markFailed();
    $("#report").innerHTML = `<p class="err">Research stopped: ${esc(message)}</p>`;
  });
  on("done", finish);

  // EventSource auto-reconnects (which would restart the research), so close on any error
  stream.onerror = () => { log("Lost connection to the server.", "err"); markFailed(); finish(); };
}

function finish() {
  if (stream) { stream.close(); stream = null; }
  setBusy(false);
}

function setBusy(busy) {
  $("#go").disabled = busy;
  $("#go").textContent = busy ? "Researching…" : "Research";
}

function markFailed() {
  $$("#stages li.active").forEach((li) => (li.className = "failed"));
}

function resetUI() {
  sources.clear();
  fullMarkdown = "";
  lastComparison = null;
  $("#workspace").classList.remove("hidden");
  $$("#stages li").forEach((li) => (li.className = ""));
  $("#plan").innerHTML = "";
  $("#log").innerHTML = "";
  $("#report").innerHTML = `<p class="muted">The agent is working (usually 1–3 minutes on the free tier). The report appears here when it's done.</p>`;
  $("#refs").innerHTML = "";
  $("#sources").innerHTML = "";
  $("#compare").innerHTML = `<p class="muted">Appears after the sources are compared.</p>`;
  $("#src-count").textContent = "";
  $("#report-actions").classList.add("hidden");
  showTab("report");
}

function log(message, cls = "") {
  const li = document.createElement("li");
  li.textContent = message;
  if (cls) li.className = cls;
  $("#log").appendChild(li);
  $("#log").scrollTop = $("#log").scrollHeight;
}

// ---------- renderers ----------
function renderPlan({ sub_questions, queries }) {
  $("#plan").innerHTML = `
    <h3>Sub-questions</h3><ul>${sub_questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>
    <h3>Search queries</h3><ul class="queries">${queries.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>`;
}

function renderSources() {
  const list = [...sources.values()];
  $("#src-count").textContent = list.length ? `(${list.length})` : "";
  $("#sources").innerHTML = list.map((s) => {
    const cred = s.credibility
      ? `<span class="cred c${s.credibility}" title="${esc(s.credibility_reason)}">credibility ${s.credibility}/5</span>` : "";
    const cited = s.ref ? `<span class="cited">cited as [${s.ref}]</span>` : "";
    const meta = [s.site, s.date, s.source_type].filter(Boolean).map(esc).join(" · ");

    let body = `<p class="muted small">Reading…</p>`;
    if (s.analyzed) {
      const dropped = (s.claims_total || 0) - s.claims.length;
      body = `<p>${esc(s.summary)}</p>` + (s.claims.length
        ? `<details><summary>${s.claims.length} verified claim${s.claims.length === 1 ? "" : "s"}${
            dropped > 0 ? ` · ${dropped} dropped (quote not found on page)` : ""}</summary>
             <ul class="claims">${s.claims.map((c) => `<li>${esc(c.claim)}<q>${esc(c.quote)}</q></li>`).join("")}</ul>
           </details>`
        : `<p class="muted small">No verified claims${s.relevant === false ? " (off-topic)" : ""}.</p>`);
    }

    return `<div class="src ${s.analyzed && !s.claims.length ? "dim" : ""}">
      <div class="src-head">
        <span class="sid">${esc(s.id)}</span>
        <a href="${safeUrl(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>
        ${cited}${cred}
      </div>
      <div class="meta">${meta}</div>
      ${body}
    </div>`;
  }).join("");
}

// Show [n] once the report has numbered the sources, otherwise the S-id
function tag(id) {
  const s = sources.get(id);
  return `<span class="sid" title="${esc(s?.title)}">${s?.ref ? `[${s.ref}]` : esc(id)}</span>`;
}

function renderComparison(c) {
  lastComparison = c;
  const tags = (ids = []) => ids.map(tag).join(" ");
  const section = (title, items, cls, fn) => (items && items.length
    ? `<h3>${title}</h3>` + items.map((x) => `<div class="card ${cls}">${fn(x)}</div>`).join("")
    : "");

  const html =
    section("Sources agree", c.consensus, "agree", (x) =>
      `<p>${esc(x.finding)}</p>${tags(x.sources)}` +
      (x.confidence ? ` <span class="muted small">${esc(x.confidence)} confidence</span>` : "")) +
    section("Sources disagree", c.disagreements, "disagree", (x) =>
      `<p><strong>${esc(x.issue)}</strong></p>
       <ul>${(x.positions || []).map((p) => `<li>${esc(p.view)} ${tags(p.sources)}</li>`).join("")}</ul>` +
      (x.likely_reason ? `<p class="muted small">Likely reason: ${esc(x.likely_reason)}</p>` : "")) +
    section("Only one source says", c.single_source, "single", (x) =>
      `<p>${esc(x.finding)}</p>${tags(x.sources)}`) +
    section("Gaps in the evidence", c.gaps, "", (g) => `<p>${esc(g)}</p>`);

  $("#compare").innerHTML = html || `<p class="muted">The sources didn't overlap enough to compare.</p>`;
}

function renderReport({ markdown, references, full_markdown }) {
  fullMarkdown = full_markdown;

  // remember which number each source got, so the other tabs can show it
  references.forEach((r) => { const s = sources.get(r.id); if (s) s.ref = r.n; });
  renderSources();
  if (lastComparison) renderComparison(lastComparison);

  // turn [3] into a clickable superscript that jumps to the reference
  const linked = markdown.replace(/\[(\d+)\](?!\()/g,
    (_, n) => `<sup class="cite"><a href="#ref-${n}">[${n}]</a></sup>`);
  $("#report").innerHTML = DOMPurify.sanitize(marked.parse(linked));

  $("#refs").innerHTML = `<h2>References</h2>` + references.map((r) => `
    <p class="ref" id="ref-${r.n}"><span class="n">[${r.n}]</span>
      ${esc(r.author)} (${esc(r.year)}).
      <a href="${safeUrl(r.url)}" target="_blank" rel="noopener"><i>${esc(r.title)}</i></a>.
      ${esc(r.site)}. <span class="muted">Accessed ${esc(r.accessed)}.</span>
    </p>`).join("");

  $("#report-actions").classList.remove("hidden");
}

// ---------- copy / download ----------
$("#copy").addEventListener("click", async () => {
  await navigator.clipboard.writeText(fullMarkdown);
  flash($("#copy"), "Copied!");
});

$("#download").addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([fullMarkdown], { type: "text/markdown" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: "research-report.md" });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

function flash(btn, text) {
  const old = btn.textContent;
  btn.textContent = text;
  setTimeout(() => (btn.textContent = old), 1500);
}
