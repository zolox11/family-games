import hashlib
import math
import time
from collections import Counter, deque
from pathlib import Path

from . import audio, vision
from server.games import QUESTION_BANK
from server.signing import sign

CONFIG = {
    "stride": 2,
    "imgsz": 960,
    "goal_frames": 5,
    "goal_cooldown_s": 3.0,
    "ball_hold_frames": 10,
    "possession_radius": 0.6,
    "freeze_grace_s": 0.5,
    "hand_agreement": 0.60,
    "hand_min_frames": 5,
    "bucket_cooldown_s": 1.0,
}
JUDGE_VERSION = "1.0"


def _center(box):
    x1, y1, x2, y2 = box["xyxy"]
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def _point_in_roi(point, roi, shape):
    if not roi:
        return False
    h, w = shape[:2]
    x1, y1, x2, y2 = roi
    return x1 * w <= point[0] <= x2 * w and y1 * h <= point[1] <= y2 * h


def _team_for_player(player, teams):
    return next((team for team, members in (teams or {}).items() if player in members), None)


def _output(video_writer):
    return str(video_writer.close()) if video_writer else None


def judge_football(video_path, config):
    stream = iter(vision.track_video(video_path, [0, 32], stride=CONFIG["stride"], imgsz=CONFIG["imgsz"]))
    initial = []
    for _ in range(15):
        try:
            initial.append(next(stream))
        except StopIteration:
            break
    if not initial:
        raise ValueError("No readable frames were found in this video.")
    id_map = vision.map_seeds(initial, config.get("seeds", {}))
    if not id_map:
        player_ids = config.get("players", [])
        if player_ids:
            first_ids = sorted({b["id"] for _, _, _, boxes in initial for b in boxes if b["cls"] == 0 and b["id"] >= 0})
            id_map = dict(zip(first_ids, player_ids))
    teams = config.get("teams") or {}
    goals = {"A": 0, "B": 0}
    possession = Counter()
    events, warnings = [], []
    trail = deque(maxlen=30)
    writer = vision.VideoWriter(video_path, 15)
    last_ball, missing_ball, last_holder = None, 0, None
    goal_streak, last_goal_time = Counter(), -999.0
    frames, ball_frames = 0, 0
    try:
        for frame_idx, t, frame, boxes in _chain(initial, stream):
            frames += 1
            persons = [b for b in boxes if b["cls"] == 0]
            ball_candidates = [b for b in boxes if b["cls"] == 32]
            ball = max(ball_candidates, key=lambda b: b["conf"]) if ball_candidates else None
            if ball:
                ball_center = _center(ball)
                last_ball, missing_ball = ball_center, 0
                ball_frames += 1
                trail.append(ball_center)
            else:
                missing_ball += 1
                ball_center = last_ball if missing_ball <= CONFIG["ball_hold_frames"] else None
            if ball_center:
                closest, distance = None, float("inf")
                for person in persons:
                    player = id_map.get(person["id"])
                    if not player:
                        continue
                    x1, y1, x2, y2 = person["xyxy"]
                    feet = ((x1 + x2) / 2, y2)
                    candidate = math.dist(feet, ball_center)
                    if candidate < distance and candidate < CONFIG["possession_radius"] * max(1, y2 - y1):
                        closest, distance = player, candidate
                if closest:
                    possession[closest] += 1
                    last_holder = closest
            for defending_team in ("A", "B"):
                roi = config.get("rois", {}).get(f"goal_{defending_team}")
                goal_streak[defending_team] = goal_streak[defending_team] + 1 if ball_center and _point_in_roi(ball_center, roi, frame.shape) else 0
                if goal_streak[defending_team] >= CONFIG["goal_frames"] and t - last_goal_time >= CONFIG["goal_cooldown_s"]:
                    scoring_team = "B" if defending_team == "A" else "A"
                    goals[scoring_team] += 1
                    scorer_team = _team_for_player(last_holder, teams)
                    player_credit = last_holder if scorer_team == scoring_team else None
                    text = f"Ball entered Team {defending_team}'s goal"
                    text += f" after {player_credit} had possession" if player_credit else " (own goal or scorer not identified)"
                    events.append({"t": round(t, 2), "type": "goal", "team": scoring_team, "player": player_credit, "reason": text})
                    last_goal_time = t
                    goal_streak.clear()
            label_map = {track_id: player for track_id, player in id_map.items()}
            if ball:
                label_map[ball["id"]] = "BALL"
            annotated = vision.draw_overlay(frame, boxes, label_map, trail, f"Team A {goals['A']}  -  {goals['B']} Team B", config.get("rois"))
            writer.write(annotated)
    except Exception:
        writer.close()
        raise
    annotated_path = _output(writer)
    total_possession = sum(possession.values())
    team_counts = {team: sum(possession[p] for p in members) for team, members in teams.items()}
    team_pct = {team: round(count / total_possession * 100, 1) if total_possession else 0.0 for team, count in team_counts.items()}
    if frames and ball_frames / frames < 0.5:
        warnings.append("ball visibility low, try a closer camera angle")
    scorer_counts = Counter(e.get("player") for e in events if e.get("player"))
    mvp = max(possession, key=lambda player: (possession[player], scorer_counts[player])) if possession else None
    return {"events": events, "stats": {"possession_frames": dict(possession), "team_possession_pct": team_pct, "most_possession_team": max(team_pct, key=team_pct.get) if team_pct and max(team_pct.values()) > 0 else None, "mvp": mvp, "warnings": warnings, "frames_analyzed": frames, "ball_detection_pct": round(ball_frames / frames * 100, 1) if frames else 0}, "score_delta": goals, "summary": f"Team A scored {goals['A']} goal(s); Team B scored {goals['B']} goal(s).", "annotated_video_path": annotated_path}


def _chain(first, remainder):
    yield from first
    yield from remainder


def judge_majlis_freeze(video_path, config):
    stop = config.get("cues", {}).get("music_stop_s")
    if stop is None:
        wav = audio.extract_audio(video_path)
        try:
            stop = audio.music_stop_time(wav)
        finally:
            Path(wav).unlink(missing_ok=True)
    if stop is None:
        raise ValueError("Could not find a music-stop cue or a clear music stop in the audio. Add music_stop_s in the judge screen.")
    window = float(config.get("rules", {}).get("freeze_window_s", 5))
    stream = iter(vision.pose_video(video_path, stride=CONFIG["stride"]))
    initial = []
    for _ in range(15):
        try:
            initial.append(next(stream))
        except StopIteration:
            break
    if not initial:
        raise ValueError("No pose frames could be read from this video.")
    pseudo_boxes = [(i, t, f, [{"id": p["id"], "xyxy": p["xyxy"]} for p in people]) for i, t, f, people in initial]
    id_map = vision.map_seeds(pseudo_boxes, config.get("seeds", {}))
    if not id_map:
        id_map = dict(zip(sorted({p["id"] for _, _, _, people in initial for p in people}), config.get("players", [])))
    motions, previous = {}, {}
    writer = vision.VideoWriter(video_path, 15)
    try:
        for frame_idx, t, frame, people in _chain(initial, stream):
            if stop + CONFIG["freeze_grace_s"] <= t <= stop + window:
                for person in people:
                    player = id_map.get(person["id"])
                    points = person["kpts"]
                    if not player or len(points) < 7 or points[5][2] <= 0.5 or points[6][2] <= 0.5:
                        continue
                    shoulder = math.dist(points[5][:2], points[6][:2])
                    if shoulder < 0.001:
                        continue
                    valid = {index: point[:2] for index, point in enumerate(points) if point[2] > 0.5}
                    common = valid.keys() & previous.get(player, {}).keys()
                    if len(common) >= 5:
                        motion = sum(math.dist(valid[index], previous[player][index]) for index in common) / len(common) / shoulder
                        motions.setdefault(player, []).append((t, motion))
                    previous[player] = valid
            labels = {p["id"]: id_map.get(p["id"], "Player") for p in people}
            draw_boxes = [{"id": p["id"], "cls": 0, "xyxy": p["xyxy"]} for p in people]
            writer.write(vision.draw_overlay(frame, draw_boxes, labels, banner_text=f"Freeze window starts at {stop:.1f}s"))
    except Exception:
        writer.close()
        raise
    annotated = _output(writer)
    averages = {player: sum(value for _, value in values) / len(values) for player, values in motions.items() if values}
    limit = float(config.get("rules", {}).get("max_motion", 0.04))
    eligible = {p: value for p, value in averages.items() if value <= limit}
    winner = min(eligible, key=eligible.get) if eligible else None
    events = [{"t": round(float(stop), 2), "type": "music_stop", "reason": "Music stopped; freeze window began."}]
    for player, values in motions.items():
        if averages.get(player, 0) > limit:
            peak_t, peak = max(values, key=lambda item: item[1])
            events.append({"t": round(peak_t, 2), "type": "player_moved", "player": player, "reason": f"{player} moved during the freeze window (motion {averages[player]:.3f}, limit {limit:.3f})."})
    points = int(config.get("rules", {}).get("points_per_round_win", 1))
    scores = {p: 0 for p in config.get("players", [])}
    output_winner = winner
    team_motion = {}
    if config.get("teams"):
        team_motion = {team: sum(averages[p] for p in members if p in averages) / len([p for p in members if p in averages]) for team, members in config["teams"].items() if any(p in averages for p in members)}
        qualified = {team: value for team, value in team_motion.items() if value <= limit}
        output_winner = min(qualified, key=qualified.get) if qualified else None
        scores = {team: 0 for team in config["teams"]}
        if output_winner:
            scores[output_winner] = points
    elif winner:
        scores[winner] = points
    if output_winner:
        if config.get("teams"):
            events.append({"t": round(float(stop + window), 2), "type": "round_winner", "team": output_winner, "reason": f"Team {output_winner} held the steadiest freeze (mean motion {team_motion[output_winner]:.3f})."})
        else:
            events.append({"t": round(float(stop + window), 2), "type": "round_winner", "player": output_winner, "reason": f"{output_winner} held the steadiest freeze (motion {averages[output_winner]:.3f})."})
    return {"events": events, "stats": {"motion_score": {p: round(v, 4) for p, v in averages.items()}, "team_motion_score": team_motion, "max_motion": limit, "music_stop_s": stop}, "score_delta": scores, "summary": f"{'Team ' if config.get('teams') else ''}{output_winner} wins the freeze round." if output_winner else "No player or team met the freeze movement limit.", "annotated_video_path": annotated}


def judge_say_it_right(video_path, config):
    question = next((q for q in QUESTION_BANK if q["id"] == config.get("question_id")), None)
    if question is None:
        raise ValueError("Select a valid heritage question before judging.")
    wav = audio.extract_audio(video_path)
    try:
        transcript = audio.transcribe(wav)
    finally:
        Path(wav).unlink(missing_ok=True)
    text = transcript["text"]
    score, answer = audio.match(text, question["answers"]) if text else (0.0, "")
    threshold = float(config.get("rules", {}).get("threshold", 80))
    correct = bool(text) and score >= threshold
    segments = transcript["segments"]
    prompt = float(config.get("cues", {}).get("prompt_shown_s", 0))
    raw_delay = segments[0]["start"] - prompt if segments else None
    delay = max(0.0, raw_delay) if raw_delay is not None else None
    points = int(config.get("rules", {}).get("points_correct", 1)) if correct else 0
    if correct and raw_delay is not None and 0 <= raw_delay <= float(config.get("rules", {}).get("speed_bonus_s", 5)):
        points += int(config.get("rules", {}).get("speed_bonus", 1))
    player = config.get("players", ["P1"])[0]
    if text:
        event = {"t": round(segments[0]["start"], 2) if segments else 0, "type": "answer_correct" if correct else "answer_incorrect", "player": player, "reason": f"Heard '{text}' (match {round(score)}) for '{question['q_en']}'."}
    else:
        event = {"t": 0, "type": "no_speech", "player": player, "reason": "No speech was detected. Please record the answer again."}
    return {"events": [event], "stats": {"transcript": text, "language": transcript["language"], "match_score": round(score, 1), "matched_answer": answer, "response_delay_s": round(delay, 2) if delay is not None else None, "question": question}, "score_delta": {player: points}, "summary": f"{'Correct answer' if correct else 'No point'} for {player}.", "annotated_video_path": None}


def _gesture(points):
    wrist = points[0]
    tips, pips = (8, 12, 16, 20), (6, 10, 14, 18)
    extended = [math.dist(points[tip][:2], wrist[:2]) > math.dist(points[pip][:2], wrist[:2]) * 1.1 for tip, pip in zip(tips, pips)]
    count = sum(extended)
    if count == 0:
        return "dallah"
    if extended == [True, True, False, False]:
        return "falcon"
    if count == 4:
        return "dhow"
    return "unknown"


def judge_hand_duel(video_path, config):
    detections = list(vision.hands_video(video_path, stride=1))
    annotated = vision.annotate_hand_detections(video_path, detections)
    cues = config.get("cues", {})
    go = cues.get("go_s")
    if go is None:
        go = next((t for t, hands in detections if len(hands) == 2), None)
    if go is None:
        return {"events": [{"t": 0, "type": "unclear_gesture", "reason": "Both hands were not visible. Please replay the round."}], "stats": {"gestures": {}, "replay": True}, "score_delta": {"P1": 0, "P2": 0}, "summary": "Replay: both players' hands were not visible.", "annotated_video_path": annotated}
    sample_window = config.get("rules", {}).get("sample_window", [0.3, 2.0])
    samples = {"P1": [], "P2": []}
    for t, hands in detections:
        if not go + sample_window[0] <= t <= go + sample_window[1]:
            continue
        for hand in hands:
            player = "P1" if hand["wrist_xy"][0] < 0.5 else "P2"
            samples[player].append(_gesture(hand["landmarks"]))
    gestures = {}
    for player, values in samples.items():
        known = [g for g in values if g != "unknown"]
        counts = Counter(known)
        gesture, amount = counts.most_common(1)[0] if counts else ("unclear", 0)
        gestures[player] = gesture if len(values) >= CONFIG["hand_min_frames"] and amount / max(1, len(known)) >= CONFIG["hand_agreement"] else "unclear"
    score = {"P1": 0, "P2": 0}
    events = []
    first, second = gestures["P1"], gestures["P2"]
    if "unclear" in gestures.values():
        events.append({"t": round(float(go), 2), "type": "unclear_gesture", "reason": "A gesture was unclear or visible in fewer than five frames. Replay the round."})
        summary = "Replay: gesture recognition was unclear."
    else:
        beats = {"dallah": "falcon", "falcon": "dhow", "dhow": "dallah"}
        winner = "P1" if beats[first] == second else "P2" if beats[second] == first else None
        if winner:
            score[winner] = 1
            reason = f"P1 showed {first.title()}, P2 showed {second.title()}: {first.title() if winner == 'P1' else second.title()} beats {second.title() if winner == 'P1' else first.title()}."
            summary = f"{winner} wins this duel."
        else:
            reason = f"Both players showed {first.title()}; replay the tie."
            summary = "Tie: replay the round."
        events.append({"t": round(float(go), 2), "type": "duel_result", "winner": winner, "reason": reason})
    return {"events": events, "stats": {"gestures": gestures, "sample_frames": {p: len(v) for p, v in samples.items()}, "replay": "unclear" in gestures.values() or first == second}, "score_delta": score, "summary": summary, "annotated_video_path": annotated}


def judge_bucket_toss(video_path, config):
    if vision.cv2 is None:
        raise RuntimeError("OpenCV is required for bucket tracking; install requirements.txt")
    cv2, np = vision.cv2, vision.np
    cap, fps = vision._open(video_path)
    ok, first = cap.read()
    if not ok:
        cap.release()
        raise ValueError("No readable frames were found in this video.")
    first = vision._resize(first, 960)
    h, w = first.shape[:2]
    seed = config.get("seeds", {}).get("object")
    if not seed:
        cap.release()
        raise ValueError("Tap the bean bag in the first frame to set its colour.")
    sx, sy = int(seed[0] * w), int(seed[1] * h)
    hsv_first = cv2.cvtColor(first, cv2.COLOR_BGR2HSV)
    sample = hsv_first[max(0, sy - 4):min(h, sy + 5), max(0, sx - 4):min(w, sx + 5)]
    if sample.size == 0:
        cap.release()
        raise ValueError("The bean-bag colour tap was outside the video frame.")
    hue, sat, val = [int(x) for x in np.median(sample.reshape(-1, 3), axis=0)]
    low_h, high_h = (hue - 12) % 180, (hue + 12) % 180
    roi = config.get("rois", {}).get("bowl")
    if not roi:
        cap.release()
        raise ValueError("Draw the bucket opening area before judging.")
    writer = vision.VideoWriter(video_path, fps / 2)
    events, scores, attempts = [], Counter(), Counter()
    candidates = []
    turn_windows = config.get("cues", {}).get("turns", [])
    cooldown = -999.0
    pending, inside_frames, was_inside = None, 0, False
    last_point = None
    index = 0
    frame = first
    try:
        while frame is not None:
            current_t = index / fps
            current_hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            smin, vmin = max(80, sat - 60), max(80, val - 70)
            if low_h <= high_h:
                mask = cv2.inRange(current_hsv, np.array([low_h, smin, vmin]), np.array([high_h, 255, 255]))
            else:
                m1 = cv2.inRange(current_hsv, np.array([0, smin, vmin]), np.array([high_h, 255, 255]))
                m2 = cv2.inRange(current_hsv, np.array([low_h, smin, vmin]), np.array([179, 255, 255]))
                mask = cv2.bitwise_or(m1, m2)
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            contour = max(contours, key=cv2.contourArea) if contours else None
            point = None
            if contour is not None and 12 <= cv2.contourArea(contour) <= frame.shape[0] * frame.shape[1] * 0.03:
                moments = cv2.moments(contour)
                if moments["m00"]:
                    point = (moments["m10"] / moments["m00"], moments["m01"] / moments["m00"])
                    if last_point is not None:
                        point = (0.65 * point[0] + 0.35 * last_point[0], 0.65 * point[1] + 0.35 * last_point[1])
                    candidates.append((current_t, point))
            last_point = point
            in_roi = point is not None and _point_in_roi(point, roi, frame.shape)
            if point and not was_inside and in_roi and candidates and len(candidates) > 1:
                prev = candidates[-2][1]
                if point[1] > prev[1]:
                    pending, inside_frames = current_t, 1
            elif pending is not None and in_roi:
                inside_frames += 1
            elif pending is not None and point is None:
                if current_t - cooldown >= CONFIG["bucket_cooldown_s"]:
                    _record_toss(config, turn_windows, pending, scores, attempts, events, goals=True)
                    cooldown = current_t
                pending = None
            elif pending is not None and not in_roi and current_t - pending < 1:
                _record_toss(config, turn_windows, pending, scores, attempts, events, goals=False)
                pending = None
            if pending is not None and inside_frames >= 4 and current_t - cooldown >= CONFIG["bucket_cooldown_s"]:
                _record_toss(config, turn_windows, pending, scores, attempts, events, goals=True)
                cooldown = current_t
                pending = None
            was_inside = in_roi
            annotated = vision.draw_overlay(frame.copy(), [], ball_trail=[point] if point else [], banner_text=f"Bucket hits: {sum(scores.values())}", rois={"bowl": roi})
            writer.write(annotated)
            index += 2
            frame = None
            for _ in range(2):
                ok, next_frame = cap.read()
                if not ok:
                    break
                frame = vision._resize(next_frame, 960)
    except Exception:
        writer.close()
        raise
    finally:
        cap.release()
    annotated = _output(writer)
    players = config.get("players", [])
    for p in players:
        attempts[p] = max(attempts[p], int(config.get("throw_count", {}).get(p, 0)))
    hit_counts = dict(scores)
    score_delta = {}
    if config.get("teams"):
        for team, members in config["teams"].items():
            score_delta[team] = sum(scores[p] for p in members)
    else:
        score_delta = {p: scores[p] for p in players}
    accuracy = {p: round(scores[p] / attempts[p] * 100, 1) if attempts[p] else 0 for p in players}
    return {"events": events, "stats": {"hits_per_player": hit_counts, "attempts_per_player": dict(attempts), "accuracy_pct": accuracy}, "score_delta": score_delta, "summary": f"{sum(scores.values())} bucket hit(s) recorded.", "annotated_video_path": annotated}


def _player_at(turns, t, config):
    player = next((row.get("player") for row in turns if float(row.get("start_s", 0)) <= t <= float(row.get("end_s", 0))), None)
    return player or (config.get("players") or ["P1"])[0]


def _record_toss(config, turns, t, scores, attempts, events, goals):
    player = _player_at(turns, t, config)
    if goals:
        scores[player] += 1
        events.append({"t": round(t, 2), "type": "score", "player": player, "reason": f"Bean bag entered the bucket at {int(t // 60):02d}:{int(t % 60):02d} during {player}'s turn."})
    else:
        events.append({"t": round(t, 2), "type": "miss", "player": player, "reason": f"The bean bag missed the bucket during {player}'s turn."})
    attempts[player] += 1


JUDGES = {
    "football": judge_football,
    "majlis_freeze": judge_majlis_freeze,
    "say_it_right": judge_say_it_right,
    "hand_duel": judge_hand_duel,
    "bucket_toss": judge_bucket_toss,
}


def run_judge(game_id, video_path, config):
    if game_id not in JUDGES:
        raise ValueError(f"Unknown game: {game_id}")
    started = time.monotonic()
    digest = hashlib.sha256()
    with open(video_path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    duration, _ = vision.media_info(video_path)
    result = JUDGES[game_id](video_path, config)
    report = {
        "game": game_id,
        "session_id": config["session_id"],
        "round": int(config.get("round", 1)),
        "video_sha256": digest.hexdigest(),
        "judge_version": JUDGE_VERSION,
        "duration_s": round(duration, 2),
        "events": result.get("events", []),
        "stats": result.get("stats", {}),
        "score_delta": result.get("score_delta", {}),
        "summary": result.get("summary", ""),
    }
    signature = sign(report)
    print(f"Judge {game_id}: {duration:.1f}s clip processed in {time.monotonic() - started:.1f}s")
    return {"report": report, "signature": signature, "annotated_video_path": result.get("annotated_video_path")}
