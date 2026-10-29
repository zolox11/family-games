import * as api from "./api.js";
import {renderGame, renderPlayers, renderRules} from "./screens/setup.js";
import {renderPlay} from "./screens/play.js";
import {renderJudge} from "./screens/judge.js";
import {renderResults} from "./screens/results.js";

export const state = {
  games: [], questions: [], game: null, playerDrafts: [{id: "P1", name: ""}, {id: "P2", name: ""}],
  sessionId: null, session: null, clip: null, cues: {}, rois: {}, seeds: {}, questionId: null, teamsEnabled: false,
};

const screens = {
  game: renderGame, players: renderPlayers, rules: renderRules,
  play: renderPlay, judge: renderJudge, results: renderResults,
};
const progress = [
  ["game", "PICK", "🎮"],
  ["players", "PLAYERS", "👾"],
  ["rules", "READY", "⭐"],
  ["play", "PLAY", "🏁"],
  ["judge", "JUDGE", "🤖"],
  ["results", "WIN!", "🏆"],
];

export function notify(message = "", kind = "error") {
  const el = document.querySelector("#notice");
  el.className = message ? `notice ${kind}` : "";
  el.textContent = message;
}

export async function refreshSession() {
  if (!state.sessionId) return null;
  state.session = await api.getSession(state.sessionId);
  return state.session;
}

export async function show(name) {
  notify();
  document.querySelectorAll("[data-screen]").forEach((section) => {
    section.hidden = section.dataset.screen !== name;
  });
  const activeIndex = progress.findIndex(([step]) => step === name);
  document.querySelector("#progress").innerHTML = progress.map(([step, label, icon], index) => `
    <div class="progress-step ${index < activeIndex ? "done" : ""} ${index === activeIndex ? "current" : ""}" ${index === activeIndex ? 'aria-current="step"' : ""}>
      <span class="progress-icon">${index < activeIndex ? "✓" : icon}</span><span class="progress-label">${label}</span>
    </div>`).join("");
  const badge = document.querySelector("#sessionBadge");
  badge.hidden = !state.sessionId;
  badge.textContent = state.sessionId ? `Session ${state.sessionId}` : "";
  const root = document.querySelector(`[data-screen="${name}"]`);
  try {
    await screens[name](root, {state, api, show, notify, refreshSession});
  } catch (error) {
    notify(error.message || "Something went wrong.");
  }
}

async function boot() {
  try {
    [state.games, state.questions] = await Promise.all([api.getGames(), api.getQuestions()]);
    await show("game");
  } catch (error) {
    notify(`Couldn't connect to the game server: ${error.message}`);
  }
}

boot();
