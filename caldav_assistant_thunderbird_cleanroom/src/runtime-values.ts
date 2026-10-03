export function formatLocalIso(date: Date): string {
  if (Number.isNaN(date.getTime())) {
    throw new Error("Cannot format an invalid Date.");
  }
  const pad = (value: number): string => String(value).padStart(2, "0");
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absolute = Math.abs(offsetMinutes);
  const offset =
    sign + pad(Math.floor(absolute / 60)) + ":" + pad(absolute % 60);

  return (
    String(date.getFullYear()).padStart(4, "0") +
    "-" + pad(date.getMonth() + 1) +
    "-" + pad(date.getDate()) +
    "T" + pad(date.getHours()) +
    ":" + pad(date.getMinutes()) +
    ":" + pad(date.getSeconds()) +
    offset
  );
}

export function newSessionId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return uuid;
  return (
    "session-" +
    Date.now().toString(36) +
    "-" +
    Math.random().toString(36).slice(2)
  );
}
