let image;
let active;
let start;
let shapes = {};
let onChange;

export async function prepareCanvas(canvas, blob, existing, changeHandler) {
  shapes = {...existing};
  onChange = changeHandler;
  image = document.createElement("video");
  image.muted = true;
  image.playsInline = true;
  image.preload = "auto";
  const url = URL.createObjectURL(blob);
  await new Promise((resolve, reject) => {
    const ready = () => {
      if (image.readyState >= 2 && image.videoWidth && image.videoHeight) resolve();
    };
    image.onloadedmetadata = () => {
      image.onloadeddata = ready;
      image.onseeked = ready;
      if (image.currentTime !== 0) image.currentTime = 0;
      else ready();
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("This browser cannot decode the first frame of the selected video."));
    };
    image.src = url;
  });
  const scale = Math.min(1, 960 / image.videoWidth);
  canvas.width = Math.round(image.videoWidth * scale);
  canvas.height = Math.round(image.videoHeight * scale);
  draw(canvas);
  canvas.onpointerdown = (event) => {
    if (!active) return;
    const rect = canvas.getBoundingClientRect();
    start = {x: (event.clientX - rect.left) * canvas.width / rect.width, y: (event.clientY - rect.top) * canvas.height / rect.height};
    canvas.setPointerCapture(event.pointerId);
  };
  canvas.onpointerup = (event) => {
    if (!active || !start) return;
    const rect = canvas.getBoundingClientRect();
    const end = {x: (event.clientX - rect.left) * canvas.width / rect.width, y: (event.clientY - rect.top) * canvas.height / rect.height};
    const a = {x: Math.max(0, Math.min(1, start.x / canvas.width)), y: Math.max(0, Math.min(1, start.y / canvas.height))};
    const b = {x: Math.max(0, Math.min(1, end.x / canvas.width)), y: Math.max(0, Math.min(1, end.y / canvas.height))};
    if (active.startsWith("seed:")) {
      shapes[active.slice(5)] = [a.x, a.y];
    } else if (Math.abs(b.x - a.x) > .01 && Math.abs(b.y - a.y) > .01) {
      shapes[active] = [Math.min(a.x, b.x), Math.min(a.y, b.y), Math.max(a.x, b.x), Math.max(a.y, b.y)];
    }
    active = null;
    start = null;
    onChange?.(shapes);
    draw(canvas);
  };
  return () => URL.revokeObjectURL(url);
}

export function setMode(name) {
  active = name;
}

export function getShapes() {
  return structuredClone(shapes);
}

function draw(canvas) {
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  for (const [name, shape] of Object.entries(shapes)) {
    context.strokeStyle = name.startsWith("goal") ? "#2cc579" : "#ffbc42";
    context.lineWidth = 3;
    context.fillStyle = `${context.strokeStyle}33`;
    if (shape.length === 4) {
      const [x1, y1, x2, y2] = shape.map((v, i) => v * (i % 2 ? canvas.height : canvas.width));
      context.fillRect(x1, y1, x2 - x1, y2 - y1);
      context.strokeRect(x1, y1, x2 - x1, y2 - y1);
      context.fillStyle = "white";
      context.font = "bold 15px sans-serif";
      context.fillText(name, x1 + 5, y1 + 20);
    } else {
      const [x, y] = shape;
      context.beginPath();
      context.arc(x * canvas.width, y * canvas.height, 8, 0, Math.PI * 2);
      context.fill();
      context.stroke();
      context.fillStyle = "white";
      context.font = "bold 15px sans-serif";
      context.fillText(name, x * canvas.width + 10, y * canvas.height);
    }
  }
}
