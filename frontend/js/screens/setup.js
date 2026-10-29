const icons = {football: "⚽", majlis_freeze: "🎵", say_it_right: "🎙️", hand_duel: "✋", bucket_toss: "🪣"};
const esc = (value) => String(value).replace(/[&<>"']/g, (char) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));

export async function renderGame(root, {state, show}) {
  root.innerHTML = `
    <div class="home-hero">
      <div class="hero-copy">
        <div class="eyebrow"><span class="eyebrow-dot"></span> FAMILY GAME DAY · LEVEL 01</div>
        <h1>Ready, player one?</h1>
        <p class="lead">Pick a game, call your crew, and let your AI referee keep score. The best part? You play it for real.</p>
        <div class="hero-tags"><span>✦ 5 mini-games</span><span>✦ Arabic + English</span><span>✦ Family approved</span></div>
      </div>
      <div class="hero-art" aria-hidden="true">
        <div class="pixel-sun"></div><div class="pixel-cloud cloud-one"></div><div class="pixel-cloud cloud-two"></div>
        <div class="pixel-hill"></div><div class="pixel-ball">⚽</div><div class="hero-level">LET'S PLAY!</div>
      </div>
    </div>
    <div class="section-heading"><div><div class="eyebrow">CHOOSE YOUR QUEST</div><h2>Pick a game to play</h2></div><span class="section-note">5 GAMES · 1 FAMILY</span></div>
    <div class="grid">${state.games.map((game) => `
      <article class="card game-card">
        <div class="game-card-top"><div class="game-icon">${icons[game.id] || "🎲"}</div><span class="badge">${game.mode === "both" ? "TEAMS OR SOLO" : game.mode.toUpperCase()}</span></div>
        <h3>${esc(game.name)}</h3><p class="muted small">${esc(game.description)}</p>
        <button class="btn primary choose-game" data-game="${esc(game.id)}"><span>Choose game</span><span aria-hidden="true">→</span></button>
      </article>`).join("")}</div>`;
  root.querySelectorAll(".choose-game").forEach((button) => button.addEventListener("click", () => {
    state.game = state.games.find((game) => game.id === button.dataset.game);
    state.playerDrafts = state.game.id === "hand_duel"
      ? [{id: "P1", name: ""}, {id: "P2", name: ""}]
      : [{id: "P1", name: ""}, {id: "P2", name: ""}];
    state.teamsEnabled = state.game.mode === "team";
    state.rois = {};
    state.seeds = {};
    state.cues = {};
    show("players");
  }));
}

export async function renderPlayers(root, {state, show, api, notify}) {
  const game = state.game;
  if (!game) return show("game");
  const teamSelect = (player, i) => game.mode === "individual" ? "" : `
    <select aria-label="Team for ${player.id}" data-team="${player.id}" ${game.mode === "team" ? "" : "data-optional-team"}>
      <option value="A" ${i % 2 === 0 ? "selected" : ""}>Team A</option>
      <option value="B" ${i % 2 === 1 ? "selected" : ""}>Team B</option>
    </select>`;
  root.innerHTML = `
    <div class="eyebrow">Step 2 · Set your teams</div><h1>Who's playing?</h1>
    <p class="lead">${game.id === "hand_duel" ? "Hand Duel is a two-player face-off." : "Add 2–4 players. Names can be in English or Arabic."}</p>
    ${game.mode === "both" ? `<label class="field"><span><input id="teamsEnabled" type="checkbox" ${state.teamsEnabled ? "checked" : ""}> Play as Team A vs Team B</span></label>` : ""}
    <div id="playersList"></div>
    <button class="btn light" id="addPlayer" ${state.playerDrafts.length >= (game.id === "hand_duel" ? 2 : 4) ? "disabled" : ""}>＋ Add player</button>
    <div class="button-row"><button class="btn light" id="back">← Back</button><button class="btn primary" id="savePlayers">Save players & teams →</button></div>`;
  const list = root.querySelector("#playersList");
  const paint = () => {
    list.innerHTML = state.playerDrafts.map((player, i) => `
      <div class="player-row"><span class="player-id">${player.id}</span>
      <input dir="auto" maxlength="40" data-name="${player.id}" placeholder="Player ${i + 1} name" value="${esc(player.name)}">
      ${state.teamsEnabled || game.mode === "team" ? teamSelect(player, i) : ""}</div>`).join("");
    root.querySelector("#addPlayer").disabled = state.playerDrafts.length >= (game.id === "hand_duel" ? 2 : 4);
  };
  paint();
  root.querySelector("#teamsEnabled")?.addEventListener("change", (event) => {
    state.teamsEnabled = event.target.checked;
    paint();
  });
  root.querySelector("#addPlayer").addEventListener("click", () => {
    if (state.playerDrafts.length < 4) {
      state.playerDrafts.push({id: `P${state.playerDrafts.length + 1}`, name: ""});
      paint();
    }
  });
  root.querySelector("#back").addEventListener("click", () => show("game"));
  root.querySelector("#savePlayers").addEventListener("click", async () => {
    state.playerDrafts = state.playerDrafts.map((player) => ({...player, name: root.querySelector(`[data-name="${player.id}"]`).value.trim()}));
    if (state.playerDrafts.some((player) => !player.name)) return notify("Please enter a name for every player.");
    const body = {game_id: game.id, players: state.playerDrafts};
    if (state.teamsEnabled || game.mode === "team") {
      const teams = {A: [], B: []};
      state.playerDrafts.forEach((player, i) => {
        const selected = root.querySelector(`[data-team="${player.id}"]`)?.value || (i % 2 ? "B" : "A");
        teams[selected].push(player.id);
      });
      if (!teams.A.length || !teams.B.length) return notify("Each team needs at least one player.");
      body.teams = teams;
    }
    try {
      const result = await api.createSession(body);
      state.sessionId = result.session_id;
      state.session = result.state;
      await show("rules");
    } catch (error) {
      notify(error.message);
    }
  });
}

export async function renderRules(root, {state, show, api, notify, refreshSession}) {
  const game = state.game;
  if (!game || !state.session) return show("game");
  const editable = Object.entries(state.session.rules).filter(([, value]) => typeof value === "number");
  root.innerHTML = `
    <div class="eyebrow">Step 3 · Rules & ready</div><h1>${esc(game.name)} rules</h1>
    <div class="callout">${esc(game.rules.text)}</div>
    <div class="rules-list">${editable.map(([key, value]) => `<label class="field"><span>${esc(key.replaceAll("_", " "))}</span><input type="number" min="0" max="3600" data-rule="${esc(key)}" value="${value}"></label>`).join("")}</div>
    <div class="card"><h3>Players & teams</h3><p class="muted">${state.session.players.map((p) => `${esc(p.name)} (${p.id})`).join(" · ")}${state.session.teams ? `<br>Team A: ${state.session.teams.A.join(", ")} · Team B: ${state.session.teams.B.join(", ")}` : ""}</p></div>
    <div class="button-row"><button class="btn light" id="back">← Players</button><button class="btn primary" id="ready">Everyone ready — let's play! →</button></div>`;
  root.querySelector("#back").addEventListener("click", () => show("players"));
  root.querySelector("#ready").addEventListener("click", async () => {
    const rules = {};
    root.querySelectorAll("[data-rule]").forEach((input) => { rules[input.dataset.rule] = Number(input.value); });
    try {
      await api.updateRules(state.sessionId, rules);
      await refreshSession();
      await show("play");
    } catch (error) {
      notify(error.message);
    }
  });
}
