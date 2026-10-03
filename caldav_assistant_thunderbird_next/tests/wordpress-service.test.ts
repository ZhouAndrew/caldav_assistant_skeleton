import {
  WordPressCliPort,
  WordPressPostView,
  WordPressRestPort,
  WordPressResult,
} from "../src/wordpress/ports";
import {
  runWordPressFullWriteTest,
  runWordPressQuickTest,
} from "../src/wordpress/service";
import {
  WordPressConnectionConfig,
  WordPressFailure,
} from "../src/wordpress/types";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function ok<T>(value: T): WordPressResult<T> {
  return {ok: true, value};
}

function fail(
  kind: WordPressFailure["kind"],
  message: string,
  status: number | null = null,
  code: string | null = null
): WordPressResult<never> {
  return {ok: false, failure: {kind, message, status, code}};
}

function config(
  patch: Partial<WordPressConnectionConfig> = {}
): WordPressConnectionConfig {
  return {
    transport: "auto",
    baseUrl: "https://wp.invalid",
    username: "user",
    applicationPassword: "SECRET-DO-NOT-LEAK",
    wordpressPath: "/var/www/html/wordpress",
    wpCliCommand: "wp",
    allowUntrustedTls: false,
    ...patch,
  };
}

class Rest implements WordPressRestPort {
  authFailure: WordPressFailure | null = null;
  createFailure: WordPressFailure | null = null;
  corruptReadback = false;
  deleted: number[] = [];

  async discover() {
    return ok({siteName: "MyWordPress", applicationPasswordsAvailable: true});
  }
  async currentUser() {
    return this.authFailure
      ? {ok: false as const, failure: this.authFailure}
      : ok({id: 1, username: "user", name: "User"});
  }
  async introspectApplicationPassword() {
    return ok({uuid: "uuid", name: "CalDAV Assistant"});
  }
  async createDraft(
    _config: WordPressConnectionConfig,
    input: {readonly title: string; readonly content: string}
  ) {
    if (this.createFailure) {
      return {ok: false as const, failure: this.createFailure};
    }
    return ok({
      id: 99,
      status: "draft",
      title: input.title,
      content: input.content,
    });
  }
  async getPost(
    _config: WordPressConnectionConfig,
    postId: number
  ) {
    return ok({
      id: postId,
      status: "draft",
      title: "CalDAV Assistant Write Test",
      content: this.corruptReadback ? "wrong" : "caldav-assistant-write-test-2026-10-03T20:00:00+08:00",
    });
  }
  async deletePost(
    _config: WordPressConnectionConfig,
    postId: number
  ) {
    this.deleted.push(postId);
    return ok(null);
  }
}

class Cli implements WordPressCliPort {
  probes = 0;
  async probe() {
    this.probes++;
    return ok({version: "6.9.4", blogName: "MyWordPress"});
  }
  async createDraft(
    _config: WordPressConnectionConfig,
    input: {readonly title: string; readonly content: string}
  ) {
    return ok({id: 77, status: "draft", title: input.title, content: input.content});
  }
  async getPost(
    _config: WordPressConnectionConfig,
    postId: number
  ) {
    return ok({
      id: postId,
      status: "draft",
      title: "CalDAV Assistant Write Test",
      content: "caldav-assistant-write-test-2026-10-03T20:00:00+08:00",
    });
  }
  async deletePost() {
    return ok(null);
  }
}

(async () => {
  const rest = new Rest();
  const cli = new Cli();

  const quick = await runWordPressQuickTest(config(), {rest, cli});
  assert(quick.ok, "REST Quick Test failed");
  assert(quick.transport === "application-password", "Quick Test used wrong primary transport");
  assert(
    quick.steps.map(item => item.name).join(",") === "discover,authenticate,introspect",
    "REST Quick Test stages are wrong"
  );

  rest.authFailure = {
    kind: "authentication",
    message: "HTTP 401",
    status: 401,
    code: "incorrect_password",
  };
  const fallback = await runWordPressQuickTest(config(), {rest, cli});
  assert(fallback.ok, "Auto did not fall back after REST authentication failure");
  assert(fallback.transport === "wp-cli", "Auto fallback did not use WP-CLI");
  assert(fallback.fallbackFrom === "application-password", "fallback source was lost");
  assert(cli.probes === 1, "WP-CLI fallback was not probed");

  const explicit = await runWordPressQuickTest(
    config({transport: "application-password"}),
    {rest, cli}
  );
  assert(!explicit.ok, "Explicit REST authentication failure was hidden by fallback");

  rest.authFailure = null;
  const full = await runWordPressFullWriteTest(
    config(),
    {rest, cli},
    "2026-10-03T20:00:00+08:00"
  );
  assert(full.ok, "Full REST write test failed");
  assert(
    full.steps.some(item => item.name === "create") &&
      full.steps.some(item => item.name === "readback") &&
      full.steps.some(item => item.name === "cleanup"),
    "Full write test skipped create/readback/cleanup"
  );
  assert(rest.deleted.includes(99), "Full write test did not clean temporary draft");

  rest.corruptReadback = true;
  const corrupt = await runWordPressFullWriteTest(
    config(),
    {rest, cli},
    "2026-10-03T20:00:00+08:00"
  );
  assert(!corrupt.ok, "corrupt read-back was accepted");
  assert(
    rest.deleted.filter(id => id === 99).length >= 2,
    "corrupt read-back did not attempt cleanup"
  );

  const serialized = JSON.stringify({quick, fallback, explicit, full, corrupt});
  assert(
    !serialized.includes("SECRET-DO-NOT-LEAK"),
    "WordPress test result leaked Application Password"
  );

  console.log("clean-room WordPress service: PASS");
})().catch(error => {
  console.error(error);
  throw error;
});
