let recorder;
let stream;
let chunks = [];
let t0 = 0;
let cues = {};

export async function startRecording(videoElement) {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    throw new Error("Camera recording is not supported in this browser. Use a video upload instead.");
  }
  stream = await navigator.mediaDevices.getUserMedia({video: {width: 1280, height: 720}, audio: true});
  videoElement.srcObject = stream;
  videoElement.muted = true;
  await videoElement.play();
  const type = [
    "video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus",
    "video/webm",
    "video/mp4",
  ].find((candidate) => MediaRecorder.isTypeSupported(candidate));
  if (!type) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
    throw new Error("This browser cannot record a supported video format. Upload an MP4, WebM, or QuickTime clip instead.");
  }
  recorder = new MediaRecorder(stream, {mimeType: type});
  chunks = [];
  cues = {};
  recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
  t0 = performance.now();
  recorder.start(500);
}

export function cue(name, extra = {}) {
  const seconds = Math.max(0, (performance.now() - t0) / 1000);
  const entry = {t: Number(seconds.toFixed(2)), ...extra};
  if (name === "turn") (cues.turns ||= []).push({...extra, start_s: entry.t});
  else cues[`${name}_s`] = entry.t;
  return entry.t;
}

export function getCues() {
  return structuredClone(cues);
}

export function recordingActive() {
  return recorder?.state === "recording";
}

export function stopRecording() {
  if (!recorder || recorder.state === "inactive") return Promise.reject(new Error("Start a recording first."));
  return new Promise((resolve) => {
    recorder.onstop = () => {
      const blob = new Blob(chunks, {type: recorder.mimeType || "video/webm"});
      stream?.getTracks().forEach((track) => track.stop());
      stream = null;
      resolve(blob);
    };
    recorder.stop();
  });
}

export function stopPreview() {
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
}
