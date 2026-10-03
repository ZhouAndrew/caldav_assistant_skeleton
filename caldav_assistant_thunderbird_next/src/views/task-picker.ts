import {MESSAGE_KEYS, MessageKey} from "../i18n";

export type ThunderbirdTaskFilter =
  | "all"
  | "notstarted"
  | "overdue"
  | "open"
  | "completed"
  | "throughcurrent"
  | "throughtoday"
  | "throughsevendays";

export interface TaskPickerSettings {
  /**
   * Thunderbird-native filter name. The adapter owns its semantics.
   * The page/view must not reimplement calendar-filter.js.
   */
  readonly filter: ThunderbirdTaskFilter;
  readonly search: string;
  readonly calendarIds: readonly string[];
}

export interface TaskPickerItem {
  readonly taskId: string;
  readonly calendarId: string;
  readonly calendarName: string;
  readonly title: string;
  readonly due: string | null;
  readonly categories: readonly string[];
}

export interface TaskPickerView {
  readonly filter: ThunderbirdTaskFilter;
  readonly items: readonly TaskPickerItem[];
  readonly emptyMessageKey: MessageKey | null;
}

function searchable(item: TaskPickerItem): string {
  return [
    item.title,
    item.calendarName,
    ...item.categories,
  ].join("\n").toLocaleLowerCase();
}

/**
 * The source list is already filtered by Thunderbird.
 *
 * This pure view function only applies the page's text search and stable display
 * ordering. It deliberately knows nothing about workflow/currentWorkId.
 */
export function deriveTaskPickerView(
  settings: TaskPickerSettings,
  nativeFilteredSource: readonly TaskPickerItem[]
): TaskPickerView {
  const query = settings.search.trim().toLocaleLowerCase();
  const items = nativeFilteredSource
    .filter(item => !query || searchable(item).includes(query))
    .slice()
    .sort((a, b) => {
      if (a.due === null && b.due !== null) return 1;
      if (a.due !== null && b.due === null) return -1;
      if (a.due !== b.due) return String(a.due).localeCompare(String(b.due));
      return a.title.localeCompare(b.title);
    });

  return Object.freeze({
    filter: settings.filter,
    items: Object.freeze(items),
    emptyMessageKey: items.length ? null : MESSAGE_KEYS.noMatchingTasks,
  });
}
