import {TaskSnapshot, WorkIntent} from "./domain.js";
import {CleanSettings} from "./settings-migration.js";
import {makeTaskId} from "./task-id.js";
import {parseWorkDescription} from "./work-description.js";

export interface TaskPickerItem {
  readonly taskId: string;
  readonly title: string;
  readonly status: TaskSnapshot["status"];
  readonly percentComplete: number;
}

export interface TaskPickerModel {
  readonly filter: string;
  readonly search: string;
  readonly items: readonly TaskPickerItem[];
}

function unfinished(task: TaskSnapshot): boolean {
  return task.status !== "COMPLETED" && task.status !== "CANCELLED";
}

function matchesFilter(task: TaskSnapshot, filter: string): boolean {
  switch (filter) {
    case "all":
      return true;
    case "completed":
      return task.status === "COMPLETED";
    case "notstarted":
      return task.status === "" || task.status === "NEEDS-ACTION";
    case "open":
    case "incomplete":
    default:
      return unfinished(task);
  }
}

function searchableText(task: TaskSnapshot): string {
  const parsed = parseWorkDescription(task.description);
  const userText = parsed.ok ? parsed.userText : task.description;
  return (task.title + "\n" + userText).toLocaleLowerCase();
}

/**
 * Task Picker is deliberately workflow-blind. There is no currentWorkId
 * parameter and no Start/Stop decision in this model.
 */
export function deriveTaskPickerModel(
  settings: CleanSettings,
  tasks: readonly TaskSnapshot[],
  search = ""
): TaskPickerModel {
  const filter = settings.taskView || "incomplete";
  const needle = search.trim().toLocaleLowerCase();

  const items = tasks
    .filter(task => matchesFilter(task, filter))
    .filter(task => !needle || searchableText(task).includes(needle))
    .map(task =>
      Object.freeze({
        taskId: makeTaskId(task),
        title: task.title || "(untitled task)",
        status: task.status,
        percentComplete: task.percentComplete,
      })
    );

  return Object.freeze({
    filter,
    search,
    items: Object.freeze(items),
  });
}

export interface TaskPageModel {
  readonly taskId: string;
  readonly title: string;
  readonly status: TaskSnapshot["status"];
  readonly percentComplete: number;
  readonly userDescription: string;
  readonly actions: readonly WorkIntent[];
  readonly isCurrent: boolean;
  readonly currentConflict: boolean;
  readonly workLogCorrupt: boolean;
  readonly message: string;
  readonly elapsedMs: number;
  readonly sessionCount: number;
}

function elapsedMs(task: TaskSnapshot, nowIso: string): {
  elapsedMs: number;
  sessionCount: number;
} | null {
  const parsed = parseWorkDescription(task.description);
  if (!parsed.ok) return null;

  const now = Date.parse(nowIso);
  if (!Number.isFinite(now)) return {elapsedMs: 0, sessionCount: parsed.workLog.sessions.length};

  let elapsed = 0;
  for (const session of parsed.workLog.sessions) {
    const start = Date.parse(session.start);
    const end = session.end === null ? now : Date.parse(session.end);
    if (Number.isFinite(start) && Number.isFinite(end)) {
      elapsed += Math.max(0, end - start);
    }
  }
  return {
    elapsedMs: elapsed,
    sessionCount: parsed.workLog.sessions.length,
  };
}

export function deriveTaskPageModel(
  task: TaskSnapshot,
  currentWorkId: string | null,
  nowIso: string
): TaskPageModel {
  const taskId = makeTaskId(task);
  const parsed = parseWorkDescription(task.description);
  const timing = elapsedMs(task, nowIso);
  const finished =
    task.status === "COMPLETED" || task.status === "CANCELLED";
  const isCurrent = currentWorkId === taskId;
  const currentConflict = currentWorkId !== null && !isCurrent;

  let actions: readonly WorkIntent[] = [];
  let message = "";

  if (!parsed.ok) {
    message = "Task Description 中的 Assistant 工作记录损坏；为保护原文，已禁止修改。";
  } else if (finished) {
    message = "这个 Task 已结束。";
  } else if (isCurrent) {
    actions = Object.freeze(["stop", "complete", "cancel"] as WorkIntent[]);
  } else if (currentConflict) {
    message = "另一个 Task 正在进行；请先处理当前工作。";
  } else {
    actions = Object.freeze(["start"] as WorkIntent[]);
  }

  return Object.freeze({
    taskId,
    title: task.title || "(untitled task)",
    status: task.status,
    percentComplete: task.percentComplete,
    userDescription: parsed.ok ? parsed.userText : task.description,
    actions,
    isCurrent,
    currentConflict,
    workLogCorrupt: !parsed.ok,
    message,
    elapsedMs: timing?.elapsedMs ?? 0,
    sessionCount: timing?.sessionCount ?? 0,
  });
}
