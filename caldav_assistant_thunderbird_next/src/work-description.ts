import {
  ParsedDescription,
  WorkLog,
  WorkResult,
  WorkSession,
} from "./domain";

const START = "[CALDAV-ASSISTANT-WORKLOG v1]";
const END = "[/CALDAV-ASSISTANT-WORKLOG]";

export interface DescriptionParseSuccess {
  readonly ok: true;
  readonly value: ParsedDescription;
}

export interface DescriptionParseFailure {
  readonly ok: false;
  readonly reason: "malformed-worklog";
}

export type DescriptionParseResult =
  | DescriptionParseSuccess
  | DescriptionParseFailure;

function validIso(value: unknown): value is string {
  if (typeof value !== "string" || !value.trim()) return false;
  return !Number.isNaN(Date.parse(value));
}

function validStatus(value: unknown): boolean {
  return value === "NEEDS-ACTION" ||
    value === "IN-PROCESS" ||
    value === "COMPLETED" ||
    value === "CANCELLED";
}

function validPercent(value: unknown): boolean {
  return Number.isInteger(value) && Number(value) >= 0 && Number(value) <= 100;
}

function validResult(value: unknown): value is WorkResult | null {
  return value === null ||
    value === "stop" ||
    value === "complete" ||
    value === "cancel";
}

function validSession(value: unknown): value is WorkSession {
  if (!value || typeof value !== "object") return false;
  const session = value as Record<string, unknown>;
  const before = session.before;
  if (!before || typeof before !== "object") return false;
  const pre = before as Record<string, unknown>;

  if (typeof session.id !== "string" || !session.id) return false;
  if (!validIso(session.start)) return false;
  if (!(session.end === null || validIso(session.end))) return false;
  if (!validResult(session.result)) return false;
  if (session.end === null && session.result !== null) return false;
  if (session.end !== null && session.result === null) return false;
  if (session.end !== null && Date.parse(session.end) < Date.parse(session.start)) {
    return false;
  }
  if (!validStatus(pre.status)) return false;
  if (pre.status === "COMPLETED" || pre.status === "CANCELLED") return false;
  if (!validPercent(pre.percentComplete)) return false;
  return true;
}

function validLog(value: unknown): value is WorkLog {
  if (!value || typeof value !== "object") return false;
  const log = value as Record<string, unknown>;
  if (log.version !== 1 || !Array.isArray(log.sessions)) return false;
  if (!log.sessions.every(validSession)) return false;

  const ids = new Set<string>();
  let openCount = 0;
  for (const session of log.sessions) {
    if (ids.has(session.id)) return false;
    ids.add(session.id);
    if (session.end === null) openCount++;
  }
  return openCount <= 1;
}

function suffixIndex(description: string): number {
  const marker = "\n\n" + START;
  if (description.startsWith(START)) return 0;
  return description.lastIndexOf(marker) >= 0
    ? description.lastIndexOf(marker) + 2
    : -1;
}

export function parseWorkDescription(
  description: string
): DescriptionParseResult {
  const index = suffixIndex(description);
  if (index < 0) {
    return {
      ok: true,
      value: Object.freeze({
        userText: description,
        workLog: Object.freeze({version: 1, sessions: Object.freeze([])}),
      }),
    };
  }

  const suffix = description.slice(index);
  if (!suffix.endsWith(END)) {
    return {ok: false, reason: "malformed-worklog"};
  }

  const bodyStart = START.length;
  const bodyEnd = suffix.length - END.length;
  const body = suffix.slice(bodyStart, bodyEnd);
  if (!body.startsWith("\n") || !body.endsWith("\n")) {
    return {ok: false, reason: "malformed-worklog"};
  }

  const json = body.slice(1, -1);
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    return {ok: false, reason: "malformed-worklog"};
  }
  if (!validLog(parsed)) {
    return {ok: false, reason: "malformed-worklog"};
  }

  const userText = index === 0 ? "" : description.slice(0, index - 2);
  return {
    ok: true,
    value: Object.freeze({
      userText,
      workLog: Object.freeze({
        version: 1,
        sessions: Object.freeze(parsed.sessions.map(session => Object.freeze({
          ...session,
          before: Object.freeze({...session.before}),
        }))),
      }),
    }),
  };
}

export function serializeWorkDescription(value: ParsedDescription): string {
  const payload = JSON.stringify({
    version: 1,
    sessions: value.workLog.sessions,
  });
  const block = START + "\n" + payload + "\n" + END;
  return value.userText ? value.userText + "\n\n" + block : block;
}

export function openSession(
  value: ParsedDescription,
  session: WorkSession
): ParsedDescription | null {
  if (value.workLog.sessions.some(item => item.end === null)) return null;
  if (session.end !== null || session.result !== null || !validSession(session)) {
    return null;
  }
  if (value.workLog.sessions.some(item => item.id === session.id)) return null;

  return Object.freeze({
    userText: value.userText,
    workLog: Object.freeze({
      version: 1,
      sessions: Object.freeze([...value.workLog.sessions, Object.freeze(session)]),
    }),
  });
}

export function closeOpenSession(
  value: ParsedDescription,
  end: string,
  result: WorkResult
): {readonly value: ParsedDescription; readonly closed: WorkSession} | null {
  if (!validIso(end)) return null;
  const openIndex = value.workLog.sessions.findIndex(item => item.end === null);
  if (openIndex < 0) return null;

  const open = value.workLog.sessions[openIndex]!;
  if (Date.parse(end) < Date.parse(open.start)) return null;

  const closed: WorkSession = Object.freeze({
    ...open,
    end,
    result,
  });
  const sessions = value.workLog.sessions.map((session, index) =>
    index === openIndex ? closed : session
  );
  return Object.freeze({
    value: Object.freeze({
      userText: value.userText,
      workLog: Object.freeze({
        version: 1,
        sessions: Object.freeze(sessions),
      }),
    }),
    closed,
  });
}

export function openWorkSession(value: ParsedDescription): WorkSession | null {
  return value.workLog.sessions.find(session => session.end === null) ?? null;
}
