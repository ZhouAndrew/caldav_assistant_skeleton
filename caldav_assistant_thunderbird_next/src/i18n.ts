export const MESSAGE_KEYS = Object.freeze({
  taskWorkLogMalformed: "taskWorkLogMalformed",
  taskFinishedOpenSession: "taskFinishedOpenSession",
  currentPointerStale: "currentPointerStale",
  openSessionNotCurrent: "openSessionNotCurrent",
  taskFinished: "taskFinished",
  anotherTaskActive: "anotherTaskActive",
  noMatchingTasks: "noMatchingTasks",
  todayMalformedWorkLog: "todayMalformedWorkLog",
} as const);

export type MessageKey =
  typeof MESSAGE_KEYS[keyof typeof MESSAGE_KEYS];
