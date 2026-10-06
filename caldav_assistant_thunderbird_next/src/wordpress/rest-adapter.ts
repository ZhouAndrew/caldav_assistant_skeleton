import {classifyRestFailure} from "./policy";
import {
  WordPressPostView,
  WordPressRestAppPassword,
  WordPressRestDiscovery,
  WordPressRestPort,
  WordPressRestUser,
  WordPressResult,
} from "./ports";
import {WordPressConnectionConfig} from "./types";

export interface HttpRequest {
  readonly method: "GET" | "POST" | "DELETE";
  readonly url: string;
  readonly headers: Readonly<Record<string, string>>;
  readonly body: string | null;
  readonly allowUntrustedTls: boolean;
}

export interface HttpResponse {
  readonly status: number;
  readonly body: string;
}

export interface HttpPort {
  request(input: HttpRequest): Promise<HttpResponse>;
}

function base64Utf8(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function root(config: WordPressConnectionConfig): string {
  const base = config.baseUrl.trim().replace(/\/+$/, "");
  if (!base) throw new Error("WordPress base URL is empty.");
  return base.endsWith("/wp-json") ? base : base + "/wp-json";
}

function headers(config: WordPressConnectionConfig): Readonly<Record<string, string>> {
  return Object.freeze({
    Accept: "application/json",
    "Content-Type": "application/json",
    Authorization:
      "Basic " +
      base64Utf8(config.username + ":" + config.applicationPassword),
  });
}

function json(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function object(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? value as Record<string, unknown>
    : null;
}

function wpFailure(
  response: HttpResponse,
  fallbackMessage: string
): ReturnType<typeof classifyRestFailure> {
  const parsed = object(json(response.body));
  const data = object(parsed?.data);
  const status =
    typeof data?.status === "number"
      ? data.status
      : response.status;
  return classifyRestFailure({
    status,
    code: typeof parsed?.code === "string" ? parsed.code : null,
    message:
      typeof parsed?.message === "string"
        ? parsed.message
        : fallbackMessage,
  });
}

function invalid(message: string): WordPressResult<never> {
  return {
    ok: false,
    failure: {
      kind: "invalid-response",
      message,
      status: null,
      code: null,
    },
  };
}

function textField(
  value: unknown,
  rawPreferred = false
): string {
  if (typeof value === "string") return value;
  const obj = object(value);
  if (!obj) return "";
  if (rawPreferred && typeof obj.raw === "string") return obj.raw;
  if (typeof obj.rendered === "string") return obj.rendered;
  if (typeof obj.raw === "string") return obj.raw;
  return "";
}

function postView(value: unknown): WordPressPostView | null {
  const obj = object(value);
  if (
    !obj ||
    !Number.isInteger(obj.id) ||
    typeof obj.status !== "string"
  ) {
    return null;
  }
  return Object.freeze({
    id: Number(obj.id),
    status: obj.status,
    title: textField(obj.title, true),
    content: textField(obj.content, true),
  });
}

export class WordPressRestAdapter implements WordPressRestPort {
  constructor(private readonly http: HttpPort) {}

  private async call(
    config: WordPressConnectionConfig,
    method: HttpRequest["method"],
    path: string,
    body: unknown = null
  ): Promise<WordPressResult<unknown>> {
    let response: HttpResponse;
    try {
      response = await this.http.request({
        method,
        url: root(config) + path,
        headers: headers(config),
        body: body === null ? null : JSON.stringify(body),
        allowUntrustedTls: config.allowUntrustedTls,
      });
    } catch (error) {
      const message = String(error instanceof Error ? error.message : error);
      const lower = message.toLocaleLowerCase();
      return {
        ok: false,
        failure: classifyRestFailure({
          status: null,
          message,
          tls:
            lower.includes("certificate") ||
            lower.includes("ssl") ||
            lower.includes("tls"),
          network: !(
            lower.includes("certificate") ||
            lower.includes("ssl") ||
            lower.includes("tls")
          ),
        }),
      };
    }

    if (response.status < 200 || response.status >= 300) {
      return {
        ok: false,
        failure: wpFailure(
          response,
          `WordPress HTTP ${response.status}`
        ),
      };
    }

    const parsed = json(response.body);
    if (parsed === null) {
      return invalid("WordPress returned invalid JSON.");
    }
    return {ok: true, value: parsed};
  }

  async discover(
    config: WordPressConnectionConfig
  ): Promise<WordPressResult<WordPressRestDiscovery>> {
    const result = await this.call(config, "GET", "/");
    if (!result.ok) return result;

    const value = object(result.value);
    const auth = object(value?.authentication);
    const applicationPasswords =
      object(auth?.["application-passwords"]);

    return {
      ok: true,
      value: Object.freeze({
        siteName:
          typeof value?.name === "string" ? value.name : "",
        applicationPasswordsAvailable: Boolean(applicationPasswords),
      }),
    };
  }

  async currentUser(
    config: WordPressConnectionConfig
  ): Promise<WordPressResult<WordPressRestUser>> {
    const result = await this.call(
      config,
      "GET",
      "/wp/v2/users/me?context=edit"
    );
    if (!result.ok) return result;

    const value = object(result.value);
    if (!value || !Number.isInteger(value.id)) {
      return invalid("WordPress current-user response is invalid.");
    }

    return {
      ok: true,
      value: Object.freeze({
        id: Number(value.id),
        username:
          typeof value.username === "string" ? value.username : "",
        name: typeof value.name === "string" ? value.name : "",
      }),
    };
  }

  async introspectApplicationPassword(
    config: WordPressConnectionConfig
  ): Promise<WordPressResult<WordPressRestAppPassword>> {
    const result = await this.call(
      config,
      "GET",
      "/wp/v2/users/me/application-passwords/introspect"
    );
    if (!result.ok) return result;

    const value = object(result.value);
    if (
      !value ||
      typeof value.uuid !== "string"
    ) {
      return invalid("WordPress Application Password introspection response is invalid.");
    }

    return {
      ok: true,
      value: Object.freeze({
        uuid: value.uuid,
        name: typeof value.name === "string" ? value.name : "",
      }),
    };
  }

  async createDraft(
    config: WordPressConnectionConfig,
    input: {readonly title: string; readonly content: string}
  ): Promise<WordPressResult<WordPressPostView>> {
    const result = await this.call(
      config,
      "POST",
      "/wp/v2/posts",
      {
        status: "draft",
        title: input.title,
        content: input.content,
      }
    );
    if (!result.ok) return result;

    const post = postView(result.value);
    return post
      ? {ok: true, value: post}
      : invalid("WordPress create-post response is invalid.");
  }

  async getPost(
    config: WordPressConnectionConfig,
    postId: number
  ): Promise<WordPressResult<WordPressPostView>> {
    const result = await this.call(
      config,
      "GET",
      `/wp/v2/posts/${postId}?context=edit`
    );
    if (!result.ok) return result;

    const post = postView(result.value);
    return post
      ? {ok: true, value: post}
      : invalid("WordPress get-post response is invalid.");
  }

  async deletePost(
    config: WordPressConnectionConfig,
    postId: number
  ): Promise<WordPressResult<null>> {
    const result = await this.call(
      config,
      "DELETE",
      `/wp/v2/posts/${postId}?force=true`
    );
    return result.ok
      ? {ok: true, value: null}
      : result;
  }
}
