"""Launch disposable real Radicale and static HTML servers, then verify adapters/UI."""
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def port():
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0))
        return server.getsockname()[1]


def ready(url):
    for _ in range(100):
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except Exception:
            time.sleep(.1)
    raise RuntimeError('Test service did not start')


with tempfile.TemporaryDirectory(prefix='caldav-html-test-') as folder:
    root = pathlib.Path(folder)
    dav_port, web_port = port(), port()
    dav_origin = f'http://127.0.0.1:{dav_port}'
    web_origin = f'http://127.0.0.1:{web_port}'
    config = root / 'config'
    config.write_text(f'''[server]
hosts = 127.0.0.1:{dav_port}
[auth]
type = none
[storage]
filesystem_folder = {root / 'storage'}
[headers]
Access-Control-Allow-Origin = {web_origin}
Access-Control-Allow-Methods = GET, PUT, DELETE, PROPFIND, REPORT, MKCALENDAR, OPTIONS
Access-Control-Allow-Headers = Authorization, Content-Type, Depth, If-Match, If-None-Match
Access-Control-Expose-Headers = ETag
''')
    with open(root / 'radicale.log', 'w') as log:
        dav = subprocess.Popen([sys.executable, '-m', 'radicale', '--config', str(config)], stdout=log, stderr=log)
        web = subprocess.Popen([sys.executable, '-m', 'http.server', str(web_port), '--bind', '127.0.0.1'], stdout=log, stderr=log)
        try:
            ready(dav_origin)
            ready(web_origin)
            env = dict(os.environ, CALDAV_TEST_URL=dav_origin + '/test/', SELECTOR_TEST_URL=web_origin + '/selector.html')
            subprocess.run(['node', 'tests/real-radicale.mjs'], env=env, check=True)
            if '--browser' in sys.argv:
                # Only disposable fixture data is created.
                def request(method, path, body=None):
                    headers = {'Authorization': 'Basic dGVzdDp0ZXN0'}
                    if body is not None:
                        headers['Content-Type'] = 'text/calendar' if method == 'PUT' else 'application/xml'
                    req = urllib.request.Request(dav_origin + path, data=body.encode() if body else None, headers=headers, method=method)
                    urllib.request.urlopen(req).close()
                request('MKCALENDAR', '/test/browser/', '<c:mkcalendar xmlns:c="urn:ietf:params:xml:ns:caldav"/>')
                text = '\r\n'.join(['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Browser Test//EN','BEGIN:VTODO','UID:browser-task','DTSTAMP:20261007T000000Z','SUMMARY:Browser task','STATUS:NEEDS-ACTION','END:VTODO','END:VCALENDAR',''])
                request('PUT', '/test/browser/task.ics', text)
                event = '\r\n'.join(['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Browser Test//EN','BEGIN:VEVENT','UID:browser-event','DTSTAMP:20261009T000000Z','SUMMARY:Browser lesson','DTSTART;TZID=Asia/Shanghai:20261009T090000','DTEND;TZID=Asia/Shanghai:20261009T100000','LOCATION:Room 1','END:VEVENT','END:VCALENDAR',''])
                request('PUT', '/test/browser/event.ics', event)
                subprocess.run(['node', 'tests/browser.mjs'], env=env, check=True)
        except Exception:
            print((root / 'radicale.log').read_text(), file=sys.stderr)
            raise
        finally:
            for process in [web, dav]:
                process.terminate()
                process.wait(timeout=10)
