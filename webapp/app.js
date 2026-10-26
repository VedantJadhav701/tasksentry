(() => {
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let spec = null, graph = null, playing = 0;

document.querySelectorAll("#seg button").forEach((b) => b.onclick = () => showTab(b.dataset.tab));
function showTab(t) {
  document.querySelectorAll("#seg button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("on", s.id === "tab-" + t));
}
$("#noise").oninput = (e) => $("#noiseV").textContent = e.target.value + "%";
$("#loadSample").onclick = async () => {
  try {
    const response = await fetch("/webapp/sample_ticket.json");
    if (!response.ok) throw new Error(`Sample record unavailable (${response.status})`);
    $("#record").value = await response.text();
    $("#err").textContent = "";
  } catch (error) {
    $("#err").textContent = error.message || "Could not load the sample record";
  }
};
$("#file").onchange = async (e) => { const f = e.target.files[0]; if (f) $("#record").value = await f.text(); };

function payload() {
  return { record: $("#record").value, use_llm: $("#useLlm").checked, model: $("#model").value || "beam:cloud",
           flip_prob: +$("#noise").value / 100, approve_high_risk: $("#approve").checked,
           execution_mode: $("#mode").value, backend_id: $("#backend").value.trim() || null };
}
async function post(url) {
  $("#err").textContent = "";
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload()) });
  const j = await r.json();
  if (!r.ok) {
    const detail = j.detail || `Request failed (${r.status})`;
    $("#err").textContent = detail;
    throw new Error(detail);
  }
  return j;
}

$("#analyze").onclick = async () => { try { const j = await post("/api/onboard/analyze"); render(j); } catch (e) {} };
$("#runBtn").onclick = async () => {
  try { const j = await post("/api/onboard/run"); render(j); showTab("live"); await replay(j); } catch (e) {}
};

function render(j) {
  spec = j.spec; graph = j.graph;
  const p = j.profile;
  $("#runMeta").textContent = `${j.execution_mode || "simulation"} · backend ${j.backend_id || "simulated"} · ${j.simulated ? "dry-run evidence" : "live backend evidence"}`;
  $("#recogEmpty").hidden = true;
  const conf = Math.round(p.confidence * 100);
  $("#recogBody").innerHTML = `
    <div class="kv"><b>Format</b><span>${esc(p.format)} <span class="pill ${conf >= 80 ? "ok" : "warn"}">${conf}% confident</span></span>
    <b>Record</b><span>${esc(p.record_id || "—")}</span>
    <b>Category</b><span>${esc(p.category || "—")}</span>
    <b>Label hint</b><span>${esc(p.label_hint || "—")}</span>
    <b>Steps found</b><span>${p.steps.length}</span></div>
    <div class="chips">${Object.entries(p.entities).map(([k, v]) => `<span class="chip">${esc(k)}: ${esc(v)}</span>`).join("")}</div>
    ${p.warnings.map((w) => `<p class="sub">⚠︎ ${esc(w)}</p>`).join("")}
    ${p.steps.map((s) => `<div class="step"><b>${s.number}. ${esc(s.title)}</b><br><code>${esc((s.commands[0] || "").slice(0, 110))}</code></div>`).join("")}`;
  $("#specBody").innerHTML = `
    <p class="sub">Source: <b>${esc(spec.source)}</b> · domain <b>${esc(spec.domain)}</b></p>
    <h3>Root-cause hypotheses (prior)</h3>${spec.hypotheses.map((h) => bar(h, spec.priors[h], false)).join("")}
    <h3>Probes</h3>${spec.probes.map((q) => `<div class="step"><b>${esc(q.name)}</b> → ${q.owns.map(esc).join(", ")}<br><code>${esc(q.commands[0] || "")}</code></div>`).join("")}
    <h3>Remediations</h3>${spec.remediations.map((r) => `<div class="step"><b>${esc(r.name)}</b> for ${esc(r.hypothesis)} <span class="pill ${r.risk === "reversible_write" ? "ok" : "warn"}">${esc(r.risk)}</span></div>`).join("") || '<p class="sub">None documented — all causes escalate.</p>'}
    <h3>Notes</h3>${spec.notes.map((n) => `<p class="sub">• ${esc(n)}</p>`).join("")}`;
  drawGraph();
  $("#post").innerHTML = spec.hypotheses.map((h) => bar(h, spec.priors[h], false)).join("");
  setTimeout(() => document.querySelectorAll("#post .f").forEach((f) => f.style.width = f.dataset.w), 30);
}

function bar(h, v, top) {
  return `<div class="bar ${top ? "top" : ""}" data-h="${esc(h)}"><span title="${esc(h)}">${esc(h)}</span><div class="t"><div class="f" data-w="${(v * 100).toFixed(1)}%" style="width:${(v * 100).toFixed(1)}%"></div></div><span>${(v * 100).toFixed(0)}%</span></div>`;
}
function setPosterior(post) {
  const entries = Object.entries(post).sort((a, b) => b[1] - a[1]);
  $("#post").innerHTML = entries.map(([h, v], i) => bar(h, v, i === 0)).join("");
}

// ---------- graph ----------
const NS = "http://www.w3.org/2000/svg", pos = {};
function el(name, attrs, parent) { const e = document.createElementNS(NS, name); for (const k in attrs) e.setAttribute(k, attrs[k]); parent && parent.appendChild(e); return e; }
function drawGraph() {
  const svg = $("#graph"); svg.innerHTML = "";
  const probes = graph.nodes.filter((n) => n.kind === "probe");
  const H = Math.max(420, probes.length * 56 + 40);
  svg.setAttribute("viewBox", `0 0 760 ${H}`);
  probes.forEach((n, i) => pos[n.id] = { x: 20, y: 24 + i * 56, w: 270, h: 44 });
  const mid = H / 2;
  Object.assign(pos, { diagnosis: { x: 400, y: mid - 140, w: 170, h: 44 }, remediation: { x: 400, y: mid - 50, w: 170, h: 44 },
    verification: { x: 400, y: mid + 40, w: 170, h: 44 }, resolved: { x: 620, y: mid - 50, w: 120, h: 44 }, escalated: { x: 620, y: mid + 40, w: 120, h: 44 } });
  const eg = el("g", {}, svg);
  graph.edges.forEach((e) => {
    const a = pos[e.from], b = pos[e.to]; if (!a || !b) return;
    const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2;
    let d;
    if (b.x === a.x + 0 || (a.x >= 400 && b.x >= 400 && b.x === a.x)) d = `M${a.x + a.w / 2},${a.y + a.h} L${b.x + b.w / 2},${b.y}`;
    else d = `M${x1},${y1} C${x1 + 60},${y1} ${x2 - 60},${y2} ${x2},${y2}`;
    const p = el("path", { d, class: "e", id: `e-${e.from}-${e.to}` }, eg);
  });
  graph.nodes.forEach((n) => {
    const q = pos[n.id]; const g = el("g", { class: "n", id: "n-" + n.id, transform: `translate(${q.x},${q.y})` }, svg);
    el("rect", { width: q.w, height: q.h, rx: 14 }, g);
    const t = el("text", { x: 14, y: n.kind === "probe" ? 19 : 26 }, g); t.textContent = n.label.length > 36 ? n.label.slice(0, 35) + "…" : n.label;
    if (n.kind === "probe") { const s = el("text", { x: 14, y: 34, class: "s" }, g); s.textContent = (n.command || "").slice(0, 44); }
  });
}
function node(id, cls, badge) {
  const g = $("#n-" + id); if (!g) return;
  g.setAttribute("class", "n " + cls);
  if (badge) { g.querySelector(".badge")?.remove(); g.querySelector(".bt")?.remove();
    const q = pos[id]; el("circle", { class: "badge", cx: q.w - 14, cy: 14, r: 10 }, g); const t = el("text", { class: "bt", x: q.w - 14, y: 18, "text-anchor": "middle" }, g); t.textContent = badge; }
}
function edge(from, to, cls) { const e = $(`#e-${from}-${to}`); if (e) e.setAttribute("class", "e " + cls); }

// ---------- terminal ----------
function say(msg, cls) { const t = $("#term"); const s = document.createElement("span"); if (cls) s.className = cls; s.textContent = msg + "\n"; t.appendChild(s); t.scrollTop = t.scrollHeight; }
function status(txt, cls) { const s = $("#status"); s.textContent = txt; s.className = "pill " + (cls || ""); }

async function replay(j) {
  const my = ++playing; drawGraph(); $("#term").textContent = ""; $("#resultCard").hidden = true;
  setPosterior(Object.fromEntries(spec.hypotheses.map((h) => [h, spec.priors[h]])));
  const used = new Set(); let order = 0; status("running", "run");
  const pr = Object.fromEntries(spec.probes.map((p) => [p.name, p]));
  for (const ev of j.events) {
    if (my !== playing) return;
    if (ev.event === "start") { say(`# harness start · domain ${ev.domain}`, "c"); }
    else if (ev.event === "probe") {
      const p = pr[ev.probe]; used.add(ev.probe); node(ev.probe, "run"); edge(ev.probe, "diagnosis", "on");
      say(`$ ${p?.commands?.[0] || ev.probe}`); await sleep(520);
      node(ev.probe, ev.abnormal ? "bad" : "ok", ++order); edge(ev.probe, "diagnosis", "done");
      say(ev.abnormal ? `  ✗ ABNORMAL  (${p?.title || ev.probe})` : `  ✓ normal`, ev.abnormal ? "e" : "");
      say(`  posterior → ${ev.top} ${(ev.confidence * 100).toFixed(0)}%  · entropy ${ev.entropy_bits.toFixed(2)} bits`, "c");
      setPosterior(ev.posterior);
    } else if (ev.event === "diagnosis") {
      graph.nodes.filter((n) => n.kind === "probe" && !used.has(n.id)).forEach((n) => node(n.id, "skip"));
      node("diagnosis", "ok"); say(`# diagnosis: ${ev.hypothesis} (${(ev.confidence * 100).toFixed(0)}%) set=[${ev.set.join(", ")}]`, "c");
    } else if (ev.event === "gate") {
      node("remediation", "run"); edge("diagnosis", "remediation", "on");
      say(`# gate ${ev.action} [${ev.risk}] EU=${ev.eu} → ${ev.reason}`, "w");
    } else if (ev.event === "approval") { say(`# approval: ${ev.result}`, ev.result === "approved" ? "w" : "e"); if (ev.result !== "approved") { node("remediation", "warn"); edge("remediation", "escalated", "on"); } }
    else if (ev.event === "remediation") { node("remediation", "ok"); edge("diagnosis", "remediation", "done"); edge("remediation", "verification", "on"); say(`$ apply ${ev.action}`); say(`  ${ev.result}`); }
    else if (ev.event === "verification") {
      node("verification", ev.healthy ? "ok" : "bad"); edge("remediation", "verification", "done");
      say(`# SPRT verification: ${ev.decision} after ${ev.reads} reads (LLR ${ev.llr})`, ev.healthy ? "c" : "e");
    } else if (ev.event === "receipt") {
      const ok = ev.status === "resolved"; node(ok ? "resolved" : "escalated", ok ? "ok" : "warn");
      edge(ok ? "verification" : "diagnosis", ok ? "resolved" : "escalated", "done");
      status(ev.status, ok ? "ok" : "warn"); say(`# receipt signed · status ${ev.status}`, "c");
    }
    await sleep(380);
  }
  const r = j.result;
  const c = $("#resultCard"); c.hidden = false;
  c.innerHTML = `<h2>Result <span class="pill ${r.status === "resolved" ? "ok" : "warn"}">${esc(r.status)}</span> <span class="pill">${esc(j.execution_mode || "simulation")} backend</span></h2>
    <div class="kv"><b>Root cause</b><span>${esc(r.diagnosis.hypothesis)} (${(r.diagnosis.confidence * 100).toFixed(1)}%)</span>
    <b>Probes run</b><span>${r.diagnosis.probes_run.length} of ${spec.probes.length} · entropy ${r.diagnosis.entropy_start_bits.toFixed(2)} → ${r.diagnosis.entropy_end_bits.toFixed(2)} bits</span>
    <b>Remediation</b><span>${esc(r.remediation ? r.remediation.name + " (" + r.remediation.risk + ")" : "none")}</span>
    <b>Approval</b><span>${esc(r.approval)}</span>
    <b>Escalation</b><span>${esc(r.escalation_team || "—")} ${r.escalation_reason ? "· " + esc(r.escalation_reason) : ""}</span>
     <b>Audit chain</b><span>${r.chain_length} entries · ${r.chain_valid ? "valid ✓" : "INVALID"} · ${r.chain_signed ? "HMAC signed" : "integrity only"} · root ${esc(r.chain_root.slice(0, 20))}…</span></div>`;
}

fetch("/api/onboard/health").then((r) => r.ok && ($("#conn").textContent = "online", $("#conn").className = "pill ok")).catch(() => {});
})();
