import {
  HttpPort,
  HttpRequest,
  HttpResponse,
  WordPressRestAdapter,
} from "../src/wordpress/rest-adapter";
import {WordPressConnectionConfig} from "../src/wordpress/types";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function config(
  patch: Partial<WordPressConnectionConfig> = {}
): WordPressConnectionConfig {
  return {
    transport: "application-password",
    baseUrl: "https://wp.example.invalid/",
    username: "andrew",
    applicationPassword: "abcd efgh ijkl",
    wordpressPath: "/var/www/html/wordpress",
    wpCliCommand: "wp",
    allowUntrustedTls: false,
    ...patch,
  };
}

class FakeHttp implements HttpPort {
  readonly calls: HttpRequest[] = [];
  queue: Array<HttpResponse | Error> = [];

  async request(input: HttpRequest): Promise<HttpResponse> {
    this.calls.push(input);
    const next = this.queue.shift();
    if (next instanceof Error) throw next;
    if (!next) throw new Error("No fake HTTP response queued.");
    return next;
  }
}

(async () => {
  const http = new FakeHttp();
  const rest = new WordPressRestAdapter(http);

  http.queue.push({
    status: 200,
    body: JSON.stringify({
      name: "MyWordPress",
      authentication: {
        "application-passwords": {
          endpoints: {
            authorization: "https://wp.example.invalid/wp-admin/authorize-application.php",
          },
        },
      },
    }),
  });
  const discovery = await rest.discover(config());
  assert(discovery.ok, "REST discovery failed");
  assert(discovery.value.applicationPasswordsAvailable,
    "Application Password support was not detected");
  assert(http.calls[0]?.url === "https://wp.example.invalid/wp-json/",
    "REST root URL was normalized incorrectly");
  assert(
    http.calls[0]?.headers.Authorization?.startsWith("Basic "),
    "Basic Authorization header missing"
  );

  http.queue.push({
    status: 200,
    body: JSON.stringify({id: 7, username: "andrew", name: "Andrew"}),
  });
  const me = await rest.currentUser(config());
  assert(me.ok && me.value.id === 7, "current user probe failed");
  assert(
    http.calls[1]?.url.endsWith("/wp-json/wp/v2/users/me?context=edit"),
    "current-user endpoint is wrong"
  );

  http.queue.push({
    status: 200,
    body: JSON.stringify({uuid: "u-1", name: "CalDAV Assistant"}),
  });
  const introspect = await rest.introspectApplicationPassword(config());
  assert(introspect.ok && introspect.value.uuid === "u-1",
    "Application Password introspection failed");

  http.queue.push({
    status: 201,
    body: JSON.stringify({
      id: 99,
      status: "draft",
      title: {raw: "Test", rendered: "Test"},
      content: {raw: "marker-123", rendered: "<p>marker-123</p>"},
    }),
  });
  const created = await rest.createDraft(config(), {
    title: "Test",
    content: "marker-123",
  });
  assert(created.ok && created.value.id === 99, "draft create failed");
  const createCall = http.calls[3]!;
  assert(createCall.method === "POST", "draft create did not use POST");
  assert(createCall.url.endsWith("/wp-json/wp/v2/posts"),
    "draft create endpoint is wrong");
  assert(
    JSON.parse(createCall.body ?? "{}").status === "draft",
    "draft create did not force draft status"
  );

  http.queue.push({
    status: 200,
    body: JSON.stringify({
      id: 99,
      status: "draft",
      title: {raw: "Test"},
      content: {raw: "marker-123"},
    }),
  });
  const read = await rest.getPost(config(), 99);
  assert(read.ok && read.value.content === "marker-123",
    "post read-back failed");
  assert(
    http.calls[4]?.url.endsWith("/wp-json/wp/v2/posts/99?context=edit"),
    "post read-back must use edit context"
  );

  http.queue.push({
    status: 200,
    body: JSON.stringify({deleted: true, previous: {id: 99}}),
  });
  const deleted = await rest.deletePost(config(), 99);
  assert(deleted.ok, "temporary draft cleanup failed");
  assert(
    http.calls[5]?.url.endsWith("/wp-json/wp/v2/posts/99?force=true"),
    "draft cleanup must use force=true"
  );

  http.queue.push({
    status: 401,
    body: JSON.stringify({
      code: "incorrect_password",
      message: "Error: The password you entered is incorrect.",
      data: {status: 401},
    }),
  });
  const authFailure = await rest.currentUser(config());
  assert(!authFailure.ok, "401 was treated as success");
  assert(authFailure.failure.kind === "authentication",
    "401 was not classified as authentication");
  assert(authFailure.failure.code === "incorrect_password",
    "WordPress error code was lost");

  http.queue.push({
    status: 403,
    body: JSON.stringify({
      code: "rest_cannot_create",
      message: "Sorry, you are not allowed to create posts as this user.",
      data: {status: 403},
    }),
  });
  const permissionFailure = await rest.createDraft(config(), {
    title: "x",
    content: "y",
  });
  assert(!permissionFailure.ok, "403 was treated as success");
  assert(permissionFailure.failure.kind === "authorization",
    "403 was not classified as authorization");

  http.queue.push(new Error("certificate verify failed"));
  const tlsFailure = await rest.discover(config());
  assert(!tlsFailure.ok && tlsFailure.failure.kind === "tls",
    "TLS failure was not separated from network failure");

  http.queue.push(new Error("connection refused"));
  const networkFailure = await rest.discover(config());
  assert(!networkFailure.ok && networkFailure.failure.kind === "network",
    "network failure classification is wrong");

  const serializedResults = JSON.stringify({
    discovery,
    me,
    introspect,
    created,
    read,
    deleted,
    authFailure,
    permissionFailure,
    tlsFailure,
    networkFailure,
  });
  assert(!serializedResults.includes("abcd efgh ijkl"),
    "REST result leaked Application Password");
  assert(!serializedResults.includes("Authorization"),
    "REST result leaked Authorization metadata");

  console.log("clean-room WordPress REST adapter: PASS");
})().catch(error => {
  console.error(error);
  throw error;
});
