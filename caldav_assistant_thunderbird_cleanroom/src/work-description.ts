import {
  DescriptionParseResult,
  ParsedDescription,
  TaskStatus,
  WorkLogV1,
  WorkResult,
  WorkSession,
} from "./domain.js";

const START = "[CALDAV-ASSISTANT-WORKLOG v1]";
const END = "[/CALDAV-ASSISTANT-WORKLOG]";
const VALID_STATUS = new Set<TaskStatus>([
  "",
  "NEEDS-ACTION",
  "IN-PROCESS",
  "COMPLETED",
  "CANCELLED",
]);
const VALID_RESULT = new Set<WorkResult>(["stop", "complete", "cancel"]);

function validPercent(value: unknown): value is number {
  return typeof value === "number" &&
    Number.isFinite(value) &&
    Number.isInteger(value) &&
    value >= 0 &&
    value <= 100;
}

function validIso(value: unknown): value is string {
  if (typeof value !== "string" || !value.trim()) return false;
  return !Number.isNaN(Date.parse(value));
}

function validSession(value: unknown): value is WorkSession {
  if (!value || typeof value !== "object") return false;
  const session = value as Partial<WorkSession>;
  if (typeof session.id !== "string" || !session.id) return false;
  if (!validIso(session.start)) return false;
  if (session.end !== null && !validIso(session.end)) return false;
  if (
    session.result !== null &&
    (typeof session.result !== "string" ||
      !VALID_RESULT.has(session.result as WorkResult))
  ) {
    return false;
  }
  if ((session.end === null) !== (session.result === null)) return false;

  const before = session.before as WorkSession["before"] | undefined;
  if (!before || !VALID_STATUS.has(before.status)) return false;
  if (!validPercent(before.percentComplete)) return false;
  return true;
}

function empty(): WorkLogV1 {
  return Object.freeze({version: 1, sessions: Object.freeze([])});
}

function parsePayload(raw: string): WorkLogV1 | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!value || typeof value !== "object") return null;
  const object = value as {version?: unknown; sessions?: unknown};
  if (object.version !== 1 || !Array.isArray(object.sessions)) return null;
  if (!object.sessions.every(validSession)) return null;

  const ids = new Set<string>();
  let openCount = 0;
  for (const session of object.sessions) {
    if (ids.has(session.id)) return null;
    ids.add(session.id);
    if (session.end === null) openCount++;
  }
  if (openCount > 1) return null;

  return Object.freeze({
    version: 1,
    sessions: Object.freeze(
      object.sessions.map(session =>
        Object.freeze({
          ...session,
          before: Object.freeze({...session.before}),
        })
      )
    ),
  });
}

export function parseWorkDescription(description: string): DescriptionParseResult {
  const original = String(description ?? "");
  const firstStart = original.indexOf(START);
  const firstEnd = original.indexOf(END);

  if (firstStart < 0 && firstEnd < 0) {
    return Object.freeze({
      ok: true,
      userText: original,
      workLog: empty(),
    });
  }

  if (firstStart < 0 || firstEnd < 0) {
    return Object.freeze({
      ok: false,
      reason: "Assistant work-log marker is incomplete.",
      original,
    });
  }

  if (original.indexOf(START, firstStart + START.length) >= 0) {
    return Object.freeze({
      ok: false,
      reason: "Multiple Assistant work-log blocks were found.",
      original,
    });
  }

  const expectedSuffix = original.slice(firstStart);
  const endAt = expectedSuffix.indexOf(END);
  if (endAt < 0 || endAt + END.length !== expectedSuffix.length) {
    return Object.freeze({
      ok: false,
      reason: "Assistant work-log block is not the final Description block.",
      original,
    });
  }

  let userText = original.slice(0, firstStart);
  if (userText.endsWith("\n\n")) {
    userText = userText.slice(0, -2);
  } else if (userText.length) {
    return Object.freeze({
      ok: false,
      reason: "Assistant work-log block separator is malformed.",
      original,
    });
  }

  const payloadText = expectedSuffix
    .slice(START.length, endAt)
    .replace(/^\n/, "")
    .replace(/\n$/, "");
  const workLog = parsePayload(payloadText);
  if (!workLog) {
    return Object.freeze({
      ok: false,
      reason: "Assistant work-log payload is invalid.",
      original,
    });
  }

  return Object.freeze({
    ok: true,
    userText,
    workLog,
  });
}

export function serializeWorkDescription(parsed: ParsedDescription): string {
  if (!parsed.workLog.sessions.length) return parsed.userText;

  const payload = JSON.stringify({
    version: 1,
    sessions: parsed.workLog.sessions,
  });
  const block = START + "\n" + payload + "\n" + END;
  return parsed.userText ? parsed.userText + "\n\n" + block : block;
}

export function openWorkSession(
  parsed: ParsedDescription,
  session: WorkSession
): ParsedDescription | null {
  if (!validSession(session) || session.end !== null || session.result !== null) {
    return null;
  }
  if (parsed.workLog.sessions.some(item => item.end === null || item.id === session.id)) {
    return null;
  }
  return Object.freeze({
    ok: true,
    userText: parsed.userText,
    workLog: Object.freeze({
      version: 1,
      sessions: Object.freeze([...parsed.workLog.sessions, session]),
    }),
  });
}

export function closeWorkSession(
  parsed: ParsedDescription,
  sessionId: string,
  end: string,
  result: WorkResult
): ParsedDescription | null {
  if (!validIso(end) || !VALID_RESULT.has(result)) return null;

  const index = parsed.workLog.sessions.findIndex(item => item.id === sessionId);
  if (index < 0) return null;
  const existing = parsed.workLog.sessions[index];
  if (!existing) return null;

  if (existing.end !== null) {
    if (existing.end === end && existing.result === result) return parsed;
    return null;
  }

  const closed: WorkSession = Object.freeze({
    ...existing,
    end,
    result,
  });
  const sessions = parsed.workLog.sessions.slice();
  sessions[index] = closed;

  return Object.freeze({
    ok: true,
    userText: parsed.userText,
    workLog: Object.freeze({
      version: 1,
      sessions: Object.freeze(sessions),
    }),
  });
}

export function getOpenSession(
  parsed: ParsedDescription
): WorkSession | null {
  return parsed.workLog.sessions.find(session => session.end === null) ?? null;
}
