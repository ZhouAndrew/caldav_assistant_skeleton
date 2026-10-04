import {
  WordPressConnectionConfig,
  WordPressFailure,
  WordPressTransport,
  WordPressTransportPlanResult,
} from "./types";

function configuredRest(config: WordPressConnectionConfig): boolean {
  return Boolean(
    config.baseUrl.trim() &&
    config.username.trim() &&
    config.applicationPassword
  );
}

function configuredCli(config: WordPressConnectionConfig): boolean {
  return Boolean(
    config.wordpressPath.trim() &&
    config.wpCliCommand.trim()
  );
}

function configFailure(message: string): WordPressTransportPlanResult {
  return {
    ok: false,
    failure: {
      kind: "configuration",
      message,
      status: null,
      code: null,
    },
  };
}

export function planWordPressTransport(
  config: WordPressConnectionConfig
): WordPressTransportPlanResult {
  if (config.transport === "application-password") {
    return configuredRest(config)
      ? {ok: true, primary: "application-password", fallback: null}
      : configFailure("REST/Application Password configuration is incomplete.");
  }

  if (config.transport === "wp-cli") {
    return configuredCli(config)
      ? {ok: true, primary: "wp-cli", fallback: null}
      : configFailure("WP-CLI configuration is incomplete.");
  }

  if (configuredRest(config)) {
    return {
      ok: true,
      primary: "application-password",
      fallback: configuredCli(config) ? "wp-cli" : null,
    };
  }

  if (configuredCli(config)) {
    return {ok: true, primary: "wp-cli", fallback: null};
  }

  return configFailure(
    "Auto transport needs either complete REST credentials or complete WP-CLI configuration."
  );
}

export function classifyRestFailure(input: {
  readonly message: string;
  readonly status?: number | null;
  readonly code?: string | null;
  readonly network?: boolean;
  readonly tls?: boolean;
}): WordPressFailure {
  const status = input.status ?? null;
  const code = input.code ?? null;

  if (input.tls) {
    return {kind: "tls", message: input.message, status, code};
  }
  if (input.network) {
    return {kind: "network", message: input.message, status, code};
  }
  if (status === 401) {
    return {kind: "authentication", message: input.message, status, code};
  }
  if (status === 403) {
    return {kind: "authorization", message: input.message, status, code};
  }
  if (status === 404) {
    return {kind: "endpoint", message: input.message, status, code};
  }
  if (status !== null && status >= 500) {
    return {kind: "server", message: input.message, status, code};
  }
  if (status !== null && status >= 400) {
    return {kind: "request", message: input.message, status, code};
  }
  return {kind: "invalid-response", message: input.message, status, code};
}

export function shouldFallbackToWpCli(
  config: WordPressConnectionConfig,
  attempted: WordPressTransport,
  failure: WordPressFailure
): boolean {
  if (config.transport !== "auto") return false;
  if (attempted !== "application-password") return false;
  if (!configuredCli(config)) return false;

  return [
    "network",
    "tls",
    "authentication",
    "authorization",
    "server",
  ].includes(failure.kind);
}
