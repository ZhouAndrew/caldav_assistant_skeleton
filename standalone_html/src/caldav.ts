import { CalDAVError, createTransport, type Resource } from './transport.js';
const DAV = 'DAV:';
const CAL = 'urn:ietf:params:xml:ns:caldav';
export interface DavEntry { readonly href: string; readonly props: Element }
export type ParseXML = (text: string) => Document;
function children(parent: Element, ns: string, name: string): Element[] {
  return Array.from(parent.childNodes).filter((node): node is Element => node.nodeType === 1)
    .filter(node => node.namespaceURI === ns && node.localName === name);
}
export function property(parent: Element, ns: string, name: string): Element | undefined {
  return children(parent, ns, name)[0];
}
export function parseMultistatus(text: string, parse: ParseXML): readonly DavEntry[] {
  if (/<!DOCTYPE|<!ENTITY/i.test(text)) throw new CalDAVError('Validation');
  let document: Document;
  try { document = parse(text); } catch { throw new CalDAVError('Validation'); }
  const root = document.documentElement;
  if (!root || root.namespaceURI !== DAV || root.localName !== 'multistatus' || document.getElementsByTagName('parsererror').length) throw new CalDAVError('Validation');
  return children(root, DAV, 'response').map(response => {
    const href = property(response, DAV, 'href')?.textContent?.trim();
    if (!href) throw new CalDAVError('Validation');
    const status = property(response, DAV, 'status')?.textContent;
    if (status && !/^HTTP\/\S+ 2\d\d(?:\s|$)/.test(status)) throw new CalDAVError('Unavailable');
    const merged = document.createElementNS(DAV, 'props');
    if (!children(response, DAV, 'propstat').length) throw new CalDAVError('Validation');
    for (const propstat of children(response, DAV, 'propstat')) {
      const code = property(propstat, DAV, 'status')?.textContent ?? '';
      if (/^HTTP\/\S+ 2\d\d(?:\s|$)/.test(code)) {
        const props = property(propstat, DAV, 'prop');
        if (!props) throw new CalDAVError('Validation');
        for (const node of Array.from(props.childNodes)) merged.appendChild(node.cloneNode(true));
      } else if (!/^HTTP\/\S+ 404(?:\s|$)/.test(code)) {
        // A failed resource must not silently become an empty successful scan.
        throw new CalDAVError('Unavailable');
      }
    }
    return Object.freeze({ href, props: merged });
  });
}
export interface Calendar { readonly url: string; readonly name: string; readonly components: readonly string[] }
export function createCalDAV(transport: ReturnType<typeof createTransport>, baseUrl: string, parse: ParseXML) {
  function url(href: string, context: string): string {
    const resolved = new URL(href, context);
    if (resolved.origin !== new URL(baseUrl).origin || resolved.username || resolved.password) throw new CalDAVError('Validation');
    return resolved.href;
  }
  async function propfind(target: string, names: string, depth = '0') {
    const response = await transport.request('PROPFIND', target,
      `<d:propfind xmlns:d="DAV:" xmlns:c="${CAL}"><d:prop>${names}</d:prop></d:propfind>`, { Depth: depth });
    return parseMultistatus(await response.text(), parse);
  }
  async function discover(): Promise<readonly Calendar[]> {
    const initial = await propfind(baseUrl, '<d:current-user-principal/><c:calendar-home-set/><d:resourcetype/>');
    const own = initial.find(entry => url(entry.href, baseUrl) === new URL(baseUrl).href);
    if (!own) throw new CalDAVError('Validation');
    let homeContext = baseUrl;
    let home = property(own.props, CAL, 'calendar-home-set');
    if (!home) {
      const principal = property(property(own.props, DAV, 'current-user-principal') ?? own.props, DAV, 'href')?.textContent;
      if (!principal) throw new CalDAVError('Validation');
      const principalUrl = url(principal, baseUrl);
      homeContext = principalUrl;
      const entries = await propfind(principalUrl, '<c:calendar-home-set/>');
      home = property(entries.find(entry => url(entry.href, principalUrl) === principalUrl)?.props ?? own.props, CAL, 'calendar-home-set');
    }
    const hrefs = home ? children(home, DAV, 'href') : [];
    if (!hrefs.length) throw new CalDAVError('Validation');
    const calendars: Calendar[] = [];
    for (const href of hrefs) {
      const homeUrl = url(href.textContent ?? '', homeContext);
      const entries = await propfind(homeUrl, '<d:resourcetype/><d:displayname/><c:supported-calendar-component-set/>', '1');
      for (const entry of entries) {
        const type = property(entry.props, DAV, 'resourcetype');
        if (!type || !property(type, CAL, 'calendar')) continue;
        const components = property(entry.props, CAL, 'supported-calendar-component-set');
        calendars.push(Object.freeze({ url: url(entry.href, homeUrl), name: property(entry.props, DAV, 'displayname')?.textContent ?? entry.href,
          components: Object.freeze(components ? children(components, CAL, 'comp').map(comp => comp.getAttribute('name') ?? '') : []) }));
      }
    }
    return Object.freeze(Array.from(new Map(calendars.map(calendar => [calendar.url, calendar])).values()));
  }
  async function components(calendar: Calendar, component: 'VTODO'|'VEVENT'): Promise<readonly Resource[]> {
    const response = await transport.request('REPORT', calendar.url,
      `<c:calendar-query xmlns:d="DAV:" xmlns:c="${CAL}"><d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="${component}"/></c:comp-filter></c:filter></c:calendar-query>`, { Depth: '1' });
    const resources = parseMultistatus(await response.text(), parse).map(entry => {
      const etag = property(entry.props, DAV, 'getetag')?.textContent;
      const text = property(entry.props, CAL, 'calendar-data')?.textContent;
      if (!etag || etag.startsWith('W/') || !text) throw new CalDAVError('Validation');
      return Object.freeze({ url: url(entry.href, calendar.url), etag, text });
    });
    if (new Set(resources.map(resource => resource.url)).size !== resources.length) throw new CalDAVError('Validation');
    return Object.freeze(resources);
  }
  return Object.freeze({ discover, tasks:(calendar:Calendar)=>components(calendar,'VTODO'), events:(calendar:Calendar)=>components(calendar,'VEVENT') });
}
