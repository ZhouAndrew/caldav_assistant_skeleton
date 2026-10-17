export type WordPressTransport =
  | "application-password"
  | "wp-cli";

export type WordPressConfiguredTransport =
  | "auto"
  | WordPressTransport;

export type WordPressFailureKind =
  | "configuration"
  | "network"
  | "tls"
  | "authentication"
  | "authorization"
  | "endpoint"
  | "request"
  | "server"
  | "invalid-response"
  | "process";

export interface WordPressFailure {
  readonly kind: WordPressFailureKind;
  readonly message: string;
  readonly status: number | null;
  readonly code: string | null;
}

export interface WordPressConnectionConfig {
  readonly transport: WordPressConfiguredTransport;
  readonly baseUrl: string;
  readonly username: string;
  readonly applicationPassword: string;
  readonly wordpressPath: string;
  readonly wpCliCommand: string;
  readonly allowUntrustedTls: boolean;
}

export interface WordPressTransportPlan {
  readonly ok: true;
  readonly primary: WordPressTransport;
  readonly fallback: WordPressTransport | null;
}

export interface WordPressTransportPlanError {
  readonly ok: false;
  readonly failure: WordPressFailure;
}

export type WordPressTransportPlanResult =
  | WordPressTransportPlan
  | WordPressTransportPlanError;
