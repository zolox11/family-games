export function countdown(seconds, onTick, onDone) {
  let remaining = seconds;
  onTick(remaining);
  const timer = setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      clearInterval(timer);
      onTick(0);
      onDone();
    } else {
      onTick(remaining);
    }
  }, 1000);
  return () => clearInterval(timer);
}
