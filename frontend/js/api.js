async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail || data.error || `Request failed (${response.status})`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

export const getGames = () => request("/api/games");
export const getQuestions = () => request("/api/questions");
export const createSession = (body) => request("/api/session", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
export const getSession = (id) => request(`/api/session/${encodeURIComponent(id)}`);
export const updateRules = (id, rules) => request(`/api/session/${encodeURIComponent(id)}/rules`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({rules})});
export const nextTurn = (id) => request(`/api/session/${encodeURIComponent(id)}/next`, {method: "POST"});
export const getResults = (id) => request(`/api/session/${encodeURIComponent(id)}/results`);
export const applyReport = (id, body) => request(`/api/session/${encodeURIComponent(id)}/apply`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});

export function judgeVideo(id, file, config) {
  const form = new FormData();
  form.append("video", file, file.name || "game-clip.webm");
  form.append("config", JSON.stringify(config));
  return request(`/api/session/${encodeURIComponent(id)}/judge`, {method: "POST", body: form});
}
