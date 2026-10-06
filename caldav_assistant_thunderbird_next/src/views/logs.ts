export interface DiagnosticRecord {
  readonly timestamp: string;
  readonly scope: string;
  readonly success: boolean;
  readonly summary: string;
}

export interface LogFilters {
  readonly date: string | null;
  readonly scope: string | null;
  readonly search: string;
}

export interface LogsView {
  readonly records: readonly DiagnosticRecord[];
}

function dateKey(timestamp: string): string {
  return timestamp.slice(0, 10);
}

export function deriveLogsView(
  source: readonly DiagnosticRecord[],
  filters: LogFilters
): LogsView {
  const query = filters.search.trim().toLocaleLowerCase();
  const records = source
    .filter(record =>
      (!filters.date || dateKey(record.timestamp) === filters.date) &&
      (!filters.scope || record.scope === filters.scope) &&
      (!query ||
        [record.timestamp, record.scope, record.summary]
          .join("\n")
          .toLocaleLowerCase()
          .includes(query))
    )
    .slice()
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp));

  return Object.freeze({records: Object.freeze(records)});
}
