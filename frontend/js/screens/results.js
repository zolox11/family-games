import {getResults} from "../api.js";

const esc = (value) => String(value).replace(/[&<>"']/g, (char) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));

export async function renderResults(root, {state, api, show, notify}) {
  const results = await getResults(state.sessionId);
  const label = (id) => state.session.teams ? `Team ${id}` : state.session.players.find((p) => p.id === id)?.name || id;
  const winner = results.winner && results.winner !== "Draw" ? label(results.winner) : results.winner;
  const facts = results.match_facts || [];
  root.innerHTML = `
    <div class="eyebrow">Step 6 · Game day results</div>
    <div class="winner"><div class="trophy">${winner && winner !== "Draw" ? "🏆" : "🤝"}</div><h2>${winner ? `${esc(winner)} ${winner === "Draw" ? "" : "wins!"}` : "Game complete!"}</h2><p>${esc(state.game.name)} · ${state.session.total_rounds} round(s)</p></div>
    <h2 style="margin-top:25px">Final score</h2>
    <div class="scoreboard">${Object.entries(results.scores).map(([id, value]) => `<div class="score"><span>${esc(label(id))}</span><strong>${value}</strong></div>`).join("")}</div>
    ${results.mvp ? `<div class="callout">⭐ Match MVP: <b>${esc(results.mvp)}</b></div>` : ""}
    <h2 style="margin-top:26px">Match facts</h2>
    <div class="grid">${facts.map((item, index) => `<div class="card"><span class="badge">Round ${item.round || index + 1}</span><h3>${esc(item.summary || "Judged round")}</h3><p class="small muted">${(item.events || []).length} event(s) verified and applied.</p></div>`).join("") || `<div class="card muted">No judged rounds were applied yet.</div>`}</div>
    <div class="button-row"><button class="btn primary" id="another">Choose another game</button><button class="btn light" id="back">Review final round</button></div>`;
  root.querySelector("#another").addEventListener("click", () => {
    state.sessionId = null; state.session = null; state.game = null; state.clip = null;
    state.reportBundle = null; state.applied = false; state.cues = {}; state.rois = {}; state.seeds = {};
    show("game");
  });
  root.querySelector("#back").addEventListener("click", () => show("judge"));
}
