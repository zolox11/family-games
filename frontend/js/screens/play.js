import {startRecording, stopRecording, recordingActive, cue, getCues} from "../recorder.js";
import {countdown} from "../timer.js";

const esc = (value) => String(value).replace(/[&<>"']/g, (char) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
let cancelCountdown;
let musicTimer;
let audioContext;

export async function renderPlay(root, {state, show, notify, refreshSession}) {
  if (!state.session) return show("game");
  await refreshSession();
  const session = state.session;
  const game = state.game;
  const player = session.players.find((p) => p.id === session.turn);
  const teamLabel = session.teams && ["A", "B"].includes(session.turn) ? `Team ${session.turn}` : "";
  let prompt = "";
  if (game.id === "say_it_right") {
    const question = state.questions.find((item) => item.id === state.questionId) || state.questions[(session.round - 1) % state.questions.length];
    state.questionId = question.id;
    prompt = `<div class="card"><span class="badge">Question ${question.id.toUpperCase()}</span><h2 dir="auto">${esc(question.q_en)}</h2><p dir="auto" lang="ar" class="muted" style="font-size:20px">${esc(question.q_ar)}</p><p class="small muted">Answer in Arabic or English.</p><button class="btn light" id="promptCue">Show question & start 3-second countdown</button></div>`;
  } else if (game.id === "hand_duel") {
    prompt = `<div class="callout"><b>Falcon</b> ✌️ beats Dhow · <b>Dhow</b> 🖐️ beats Dallah · <b>Dallah</b> ✊ beats Falcon. Show your sign together on GO.</div>`;
  } else if (game.id === "majlis_freeze") {
    prompt = `<div class="callout">Dance while the music plays. Freeze when it stops. The host can mark the stop cue, or the AI will look for the audio drop.</div>`;
  } else if (game.id === "football") {
    prompt = `<div class="callout">Start the camera at the sideline. After recording, mark each goal and tap each player's starting position so the judge can identify them.</div>`;
  } else {
    prompt = `<div class="callout">Mark the bucket opening and tap the bean bag in the first frame before running the judge.</div>`;
  }
  root.innerHTML = `
    <div class="eyebrow">Step 4 · Round in play</div><h1>Let the game begin!</h1>
    <div class="columns">
      <div class="panel">
        <div class="button-row" style="margin-top:0;justify-content:space-between"><span class="badge">Round ${session.round} of ${session.total_rounds}</span><span class="badge">${esc(teamLabel || player?.name || "Your turn")}</span></div>
        <div class="scoreboard">${Object.entries(session.scores).map(([id, score]) => `<div class="score"><span>${session.teams ? `Team ${id}` : esc(session.players.find((p) => p.id === id)?.name || id)}</span><strong>${score}</strong></div>`).join("")}</div>
        <div id="playTimer" class="timer" aria-live="polite"></div>
        <div class="live-wrap"><video id="livePreview" autoplay playsinline muted></video></div>
        <div class="button-row">
          <button class="btn primary" id="startRecord">● Start recording</button>
          <button class="btn light" id="stopRecord" disabled>■ Stop & keep clip</button>
        </div>
        <label class="field"><span>Or choose a recorded video clip</span><input id="videoFile" type="file" accept="video/mp4,video/webm,video/quicktime"></label>
        <div class="cue-row">
          ${game.id === "majlis_freeze" ? `<button class="btn light" id="musicButton">♫ Start music & auto-stop</button><button class="btn outline" data-cue="music_stop">Music stopped</button>` : ""}
          ${game.id === "hand_duel" ? `<button class="btn light" id="goButton">3-2-1-GO</button>` : ""}
          ${game.id === "bucket_toss" ? `<select id="thrower" aria-label="Current thrower">${session.players.map((p) => `<option value="${p.id}" ${p.id === (state.thrower || session.players[0].id) ? "selected" : ""}>${esc(p.name)}'s turn</option>`).join("")}</select><button class="btn outline" id="turnStart">Start this turn</button><button class="btn outline" id="turnEnd">End this turn</button><button class="btn outline" id="throwButton">Log a throw</button>` : ""}
        </div>
        ${prompt}
      </div>
      <aside class="panel"><h3>Quick guide</h3><p class="muted">${esc(game.rules.text)}</p><p class="small muted">Recording stays on this device until you send the clip to the local judge server. A camera is optional; uploading a clip works too.</p>
        <div class="button-row"><button class="btn light" id="backRules">← Rules</button><button class="btn primary" id="toJudge">Judge this round →</button></div></aside>
    </div>`;
  const start = root.querySelector("#startRecord");
  const stop = root.querySelector("#stopRecord");
  const video = root.querySelector("#livePreview");
  start.addEventListener("click", async () => {
    try {
      await startRecording(video);
      state.clip = null;
      state.cues = {};
      start.disabled = true;
      stop.disabled = false;
      notify("Recording started. Cues are timed against the recording.", "success");
    } catch (error) { notify(error.message); }
  });
  stop.addEventListener("click", async () => {
    try {
      state.clip = await stopRecording();
      state.clipName = `game-round-${session.round}.webm`;
      const recordedCues = getCues();
      state.cues = {...state.cues, ...recordedCues, turns: state.cues.turns || recordedCues.turns || []};
      start.disabled = false;
      stop.disabled = true;
      video.srcObject = null;
      video.src = URL.createObjectURL(state.clip);
      video.controls = true;
      notify("Clip saved. Continue to AI Judge Results.", "success");
    } catch (error) { notify(error.message); }
  });
  root.querySelector("#videoFile").addEventListener("change", (event) => {
    const file = event.target.files[0];
    if (file) {
      state.clip = file;
      state.clipName = file.name;
      state.cues = {};
      notify(`Selected ${file.name}`, "success");
    }
  });
  root.querySelectorAll("[data-cue]").forEach((button) => button.addEventListener("click", () => {
    const type = button.dataset.cue;
    state.cues[`${type}_s`] = recordingActive() ? cue(type) : Number(prompt(`Enter ${type.replace("_", " ")} time in seconds from clip start:`) || 0);
    notify(`${type.replace("_", " ")} cue saved at ${state.cues[`${type}_s`]}s`, "success");
  }));
  root.querySelector("#goButton")?.addEventListener("click", () => {
    cancelCountdown?.();
    cancelCountdown = countdown(3, (n) => { root.querySelector("#playTimer").textContent = n ? String(n) : "GO!"; }, () => {
      if (recordingActive()) state.cues.go_s = cue("go");
      else state.cues.go_s = Number(prompt("GO cue time in seconds from clip start:") || 0);
    });
  });
  root.querySelector("#promptCue")?.addEventListener("click", () => {
    cancelCountdown?.();
    if (recordingActive()) state.cues.prompt_shown_s = cue("prompt_shown");
    cancelCountdown = countdown(3, (n) => { root.querySelector("#playTimer").textContent = n ? String(n) : "Answer!"; }, () => {
      if (!recordingActive()) notify("Now record the player answering, or enter a prompt timestamp on the judge screen.", "success");
    });
  });
  root.querySelector("#musicButton")?.addEventListener("click", async () => {
    if (!recordingActive()) return notify("Start recording before starting the music so the cue time is accurate.");
    try {
      audioContext ||= new AudioContext();
      await audioContext.resume();
      const oscillator = audioContext.createOscillator();
      const gain = audioContext.createGain();
      oscillator.type = "sine"; oscillator.frequency.value = 440; gain.gain.value = 0.045;
      oscillator.connect(gain); gain.connect(audioContext.destination); oscillator.start();
      state.cues.music_stop_s = undefined;
      const duration = 5000 + Math.random() * 5000;
      root.querySelector("#playTimer").textContent = "♫ Music!";
      clearTimeout(musicTimer);
      musicTimer = setTimeout(() => {
        oscillator.stop();
        state.cues.music_stop_s = cue("music_stop");
        root.querySelector("#playTimer").textContent = "Freeze!";
        notify("Music stopped — hold still!", "success");
      }, duration);
    } catch (error) { notify(`Couldn't start audio: ${error.message}`); }
  });
  root.querySelector("#throwButton")?.addEventListener("click", () => {
    state.thrower = root.querySelector("#thrower").value;
    state.throwCount ||= {};
    state.throwCount[state.thrower] = (state.throwCount[state.thrower] || 0) + 1;
    notify(`Logged throw ${state.throwCount[state.thrower]} for ${state.session.players.find((p) => p.id === state.thrower)?.name || state.thrower}.`, "success");
  });
  root.querySelector("#turnStart")?.addEventListener("click", () => {
    state.thrower = root.querySelector("#thrower").value;
    const start_s = recordingActive() ? cue("turn", {player: state.thrower}) : Number(prompt("Turn start in seconds from clip start:") || 0);
    state.cues.turns ||= [];
    state.cues.turns.push({player: state.thrower, start_s, end_s: start_s + 20});
    notify(`Turn started at ${start_s.toFixed(1)}s.`, "success");
  });
  root.querySelector("#turnEnd")?.addEventListener("click", () => {
    const end_s = recordingActive() ? cue("turn_end") : Number(prompt("Turn end in seconds from clip start:") || 0);
    const latest = [...(state.cues.turns || [])].reverse().find((turn) => turn.player === root.querySelector("#thrower").value);
    if (latest) latest.end_s = end_s;
    notify(`Turn ended at ${end_s.toFixed(1)}s.`, "success");
  });
  root.querySelector("#backRules").addEventListener("click", () => show("rules"));
  root.querySelector("#toJudge").addEventListener("click", async () => {
    if (recordingActive()) return notify("Stop the recording before moving to the judge.");
    if (!state.clip) return notify("Record a clip or choose a video file first.");
    await show("judge");
  });
}
