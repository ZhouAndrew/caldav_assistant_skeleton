import {
  WordPressCliPort,
  WordPressPostView,
  WordPressRestPort,
  WordPressResult,
} from "./ports";
import {
  planWordPressTransport,
  shouldFallbackToWpCli,
} from "./policy";
import {
  WordPressConnectionConfig,
  WordPressFailure,
  WordPressTransport,
} from "./types";

export interface WordPressTestStep {
  readonly name:
    | "discover"
    | "authenticate"
    | "introspect"
    | "probe"
    | "create"
    | "readback"
    | "cleanup";
  readonly success: boolean;
  readonly transport: WordPressTransport;
  readonly message: string;
}

export interface WordPressTestSuccess {
  readonly ok: true;
  readonly transport: WordPressTransport;
  readonly fallbackFrom: WordPressTransport | null;
  readonly steps: readonly WordPressTestStep[];
}

export interface WordPressTestFailure {
  readonly ok: false;
  readonly transport: WordPressTransport | null;
  readonly fallbackFrom: WordPressTransport | null;
  readonly failure: WordPressFailure;
  readonly steps: readonly WordPressTestStep[];
}

export type WordPressTestResult =
  | WordPressTestSuccess
  | WordPressTestFailure;

export interface WordPressPorts {
  readonly rest: WordPressRestPort;
  readonly cli: WordPressCliPort;
}

function step(
  name: WordPressTestStep["name"],
  success: boolean,
  transport: WordPressTransport,
  message: string
): WordPressTestStep {
  return Object.freeze({name, success, transport, message});
}

function failureResult(
  transport: WordPressTransport | null,
  fallbackFrom: WordPressTransport | null,
  failure: WordPressFailure,
  steps: readonly WordPressTestStep[]
): WordPressTestFailure {
  return Object.freeze({
    ok: false,
    transport,
    fallbackFrom,
    failure,
    steps: Object.freeze([...steps]),
  });
}

function configFailure(message: string): WordPressFailure {
  return {
    kind: "configuration",
    message,
    status: null,
    code: null,
  };
}

async function quickRest(
  config: WordPressConnectionConfig,
  rest: WordPressRestPort
): Promise<WordPressTestResult> {
  const steps: WordPressTestStep[] = [];

  const discovery = await rest.discover(config);
  if (!discovery.ok) {
    steps.push(step(
      "discover",
      false,
      "application-password",
      discovery.failure.message
    ));
    return failureResult(
      "application-password",
      null,
      discovery.failure,
      steps
    );
  }
  if (!discovery.value.applicationPasswordsAvailable) {
    const failure = configFailure(
      "WordPress does not advertise Application Password support."
    );
    steps.push(step(
      "discover",
      false,
      "application-password",
      failure.message
    ));
    return failureResult("application-password", null, failure, steps);
  }
  steps.push(step(
    "discover",
    true,
    "application-password",
    discovery.value.siteName || "WordPress REST API"
  ));

  const user = await rest.currentUser(config);
  if (!user.ok) {
    steps.push(step(
      "authenticate",
      false,
      "application-password",
      user.failure.message
    ));
    return failureResult("application-password", null, user.failure, steps);
  }
  steps.push(step(
    "authenticate",
    true,
    "application-password",
    user.value.username || user.value.name
  ));

  const appPassword = await rest.introspectApplicationPassword(config);
  if (!appPassword.ok) {
    steps.push(step(
      "introspect",
      false,
      "application-password",
      appPassword.failure.message
    ));
    return failureResult(
      "application-password",
      null,
      appPassword.failure,
      steps
    );
  }
  steps.push(step(
    "introspect",
    true,
    "application-password",
    appPassword.value.name || "Application Password"
  ));

  return Object.freeze({
    ok: true,
    transport: "application-password",
    fallbackFrom: null,
    steps: Object.freeze(steps),
  });
}

async function quickCli(
  config: WordPressConnectionConfig,
  cli: WordPressCliPort
): Promise<WordPressTestResult> {
  const result = await cli.probe(config);
  const steps: WordPressTestStep[] = [
    step(
      "probe",
      result.ok,
      "wp-cli",
      result.ok
        ? [result.value.version, result.value.blogName].filter(Boolean).join(" · ")
        : result.failure.message
    ),
  ];

  return result.ok
    ? Object.freeze({
        ok: true,
        transport: "wp-cli",
        fallbackFrom: null,
        steps: Object.freeze(steps),
      })
    : failureResult("wp-cli", null, result.failure, steps);
}

async function runQuickOn(
  transport: WordPressTransport,
  config: WordPressConnectionConfig,
  ports: WordPressPorts
): Promise<WordPressTestResult> {
  return transport === "application-password"
    ? quickRest(config, ports.rest)
    : quickCli(config, ports.cli);
}

function firstFailure(result: WordPressTestResult): WordPressFailure | null {
  return result.ok ? null : result.failure;
}

export async function runWordPressQuickTest(
  config: WordPressConnectionConfig,
  ports: WordPressPorts
): Promise<WordPressTestResult> {
  const plan = planWordPressTransport(config);
  if (!plan.ok) {
    return failureResult(null, null, plan.failure, []);
  }

  const primary = await runQuickOn(plan.primary, config, ports);
  if (primary.ok) return primary;

  if (
    plan.fallback === "wp-cli" &&
    shouldFallbackToWpCli(config, plan.primary, primary.failure)
  ) {
    const fallback = await quickCli(config, ports.cli);
    return fallback.ok
      ? Object.freeze({
          ...fallback,
          fallbackFrom: plan.primary,
          steps: Object.freeze([...primary.steps, ...fallback.steps]),
        })
      : Object.freeze({
          ...fallback,
          fallbackFrom: plan.primary,
          steps: Object.freeze([...primary.steps, ...fallback.steps]),
        });
  }

  return primary;
}

async function verifiedTemporaryDraft(
  transport: WordPressTransport,
  config: WordPressConnectionConfig,
  ports: WordPressPorts,
  nowIso: string
): Promise<WordPressTestResult> {
  const target = transport === "application-password"
    ? ports.rest
    : ports.cli;
  const steps: WordPressTestStep[] = [];
  const marker = "caldav-assistant-write-test-" + nowIso;
  const title = "CalDAV Assistant Write Test";
  let created: WordPressPostView | null = null;

  const create = await target.createDraft(config, {
    title,
    content: marker,
  });
  if (!create.ok) {
    steps.push(step("create", false, transport, create.failure.message));
    return failureResult(transport, null, create.failure, steps);
  }
  created = create.value;
  steps.push(step("create", true, transport, String(created.id)));

  const readback = await target.getPost(config, created.id);
  if (
    !readback.ok ||
    readback.value.id !== created.id ||
    readback.value.status !== "draft" ||
    !readback.value.content.includes(marker)
  ) {
    const failure = readback.ok
      ? {
          kind: "invalid-response" as const,
          message: "Temporary draft read-back did not match.",
          status: null,
          code: null,
        }
      : readback.failure;
    steps.push(step("readback", false, transport, failure.message));

    const cleanup = await target.deletePost(config, created.id);
    steps.push(step(
      "cleanup",
      cleanup.ok,
      transport,
      cleanup.ok ? String(created.id) : cleanup.failure.message
    ));
    return failureResult(transport, null, failure, steps);
  }
  steps.push(step("readback", true, transport, String(created.id)));

  const cleanup = await target.deletePost(config, created.id);
  if (!cleanup.ok) {
    steps.push(step("cleanup", false, transport, cleanup.failure.message));
    return failureResult(transport, null, cleanup.failure, steps);
  }
  steps.push(step("cleanup", true, transport, String(created.id)));

  return Object.freeze({
    ok: true,
    transport,
    fallbackFrom: null,
    steps: Object.freeze(steps),
  });
}

export async function runWordPressFullWriteTest(
  config: WordPressConnectionConfig,
  ports: WordPressPorts,
  nowIso: string
): Promise<WordPressTestResult> {
  const quick = await runWordPressQuickTest(config, ports);
  if (!quick.ok) return quick;

  const write = await verifiedTemporaryDraft(
    quick.transport,
    config,
    ports,
    nowIso
  );

  if (write.ok) {
    return Object.freeze({
      ...write,
      fallbackFrom: quick.fallbackFrom,
      steps: Object.freeze([...quick.steps, ...write.steps]),
    });
  }

  return Object.freeze({
    ...write,
    fallbackFrom: quick.fallbackFrom,
    steps: Object.freeze([...quick.steps, ...write.steps]),
  });
}
