import {
  CleanroomBrowserApi,
  createStoragePort,
  createThunderbirdTaskPort,
  createThunderbirdTaskQueryPort,
} from "./browser-ports.js";
import {WorkIntent} from "./domain.js";
import {
  TaskPageModel,
  TaskPickerModel,
  deriveTaskPageModel,
  deriveTaskPickerModel,
} from "./page-models.js";
import {formatLocalIso, newSessionId} from "./runtime-values.js";
import {
  StorageCurrentWork,
  readSettings,
} from "./storage-runtime.js";
import {parseTaskId} from "./task-id.js";
import {
  TaskCommandResult,
  executeTaskCommand,
} from "./workflow-service.js";

export async function loadTaskPickerPage(
  browserApi: CleanroomBrowserApi,
  search = ""
): Promise<TaskPickerModel> {
  const storage = createStoragePort(browserApi.storage.local);
  const settings = await readSettings(storage);
  const query = createThunderbirdTaskQueryPort(browserApi.ThunderbirdTasks);

  const tasks = await query.listTasks({
    calendarId: settings.taskCalendarId,
    includeCompleted: true,
  });
  return deriveTaskPickerModel(settings, tasks, search);
}

export async function loadTaskPage(
  browserApi: CleanroomBrowserApi,
  taskId: string,
  nowIso = formatLocalIso(new Date())
): Promise<TaskPageModel> {
  const ref = parseTaskId(taskId);
  if (!ref) throw new Error("Invalid taskId.");

  const storage = createStoragePort(browserApi.storage.local);
  const tasks = createThunderbirdTaskPort(browserApi.ThunderbirdTasks);
  const currentWork = new StorageCurrentWork(storage);

  const [task, currentWorkId] = await Promise.all([
    tasks.getTask(ref),
    currentWork.getCurrentWorkId(),
  ]);
  return deriveTaskPageModel(task, currentWorkId, nowIso);
}

export async function runTaskPageAction(
  browserApi: CleanroomBrowserApi,
  intent: WorkIntent,
  taskId: string,
  nowIso = formatLocalIso(new Date()),
  sessionId = newSessionId()
): Promise<TaskCommandResult> {
  const storage = createStoragePort(browserApi.storage.local);
  return executeTaskCommand(intent, taskId, {
    tasks: createThunderbirdTaskPort(browserApi.ThunderbirdTasks),
    currentWork: new StorageCurrentWork(storage),
    nowIso: () => nowIso,
    newSessionId: () => sessionId,
  });
}
