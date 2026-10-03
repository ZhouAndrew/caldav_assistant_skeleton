import {TaskStatus} from "../../domain";

export type PickerStatusFilter =
  | "open"
  | "all"
  | "not-started"
  | "in-progress"
  | "completed"
  | "cancelled";

export interface TaskPickerSettings {
  readonly search: string;
  readonly status: PickerStatusFilter;
  readonly calendarIds: readonly string[];
}

export interface TaskPickerItem {
  readonly taskId: string;
  readonly calendarId: string;
  readonly calendarName: string;
  readonly title: string;
  readonly status: TaskStatus;
  readonly percentComplete: number;
  readonly due: string | null;
  readonly categories: readonly string[];
}

export interface TaskPickerView {
  readonly items: readonly TaskPickerItem[];
  readonly emptyMessage: string | null;
}

function statusMatch(item: TaskPickerItem, filter: PickerStatusFilter): boolean {
  switch (filter) {
    case "all":
      return true;
    case "open":
      return item.status !== "COMPLETED" && item.status !== "CANCELLED";
    case "not-started":
      return item.status === "NEEDS-ACTION" && item.percentComplete === 0;
    case "in-progress":
      return item.status === "IN-PROCESS" ||
        (item.percentComplete > 0 && item.percentComplete < 100);
    case "completed":
      return item.status === "COMPLETED" || item.percentComplete === 100;
    case "cancelled":
      return item.status === "CANCELLED";
  }
}

function searchable(item: TaskPickerItem): string {
  return [
    item.title,
    item.calendarName,
    ...item.categories,
  ].join("\n").toLocaleLowerCase();
}

export function deriveTaskPickerView(
  settings: TaskPickerSettings,
  source: readonly TaskPickerItem[]
): TaskPickerView {
  const calendarSet = new Set(settings.calendarIds);
  const query = settings.search.trim().toLocaleLowerCase();

  const items = source
    .filter(item =>
      (calendarSet.size === 0 || calendarSet.has(item.calendarId)) &&
      statusMatch(item, settings.status) &&
      (!query || searchable(item).includes(query))
    )
    .slice()
    .sort((a, b) => {
      if (a.due === null && b.due !== null) return 1;
      if (a.due !== null && b.due === null) return -1;
      if (a.due !== b.due) return String(a.due).localeCompare(String(b.due));
      return a.title.localeCompare(b.title);
    });

  return Object.freeze({
    items: Object.freeze(items),
    emptyMessage: items.length ? null : "No matching Tasks.",
  });
}
