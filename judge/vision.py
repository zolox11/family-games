import subprocess
import threading
import uuid
from collections import deque
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

from .audio import ffmpeg_executable

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
_detector = None
_pose_model = None
_MODEL_LOCK = threading.Lock()


def _require_cv():
    if cv2 is None or np is None:
        raise RuntimeError("OpenCV and numpy are required for video judging; install requirements.txt")


def _model(pose=False):
    global _detector, _pose_model
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("Ultralytics is required for this judge; install requirements.txt") from exc
    if pose:
        if _pose_model is None:
            _pose_model = YOLO("yolo11n-pose.pt")
        return _pose_model
    if _detector is None:
        _detector = YOLO("yolo11n.pt")
    return _detector


def _reset_tracker(model):
    predictor = getattr(model, "predictor", None)
    for tracker in getattr(predictor, "trackers", []):
        tracker.reset()


def _open(path):
    _require_cv()
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("Could not open video. Check that the file is a supported, playable video.")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    return cap, fps


def _resize(frame, width):
    height, frame_width = frame.shape[:2]
    if frame_width > width:
        frame = cv2.resize(frame, (width, round(height * width / frame_width)))
    return frame


def track_video(path, classes, stride=2, imgsz=960):
    cap, fps = _open(path)
    _MODEL_LOCK.acquire()
    try:
        model = _model()
        _reset_tracker(model)
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            current = idx
            idx += 1
            if current % max(1, stride):
                continue
            frame = _resize(frame, imgsz)
            result = model.track(frame, persist=True, tracker="bytetrack.yaml", classes=classes, conf=0.25, imgsz=imgsz, verbose=False)[0]
            boxes = []
            if result.boxes is not None:
                xyxy = result.boxes.xyxy.cpu().numpy()
                clss = result.boxes.cls.cpu().numpy().astype(int)
                confs = result.boxes.conf.cpu().numpy()
                ids = result.boxes.id.cpu().numpy().astype(int) if result.boxes.id is not None else [-1] * len(xyxy)
                for box, cls, conf, track_id in zip(xyxy, clss, confs, ids):
                    boxes.append({"id": int(track_id), "cls": int(cls), "xyxy": box.tolist(), "conf": float(conf)})
            yield current, current / fps, frame, boxes
    finally:
        cap.release()
        _MODEL_LOCK.release()


def pose_video(path, stride=2):
    cap, fps = _open(path)
    _MODEL_LOCK.acquire()
    try:
        model = _model(pose=True)
        _reset_tracker(model)
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            current = idx
            idx += 1
            if current % max(1, stride):
                continue
            frame = _resize(frame, 960)
            result = model.track(frame, persist=True, tracker="bytetrack.yaml", conf=0.25, imgsz=960, verbose=False)[0]
            people = []
            if result.boxes is not None and result.keypoints is not None:
                coordinates = result.keypoints.data.cpu().numpy()
                xyxy = result.boxes.xyxy.cpu().numpy()
                ids = result.boxes.id.cpu().numpy().astype(int) if result.boxes.id is not None else [-1] * len(xyxy)
                for box, track_id, points in zip(xyxy, ids, coordinates):
                    people.append({"id": int(track_id), "xyxy": box.tolist(), "kpts": points.tolist()})
            yield current, current / fps, frame, people
    finally:
        cap.release()
        _MODEL_LOCK.release()


def hands_video(path, stride=1):
    _require_cv()
    try:
        import mediapipe as mp
    except ImportError as exc:
        raise RuntimeError("MediaPipe is required for Hand Duel; install requirements.txt") from exc
    cap, fps = _open(path)
    hands_api = mp.solutions.hands
    idx = 0
    try:
        with hands_api.Hands(max_num_hands=2, min_detection_confidence=0.5, min_tracking_confidence=0.5) as hands:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                current = idx
                idx += 1
                if current % max(1, stride):
                    continue
                frame = _resize(frame, 960)
                result = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                detections = []
                if result.multi_hand_landmarks:
                    for i, hand in enumerate(result.multi_hand_landmarks):
                        points = [[p.x, p.y, p.z] for p in hand.landmark]
                        handedness = result.multi_handedness[i].classification[0].label if result.multi_handedness else "Unknown"
                        detections.append({"wrist_xy": points[0][:2], "landmarks": points, "handedness": handedness})
                yield current / fps, detections
    finally:
        cap.release()


def shirt_hsv(frame, xyxy):
    _require_cv()
    x1, y1, x2, y2 = [int(v) for v in xyxy]
    height, width = frame.shape[:2]
    x1, x2 = max(0, x1), min(width, x2)
    y1, y2 = max(0, y1 + int((y2 - y1) * 0.15)), min(height, y1 + int((y2 - y1) * 0.55))
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return [0.0, 0.0, 0.0]
    pixels = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
    if len(pixels) < 2:
        return pixels.mean(axis=0).tolist()
    try:
        from sklearn.cluster import KMeans
        clusters = KMeans(n_clusters=2, n_init=2, random_state=0).fit(pixels)
        counts = np.bincount(clusters.labels_)
        return clusters.cluster_centers_[int(np.argmax(counts))].tolist()
    except ImportError:
        return np.median(pixels, axis=0).tolist()


def map_seeds(first_frames_boxes, seeds):
    observations = {}
    frame_width, frame_height = None, None
    for _, _, frame, boxes in first_frames_boxes:
        if frame_width is None:
            frame_height, frame_width = frame.shape[:2]
        for box in boxes:
            if box.get("cls") not in (None, 0):
                continue
            if box.get("id", -1) < 0:
                continue
            x1, y1, x2, y2 = box["xyxy"]
            observations.setdefault(box["id"], []).append(((x1 + x2) / 2, (y1 + y2) / 2))
    centers = {track_id: np.mean(points, axis=0) for track_id, points in observations.items()}
    if not seeds or not centers:
        return {}
    try:
        from scipy.optimize import linear_sum_assignment
        ids = list(centers)
        players = list(seeds)
        points = {p: np.array([seeds[p][0] * frame_width, seeds[p][1] * frame_height] if max(seeds[p]) <= 1 else seeds[p], dtype=float) for p in players}
        costs = np.array([[np.linalg.norm(centers[track_id] - points[player]) for track_id in ids] for player in players])
        rows, cols = linear_sum_assignment(costs)
        return {ids[col]: players[row] for row, col in zip(rows, cols)}
    except ImportError:
        remaining = set(centers)
        mapping = {}
        for player, point in seeds.items():
            if not remaining:
                break
            point = [point[0] * frame_width, point[1] * frame_height] if max(point) <= 1 else point
            track_id = min(remaining, key=lambda item: np.linalg.norm(centers[item] - np.array(point)))
            mapping[track_id] = player
            remaining.remove(track_id)
        return mapping


def draw_overlay(frame, boxes, labels=None, ball_trail=None, banner_text="", rois=None):
    _require_cv()
    labels = labels or {}
    for name, roi in (rois or {}).items():
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = [int(v) for v in (roi[0] * w, roi[1] * h, roi[2] * w, roi[3] * h)]
        cv2.rectangle(frame, (x1, y1), (x2, y2), (70, 220, 100), 2)
        cv2.putText(frame, name, (x1, max(20, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (70, 220, 100), 2)
    for box in boxes:
        x1, y1, x2, y2 = map(int, box["xyxy"])
        label = labels.get(box.get("id"), "BALL" if box.get("cls") == 32 else "Player")
        color = (0, 180, 255) if label == "BALL" else (230, 120, 40)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, label, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    points = list(ball_trail or [])
    for i, point in enumerate(points):
        if i % 2 == 0:
            cv2.circle(frame, tuple(map(int, point)), 3, (20, 220, 255), -1)
    if banner_text:
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 38), (15, 37, 64), -1)
        cv2.putText(frame, banner_text[:100], (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
    return frame


def annotate_hand_detections(path, detections):
    cap, fps = _open(path)
    writer = VideoWriter(path, fps)
    by_frame = {round(t * fps): hands for t, hands in detections}
    index = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = _resize(frame, 960)
            for hand in by_frame.get(index, []):
                x, y = hand["wrist_xy"]
                px, py = int(x * frame.shape[1]), int(y * frame.shape[0])
                player = "P1" if x < 0.5 else "P2"
                for landmark in hand["landmarks"]:
                    cv2.circle(frame, (int(landmark[0] * frame.shape[1]), int(landmark[1] * frame.shape[0])), 3, (20, 220, 255), -1)
                cv2.putText(frame, player, (px, max(20, py - 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (70, 220, 100), 2)
            writer.write(frame)
            index += 1
    except Exception:
        writer.close()
        raise
    finally:
        cap.release()
    return str(writer.close())


class VideoWriter:
    def __init__(self, path, fps):
        _require_cv()
        OUTPUTS.mkdir(exist_ok=True)
        self.path = OUTPUTS / f"{uuid.uuid4().hex}.mp4"
        self.temp_path = OUTPUTS / f"{uuid.uuid4().hex}.mp4"
        self.writer = None
        self.fps = max(1, fps)
        self.closed = False

    def write(self, frame):
        if self.writer is None:
            h, w = frame.shape[:2]
            self.writer = cv2.VideoWriter(str(self.temp_path), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (w, h))
            if not self.writer.isOpened():
                raise RuntimeError("Could not create annotated video")
        self.writer.write(frame)

    def close(self):
        if self.closed:
            return self.path
        if self.writer is not None:
            self.writer.release()
            self.writer = None
        try:
            subprocess.run([ffmpeg_executable(), "-y", "-i", str(self.temp_path), "-vcodec", "libx264", "-pix_fmt", "yuv420p", str(self.path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except FileNotFoundError as exc:
            raise RuntimeError("FFmpeg could not be started. Install FFmpeg and add it to PATH.") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("ffmpeg could not encode the annotated video: " + exc.stderr.decode(errors="replace")[-500:]) from exc
        finally:
            self.closed = True
            if self.temp_path.exists():
                self.temp_path.unlink()
        return self.path


def media_info(path):
    cap, fps = _open(path)
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return max(0, frames / fps), fps
