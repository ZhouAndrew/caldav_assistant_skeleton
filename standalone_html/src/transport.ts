export type ErrorCode = 'Permission' | 'NotFound' | 'Conflict' | 'Unavailable' | 'Validation';
export class CalDAVError extends Error {
  constructor(readonly code: ErrorCode, readonly status: number | null = null) {
    super(`CalDAV ${code}${status === null ? '' : ` (${status})`}`);
  }
}
export interface Resource { readonly url: string; readonly etag: string; readonly text: string }
export interface Receipt { readonly verified: true; readonly resource: Resource }
export interface Options {
  readonly baseUrl: string;
  readonly authorization?: string;
  readonly fetch: typeof fetch;
  readonly timeoutMs?: number;
}
/** HTTP effect boundary. No workflow state, credential persistence or implicit clock. */
export function createTransport(options: Options) {
  const base = new URL(options.baseUrl);
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password) {
    throw new CalDAVError('Validation');
  }
  function resolve(href: string): string {
    const url = new URL(href, base);
    // Never forward credentials to a server-provided foreign origin.
    if (url.origin !== base.origin || url.username || url.password) throw new CalDAVError('Validation');
    return url.href;
  }
  async function request(method: string, href: string, body?: string, extra: Record<string, string> = {}) {
    const headers = new Headers(extra);
    if (options.authorization) headers.set('Authorization', options.authorization);
    if (body !== undefined && !headers.has('Content-Type')) headers.set('Content-Type', 'application/xml; charset=utf-8');
    let response: Response;
    try {
      response = await options.fetch(resolve(href), {
        method, headers, ...(body === undefined ? {} : { body }),
        redirect: 'error', cache: 'no-store', credentials: 'omit',
        signal: AbortSignal.timeout(options.timeoutMs ?? 15000),
      });
    } catch (error) {
      if (error instanceof CalDAVError) throw error;
      // Browser network/CORS/TLS exceptions can contain credential-bearing details.
      throw new CalDAVError('Unavailable');
    }
    if (!response.ok) {
      const code: ErrorCode = response.status === 401 || response.status === 403 ? 'Permission'
        : response.status === 404 ? 'NotFound'
        : response.status === 409 || response.status === 412 ? 'Conflict' : 'Unavailable';
      throw new CalDAVError(code, response.status);
    }
    return response;
  }
  async function read(href: string): Promise<Resource> {
    const response = await request('GET', href);
    const etag = response.headers.get('ETag');
    if (!etag || etag.startsWith('W/')) throw new CalDAVError('Validation');
    return Object.freeze({ url: resolve(href), etag, text: await response.text() });
  }
  async function writeVerified(
    href: string, text: string, previousEtag: string | null,
    compare: (expected: string, actual: string) => boolean,
  ): Promise<Receipt> {
    if (previousEtag !== null && (!previousEtag || previousEtag.startsWith('W/'))) throw new CalDAVError('Validation');
    await request('PUT', href, text, {
      'Content-Type': 'text/calendar; charset=utf-8',
      ...(previousEtag === null ? { 'If-None-Match': '*' } : { 'If-Match': previousEtag }),
    });
    const resource = await read(href);
    // Comparator belongs to the pure iCalendar layer; servers may normalize bytes.
    if (!compare(text, resource.text)) throw new CalDAVError('Validation');
    return Object.freeze({ verified: true, resource });
  }
  return Object.freeze({ request, read, writeVerified });
}
