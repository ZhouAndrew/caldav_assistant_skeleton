import {
  classifyRestFailure,
  planWordPressTransport,
  shouldFallbackToWpCli,
} from "../src/wordpress/policy";
import {WordPressConnectionConfig} from "../src/wordpress/types";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function config(
  patch: Partial<WordPressConnectionConfig> = {}
): WordPressConnectionConfig {
  return {
    transport: "auto",
    baseUrl: "https://wordpress.example.invalid",
    username: "user",
    applicationPassword: "secret",
    wordpressPath: "/var/www/html/wordpress",
    wpCliCommand: "wp",
    allowUntrustedTls: false,
    ...patch,
  };
}

const auto = planWordPressTransport(config());
assert(auto.ok, "Auto transport plan failed");
assert(auto.primary === "application-password", "Auto should prefer REST");
assert(auto.fallback === "wp-cli", "Auto should retain WP-CLI fallback");

const restOnly = planWordPressTransport(config({
  transport: "application-password",
}));
assert(restOnly.ok && restOnly.fallback === null,
  "Explicit REST must never configure fallback");

const cliOnly = planWordPressTransport(config({
  transport: "wp-cli",
  baseUrl: "",
  username: "",
  applicationPassword: "",
}));
assert(cliOnly.ok && cliOnly.primary === "wp-cli",
  "Explicit WP-CLI plan failed");

const auth401 = classifyRestFailure({
  message: "invalid application password",
  status: 401,
  code: "incorrect_password",
});
assert(auth401.kind === "authentication", "401 classification is wrong");
assert(
  shouldFallbackToWpCli(config(), "application-password", auth401),
  "Auto 401 should be eligible for WP-CLI fallback"
);
assert(
  !shouldFallbackToWpCli(
    config({transport: "application-password"}),
    "application-password",
    auth401
  ),
  "Explicit REST 401 must not fall back"
);

const forbidden403 = classifyRestFailure({
  message: "rest_cannot_create",
  status: 403,
  code: "rest_cannot_create",
});
assert(forbidden403.kind === "authorization", "403 classification is wrong");
assert(
  shouldFallbackToWpCli(config(), "application-password", forbidden403),
  "Auto 403 should be eligible for local WP-CLI fallback"
);

const endpoint404 = classifyRestFailure({
  message: "route not found",
  status: 404,
  code: "rest_no_route",
});
assert(endpoint404.kind === "endpoint", "404 classification is wrong");
assert(
  !shouldFallbackToWpCli(config(), "application-password", endpoint404),
  "404 must remain visible instead of hiding REST configuration errors"
);

const badRequest = classifyRestFailure({
  message: "invalid payload",
  status: 400,
  code: "rest_invalid_param",
});
assert(badRequest.kind === "request", "400 classification is wrong");
assert(
  !shouldFallbackToWpCli(config(), "application-password", badRequest),
  "400 must not hide a request/programming error with fallback"
);

const server = classifyRestFailure({
  message: "server error",
  status: 503,
});
assert(server.kind === "server", "5xx classification is wrong");
assert(
  shouldFallbackToWpCli(config(), "application-password", server),
  "Auto 5xx should be eligible for WP-CLI fallback"
);

const incomplete = planWordPressTransport(config({
  baseUrl: "",
  username: "",
  applicationPassword: "",
  wordpressPath: "",
  wpCliCommand: "",
}));
assert(!incomplete.ok && incomplete.failure.kind === "configuration",
  "Incomplete Auto configuration was accepted");

console.log("clean-room WordPress policy: PASS");
