import {
  ParsedWorkDescription,
  TaskStatus,
  WorkResult,
  WorkSession,
  normalizePercent,
} from "./domain";

const START = "[CALDAV-ASSISTANT-WORKLOG v1]";
const END = "[/CALDAV-ASSISTANT-WORKLOG]";

export interface ParseResult {
  readonly ok: true;
  readonly value: ParsedWorkDescription;
}

export interface ParseFailure {
  readonly ok: false;
  readonly reason: "multiple-blocks" | "unterminated-block" | "trailing-data" | "invalid-json" | "invalid-session";
}

export type WorkDescriptionParse = ParseResult | ParseFailure;

function isStatus(value: unknown): value is TaskStatus {
  return value === "NEEDS-ACTION" ||
    value === "IN-PROCESS" ||
    value === "COMPLETED" ||
    value === "CANCELLED";
}

function isResult(value: unknown): value is WorkResult | null {
  return value === null ||
    value === "stop" ||
    value === "complete" ||
    value === "cancel";
}

function validIso(value: unknown): value is string {
  return typeof value === "string" &&
    value.length > 0 &&
    Number.isFinite(Date.parse(value));
}

function validateSession(value: unknown): WorkSession | null {
  if (!value || typeof value !== "object") return null;
  const session = value as Record<string, unknown>;
  const before = session.before;
  if (!before || typeof before !== "object") return null;
  const beforeRecord = before as Record<string, unknown>;

  if (
    typeof session.id !== "string" ||
    !session.id ||
    !validIso(session.start) ||
    !(session.end === null || validIso(session.end)) ||
    !isResult(session.result) ||
    !isStatus(beforeRecord.status) ||
    typeof beforeRecord.percentComplete !== "number"
  ) {
    return null;
  }

  const closed = session.end !== null;
  if (closed !== (session.result !== null)) return null;

  return Object.freeze({
    id: session.id,
    start: session.start,
    end: session.end,
    result: session.result,
    before: Object.freeze({
      status: beforeRecord.status,
      percentComplete: normalizePercent(beforeRecord.percentComplete),
    }),
  });
}

export function parseWorkDescription(description: string): WorkDescriptionParse {
  const source = String(description ?? "");
  const first = source.indexOf(START);
  if (first < 0) {
    return Object.freeze({
      ok: true,
      value: Object.freeze({prefix: source, sessions: Object.freeze([])}),
    });
  }

  if (source.indexOf(START, first + START.length) >= 0) {
    return Object.freeze({ok: false, reason: "multiple-blocks"});
  }

  const end = source.indexOf(END, first + START.length);
  if (end < 0) return Object.freeze({ok: false, reason: "unterminated-block"});
  if (source.indexOf(END, end + END.length) >= 0) {
    return Object.freeze({ok: false, reason: "multiple-blocks"});
  }

  const trailing = source.slice(end + END.length);
  if (trailing.trim() !== "") {
    return Object.freeze({ok: false, reason: "trailing-data"});
  }

  const payloadText = source.slice(first + START.length, end).trim();
  let raw: unknown;
  try {
    raw = payloadText ? JSON.parse(payloadText) : [];
  } catch {
    return Object.freeze({ok: false, reason: "invalid-json"});
  }

  if (!Array.isArray(raw)) {
    return Object.freeze({ok: false, reason: "invalid-json"});
  }

  const sessions: WorkSession[] = [];
  for (const item of raw) {
    const validated = validateSession(item);
    if (!validated) return Object.freeze({ok: false, reason: "invalid-session"});
    sessions.push(validated);
  }

  return Object.freeze({
    ok: true,
    value: Object.freeze({
      prefix: source.slice(0, first),
      sessions: Object.freeze(sessions),
    }),
  });
}

export function serializeWorkDescription(parsed: ParsedWorkDescription): string {
  if (!parsed.sessions.length) return parsed.prefix;

  const separator =
    parsed.prefix.length === 0 || parsed.prefix.endsWith("\n")
      ? ""
      : "\n\n";

  return (
    parsed.prefix +
    separator +
    START +
    "\n" +
    JSON.stringify(parsed.sessions) +
    "\n" +
    END
  );
}

export function openSession(
  parsed: ParsedWorkDescription,
  session: WorkSession,
): ParsedWorkDescription | null {
  if (parsed.sessions.some(item => item.end === null)) return null;
  return Object.freeze({
    prefix: parsed.prefix,
    sessions: Object.freeze([...parsed.sessions, Object.freeze(session)]),
  });
}

export function closeSession(
  parsed: ParsedWorkDescription,
  sessionId: string,
  end: string,
  result: WorkResult,
): ParsedWorkDescription | null {
  if (!validIso(end)) return null;
  let matched = 0;

  const sessions = parsed.sessions.map(session => {
    if (session.id !== sessionId) return session;
    matched++;
    if (session.end !== null) {
      if (session.end === end && session.result === result) return session;
      return session;
    }
    return Object.freeze({...session, end, result});
  });

  if (matched !== 1) return null;
  return Object.freeze({
    prefix: parsed.prefix,
    sessions: Object.freeze(sessions),
  });
}

export function openSessions(parsed: ParsedWorkDescription): readonly WorkSession[] {
  return Object.freeze(parsed.sessions.filter(session => session.end === null));
}
