import {MESSAGE_KEYS, MessageKey} from "../i18n";
import {
  TaskListItem,
  TaskQueryOptions,
  ThunderbirdTaskFilter,
} from "../task-query";

export type TaskPickerSettings = TaskQueryOptions;
export type TaskPickerItem = TaskListItem;
export type {ThunderbirdTaskFilter};

export interface TaskPickerView {
  readonly filter: ThunderbirdTaskFilter;
  readonly items: readonly TaskPickerItem[];
  readonly emptyMessageKey: MessageKey | null;
}

/**
 * Input is already filtered/search-matched by Thunderbird's own calFilter.
 *
 * The page only performs deterministic display ordering and selection. It has
 * no currentWorkId and no workflow knowledge.
 */
export function deriveTaskPickerView(
  settings: TaskPickerSettings,
  nativeFilteredSource: readonly TaskPickerItem[]
): TaskPickerView {
  const items = nativeFilteredSource
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
