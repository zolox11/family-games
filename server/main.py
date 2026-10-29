import json
import logging
import secrets
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from judge.judges import run_judge
from server.games import GAMES
from server.models import ApplyRequest, JudgeConfig, RulesUpdate, SESSIONS, SESSIONS_LOCK, SessionCreate, SessionState
from server.signing import verify

ROOT = Path(__file__).resolve().parents[1]
UPLOADS = ROOT / "uploads"
OUTPUTS = ROOT / "outputs"
POSITIVE_RULES = {"match_s", "rounds", "rounds_per_player", "freeze_window_s", "throws_per_player", "turn_time_s"}
UPLOADS.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
app = FastAPI(title="Family AI Game Day", version="1.0")


@app.get("/api/games")
def games():
    return [{"id": game_id, **game} for game_id, game in GAMES.items()]


@app.get("/api/questions")
def questions():
    from server.games import QUESTION_BANK
    return QUESTION_BANK


@app.post("/api/session")
def create_session(payload: SessionCreate):
    if payload.game_id not in GAMES:
        raise HTTPException(400, detail="unknown_game")
    game = GAMES[payload.game_id]
    ids = {player.id for player in payload.players}
    if payload.game_id == "hand_duel" and len(payload.players) != 2:
        raise HTTPException(400, detail="hand_duel_requires_two_players")
    teams = payload.teams if game["mode"] == "team" or (game["mode"] == "both" and payload.teams) else None
    if game["mode"] == "team" and teams is None:
        raise HTTPException(400, detail="teams_required")
    if teams is not None:
        assigned = teams.get("A", []) + teams.get("B", [])
        if set(teams) != {"A", "B"} or set(teams["A"]) & set(teams["B"]) or set(assigned) != ids or len(assigned) != len(ids):
            raise HTTPException(400, detail="teams_must_assign_each_player_once")
    rules = {key: value for key, value in game["rules"].items() if key != "text"}
    for key, value in payload.rules.items():
        if key not in rules or not isinstance(value, (int, float)) or isinstance(value, bool):
            raise HTTPException(400, detail="invalid_rules")
        if key in POSITIVE_RULES and value < 1:
            raise HTTPException(400, detail="invalid_rules")
        rules[key] = max(0, min(value, 3600))
    if payload.game_id == "football":
        total_rounds = 1
    elif payload.game_id == "say_it_right":
        total_rounds = int(rules["rounds_per_player"]) * len(payload.players)
    elif payload.game_id == "hand_duel":
        total_rounds = int(rules["rounds"])
    else:
        total_rounds = int(rules.get("rounds", 1))
    if teams:
        score_keys = list(teams)
        first_turn = "A"
    else:
        score_keys = [player.id for player in payload.players]
        first_turn = payload.players[0].id
    state = SessionState(game_id=payload.game_id, players=payload.players, teams=teams, rules=rules, total_rounds=max(1, total_rounds), turn=first_turn, scores={key: 0 for key in score_keys})
    session_id = secrets.token_urlsafe(6)
    with SESSIONS_LOCK:
        SESSIONS[session_id] = state
    return {"session_id": session_id, "state": state.model_dump()}


def _session_or_404(session_id):
    state = SESSIONS.get(session_id)
    if state is None:
        raise HTTPException(404, detail="session_not_found")
    return state


@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    with SESSIONS_LOCK:
        return _session_or_404(session_id).model_dump()


@app.post("/api/session/{session_id}/rules")
def update_rules(session_id: str, payload: RulesUpdate):
    rules = payload.rules
    with SESSIONS_LOCK:
        state = _session_or_404(session_id)
        allowed = GAMES[state.game_id]["rules"]
        for key, value in rules.items():
            if key not in state.rules or (key in POSITIVE_RULES and value < 1):
                raise HTTPException(400, detail="invalid_rules")
        state.rules.update({key: value for key, value in rules.items() if key in allowed})
        if state.game_id == "say_it_right":
            state.total_rounds = int(state.rules["rounds_per_player"]) * len(state.players)
        elif state.game_id != "football" and "rounds" in state.rules:
            state.total_rounds = int(state.rules["rounds"])
        return state.model_dump()


@app.post("/api/session/{session_id}/judge")
async def judge_video(session_id: str, video: UploadFile = File(...), config: str = Form(...)):
    try:
        config_data = json.loads(config)
        judge_config = JudgeConfig.model_validate(config_data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise HTTPException(400, detail=f"invalid_config: {exc}") from exc
    with SESSIONS_LOCK:
        state = _session_or_404(session_id)
        if judge_config.session_id != session_id or judge_config.game != state.game_id:
            raise HTTPException(400, detail="wrong_session")
        judge_config.round = state.round
        judge_config.players = [player.id for player in state.players]
        judge_config.teams = state.teams
        judge_config.rules = state.rules
        state.status = "judging"
    content_types = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}
    media_type = (video.content_type or "").split(";", 1)[0].strip().lower()
    extension = content_types.get(media_type)
    if not extension:
        with SESSIONS_LOCK:
            state.status = "playing"
        raise HTTPException(400, detail=f"unsupported_video_type: {video.content_type or 'unknown'}")
    path = UPLOADS / f"{uuid.uuid4().hex}{extension}"
    total = 0
    try:
        with path.open("wb") as target:
            while chunk := await video.read(1024 * 1024):
                total += len(chunk)
                if total > 300 * 1024 * 1024:
                    raise HTTPException(413, detail="video_too_large")
                target.write(chunk)
        if total == 0:
            raise HTTPException(400, detail="empty_video")
        result = await run_in_threadpool(run_judge, state.game_id, str(path), judge_config.model_dump())
        annotated = result.get("annotated_video_path")
        url = f"/outputs/{Path(annotated).name}" if annotated else None
        return {"report": result["report"], "signature": result["signature"], "annotated_video_url": url}
    except HTTPException:
        raise
    except (RuntimeError, ValueError) as exc:
        logging.exception("Judge failed for session %s", session_id)
        raise HTTPException(422, detail=str(exc)) from exc
    except Exception as exc:
        logging.exception("Unexpected judge failure for session %s", session_id)
        raise HTTPException(500, detail="judge_failed") from exc
    finally:
        path.unlink(missing_ok=True)
        with SESSIONS_LOCK:
            if session_id in SESSIONS and SESSIONS[session_id].status == "judging":
                SESSIONS[session_id].status = "playing"


@app.post("/api/session/{session_id}/apply")
def apply_results(session_id: str, payload: ApplyRequest):
    if not verify(payload.report, payload.signature):
        raise HTTPException(400, detail="signature_invalid")
    with SESSIONS_LOCK:
        state = _session_or_404(session_id)
        report = payload.report
        if report.get("session_id") != session_id:
            raise HTTPException(400, detail="wrong_session")
        replay_key = f"{report.get('video_sha256', '')}:{report.get('round', '')}"
        if not report.get("video_sha256") or replay_key in state.applied_hashes:
            raise HTTPException(400, detail="already_applied")
        if report.get("game") != state.game_id or not isinstance(report.get("score_delta"), dict):
            raise HTTPException(400, detail="invalid_report")
        for key, amount in report["score_delta"].items():
            if key not in state.scores or isinstance(amount, bool) or not isinstance(amount, int) or not 0 <= amount <= 100:
                raise HTTPException(400, detail="invalid_score_delta")
        for key, amount in report["score_delta"].items():
            state.scores[key] += int(amount)
        state.applied_hashes.append(replay_key)
        state.history.append({"game": report["game"], "round": report["round"], "summary": report.get("summary", ""), "events": report.get("events", []), "stats": report.get("stats", {})})
        state.status = "playing"
        return {"ok": True, "state": state.model_dump()}


@app.post("/api/session/{session_id}/next")
def next_turn(session_id: str):
    with SESSIONS_LOCK:
        state = _session_or_404(session_id)
        if state.status == "finished":
            return {"state": state.model_dump()}
        if state.round >= state.total_rounds:
            state.status = "finished"
            state.turn = None
            return {"state": state.model_dump()}
        state.round += 1
        if state.teams:
            state.turn = "B" if state.turn == "A" else "A"
        elif state.game_id == "say_it_right":
            player_round = (state.round - 1) // int(state.rules["rounds_per_player"])
            state.turn = state.players[player_round % len(state.players)].id
        else:
            state.turn = state.players[(state.round - 1) % len(state.players)].id
        return {"state": state.model_dump()}


@app.get("/api/session/{session_id}/results")
def results(session_id: str):
    with SESSIONS_LOCK:
        state = _session_or_404(session_id)
        high = max(state.scores.values(), default=0)
        winners = [name for name, value in state.scores.items() if value == high]
        winner = winners[0] if high > 0 and len(winners) == 1 else ("Draw" if len(winners) > 1 else None)
        mvp = None
        if state.game_id == "football" and state.history:
            mvp_id = state.history[-1].get("stats", {}).get("mvp")
            mvp = next((p.name for p in state.players if p.id == mvp_id), None)
        return {"winner": winner, "scores": state.scores, "match_facts": state.history, "mvp": mvp}


@app.get("/outputs/{filename}")
def output_video(filename: str):
    if Path(filename).name != filename:
        raise HTTPException(404, detail="output_not_found")
    path = OUTPUTS / filename
    if not path.is_file():
        raise HTTPException(404, detail="output_not_found")
    return FileResponse(path, media_type="video/mp4")


app.mount("/", StaticFiles(directory=str(ROOT / "frontend"), html=True), name="static")
