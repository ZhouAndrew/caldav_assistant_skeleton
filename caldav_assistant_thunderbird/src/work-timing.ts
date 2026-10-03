export type TimingAction =
  | "start"
  | "pause"
  | "resume"
  | "complete"
  | "cancel"
  | "switch-away";

export interface WorkTimingEntry {
  readonly action: TimingAction;
  readonly success: boolean;
  readonly timestampMs: number;
}

export interface WorkTiming {
  readonly accumulatedMs: number;
  readonly runningSinceMs: number | null;
}

function validTime(value: number): boolean {
  return Number.isFinite(value) && value >= 0;
}

/**
 * Derive elapsed-work timing entirely from immutable action history.
 *
 * The current clock is deliberately not read here; callers pass it explicitly
 * when they want a live elapsed value.
 */
export function deriveWorkTiming(
  entries: readonly WorkTimingEntry[],
): WorkTiming {
  let accumulatedMs = 0;
  let runningSinceMs: number | null = null;
  let sessionSeen = false;

  for (const entry of entries) {
    if (!entry.success || !validTime(entry.timestampMs)) continue;

    switch (entry.action) {
      case "start":
        accumulatedMs = 0;
        runningSinceMs = entry.timestampMs;
        sessionSeen = true;
        break;

      case "pause":
        if (sessionSeen && runningSinceMs !== null) {
          accumulatedMs += Math.max(0, entry.timestampMs - runningSinceMs);
          runningSinceMs = null;
        }
        break;

      case "resume":
        if (sessionSeen && runningSinceMs === null) {
          runningSinceMs = entry.timestampMs;
        }
        break;

      case "complete":
      case "cancel":
      case "switch-away":
        if (sessionSeen && runningSinceMs !== null) {
          accumulatedMs += Math.max(0, entry.timestampMs - runningSinceMs);
        }
        runningSinceMs = null;
        sessionSeen = false;
        break;
    }
  }

  return Object.freeze({
    accumulatedMs,
    runningSinceMs,
  });
}

export function elapsedWorkMs(
  timing: WorkTiming,
  nowMs: number,
): number {
  const live = timing.runningSinceMs !== null && validTime(nowMs)
    ? Math.max(0, nowMs - timing.runningSinceMs)
    : 0;
  return Math.max(0, timing.accumulatedMs + live);
}
