import {
  WordPressConnectionConfig,
  WordPressFailure,
} from "./types";

export type WordPressResult<T> =
  | {readonly ok: true; readonly value: T}
  | {readonly ok: false; readonly failure: WordPressFailure};

export interface WordPressRestDiscovery {
  readonly siteName: string;
  readonly applicationPasswordsAvailable: boolean;
}

export interface WordPressRestUser {
  readonly id: number;
  readonly username: string;
  readonly name: string;
}

export interface WordPressRestAppPassword {
  readonly uuid: string;
  readonly name: string;
}

export interface WordPressPostView {
  readonly id: number;
  readonly status: string;
  readonly title: string;
  readonly content: string;
}

export interface WordPressRestPort {
  discover(
    config: WordPressConnectionConfig
  ): Promise<WordPressResult<WordPressRestDiscovery>>;

  currentUser(
    config: WordPressConnectionConfig
  ): Promise<WordPressResult<WordPressRestUser>>;

  introspectApplicationPassword(
    config: WordPressConnectionConfig
  ): Promise<WordPressResult<WordPressRestAppPassword>>;

  createDraft(
    config: WordPressConnectionConfig,
    input: {readonly title: string; readonly content: string}
  ): Promise<WordPressResult<WordPressPostView>>;

  getPost(
    config: WordPressConnectionConfig,
    postId: number
  ): Promise<WordPressResult<WordPressPostView>>;

  deletePost(
    config: WordPressConnectionConfig,
    postId: number
  ): Promise<WordPressResult<null>>;
}

export interface WordPressCliProbe {
  readonly version: string;
  readonly blogName: string;
}

export interface WordPressCliPort {
  probe(
    config: WordPressConnectionConfig
  ): Promise<WordPressResult<WordPressCliProbe>>;

  createDraft(
    config: WordPressConnectionConfig,
    input: {readonly title: string; readonly content: string}
  ): Promise<WordPressResult<WordPressPostView>>;

  getPost(
    config: WordPressConnectionConfig,
    postId: number
  ): Promise<WordPressResult<WordPressPostView>>;

  deletePost(
    config: WordPressConnectionConfig,
    postId: number
  ): Promise<WordPressResult<null>>;
}
