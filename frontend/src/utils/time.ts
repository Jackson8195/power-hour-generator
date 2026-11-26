/** m:ss, or m:ss.t with ``precise`` (short transition moments). */
export function formatTime(seconds: number, precise = false): string {
  const safe = Math.max(0, seconds);
  const m = Math.floor(safe / 60);
  if (precise) {
    const s = (safe - m * 60).toFixed(1).padStart(4, "0");
    return `${m}:${s}`;
  }
  const s = Math.floor(safe) % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}
