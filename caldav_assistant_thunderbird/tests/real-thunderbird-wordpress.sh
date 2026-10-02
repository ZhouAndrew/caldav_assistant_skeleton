#!/usr/bin/env bash
set -euo pipefail

TB_VERSION="${1:-153.1.0esr}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
TB_PID=""
XVFB_PID=""
REPORT_PID=""
WM_PID=""
RUN_TAG="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
DB_NAME="caldav-tb-wp-db-${RUN_TAG}"
WEB_NAME="caldav-tb-wp-web-${RUN_TAG}"
NET_NAME="caldav-tb-wp-net-${RUN_TAG}"
VOL_NAME="caldav-tb-wp-data-${RUN_TAG}"
CADDY_NAME="caldav-tb-wp-caddy-${RUN_TAG}"
WP_BASE_URL="https://localhost:8443"

cleanup() {
  set +e
  [[ -n "$TB_PID" ]] && kill "$TB_PID" 2>/dev/null || true
  [[ -n "$XVFB_PID" ]] && kill "$XVFB_PID" 2>/dev/null || true
  [[ -n "$REPORT_PID" ]] && kill "$REPORT_PID" 2>/dev/null || true
  [[ -n "$WM_PID" ]] && kill "$WM_PID" 2>/dev/null || true
  docker logs "$CADDY_NAME" >"$TMP/caddy.log" 2>&1 || true
  docker logs "$WEB_NAME" >"$TMP/wordpress-web.log" 2>&1 || true
  docker logs "$DB_NAME" >"$TMP/wordpress-db.log" 2>&1 || true
  docker rm -f "$CADDY_NAME" "$WEB_NAME" "$DB_NAME" 2>/dev/null || true
  docker volume rm "$VOL_NAME" 2>/dev/null || true
  docker network rm "$NET_NAME" 2>/dev/null || true
  if [[ -n "${ACCEPTANCE_ARTIFACT_DIR:-}" ]]; then
    mkdir -p "$ACCEPTANCE_ARTIFACT_DIR"
    for candidate in "$TMP/report.json" "$TMP/thunderbird.stdout" "$TMP/thunderbird.stderr" "$TMP/wordpress-web.log" "$TMP/wordpress-db.log" "$TMP/caddy.log" "$TMP/xvfb.log" "$TMP/openbox.log"; do
      [[ -f "$candidate" ]] && cp "$candidate" "$ACCEPTANCE_ARTIFACT_DIR/" || true
    done
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "== Start isolated real WordPress =="
docker network create "$NET_NAME" >/dev/null
docker volume create "$VOL_NAME" >/dev/null

docker run -d --name "$DB_NAME" \
  --network "$NET_NAME" \
  -e MARIADB_DATABASE=wordpress \
  -e MARIADB_USER=wordpress \
  -e MARIADB_PASSWORD=wordpress \
  -e MARIADB_ROOT_PASSWORD=root \
  mariadb:11.4 >/dev/null

DB_READY=0
for _ in $(seq 1 120); do
  if docker exec "$DB_NAME" mariadb-admin ping -uroot -proot --silent >/dev/null 2>&1; then
    DB_READY=1
    break
  fi
  if [[ "$(docker inspect -f '{{.State.Running}}' "$DB_NAME" 2>/dev/null || true)" != "true" ]]; then
    break
  fi
  sleep 1
done
if [[ "$DB_READY" != 1 ]]; then
  echo "MariaDB fixture failed to become ready"
  docker logs "$DB_NAME" || true
  exit 1
fi

docker run -d --name "$WEB_NAME" \
  --network "$NET_NAME" \
  -p 8080:80 \
  -v "$VOL_NAME":/var/www/html \
  -e WORDPRESS_DB_HOST="$DB_NAME":3306 \
  -e WORDPRESS_DB_USER=wordpress \
  -e WORDPRESS_DB_PASSWORD=wordpress \
  -e WORDPRESS_DB_NAME=wordpress \
  -e "WORDPRESS_CONFIG_EXTRA=define('WP_ENVIRONMENT_TYPE','local');" \
  wordpress:latest >/dev/null

WP_FILES_READY=0
for _ in $(seq 1 120); do
  if docker exec "$WEB_NAME" test -f /var/www/html/wp-config.php; then
    WP_FILES_READY=1
    break
  fi
  if [[ "$(docker inspect -f '{{.State.Running}}' "$WEB_NAME" 2>/dev/null || true)" != "true" ]]; then
    break
  fi
  sleep 1
done
if [[ "$WP_FILES_READY" != 1 ]]; then
  echo "WordPress fixture failed to become ready"
  docker logs "$WEB_NAME" || true
  exit 1
fi

WPCLI=(docker run --rm --network "$NET_NAME" -v "$VOL_NAME":/var/www/html -e WORDPRESS_DB_HOST="$DB_NAME":3306 -e WORDPRESS_DB_USER=wordpress -e WORDPRESS_DB_PASSWORD=wordpress -e WORDPRESS_DB_NAME=wordpress wordpress:cli)
"${WPCLI[@]}" --path=/var/www/html core install \
  --url="$WP_BASE_URL" \
  --title="Thunderbird WordPress Acceptance" \
  --admin_user=wp_user \
  --admin_password=admin-test-only \
  --admin_email=acceptance@example.test \
  --skip-email >/dev/null

echo "== Start private-CA HTTPS reverse proxy =="
mkdir -p "$TMP/certs"
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$TMP/certs/ca.key" \
  -out "$TMP/certs/ca.crt" \
  -subj "/CN=CalDAV Assistant Test CA" \
  -days 2 >/dev/null 2>&1
openssl req -newkey rsa:2048 -nodes \
  -keyout "$TMP/certs/server.key" \
  -out "$TMP/certs/server.csr" \
  -subj "/CN=localhost" >/dev/null 2>&1
cat >"$TMP/certs/server.ext" <<'EOF'
subjectAltName=DNS:localhost,IP:127.0.0.1
extendedKeyUsage=serverAuth
EOF
openssl x509 -req \
  -in "$TMP/certs/server.csr" \
  -CA "$TMP/certs/ca.crt" \
  -CAkey "$TMP/certs/ca.key" \
  -CAcreateserial \
  -out "$TMP/certs/server.crt" \
  -days 2 -sha256 \
  -extfile "$TMP/certs/server.ext" >/dev/null 2>&1

cat >"$TMP/Caddyfile" <<EOF
:443 {
  tls /etc/caddy/certs/server.crt /etc/caddy/certs/server.key
  reverse_proxy $WEB_NAME:80
}
EOF

docker run -d --name "$CADDY_NAME" \
  --network "$NET_NAME" \
  -p 8443:443 \
  -v "$TMP/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -v "$TMP/certs:/etc/caddy/certs:ro" \
  caddy:2.10-alpine >/dev/null

HTTPS_READY=0
for _ in $(seq 1 120); do
  if curl --cacert "$TMP/certs/ca.crt" -fsS "$WP_BASE_URL/wp-json/" >/dev/null 2>&1; then
    HTTPS_READY=1
    break
  fi
  sleep 1
done
if [[ "$HTTPS_READY" != 1 ]]; then
  echo "HTTPS WordPress fixture failed to become ready"
  docker logs "$CADDY_NAME" || true
  docker logs "$WEB_NAME" || true
  exit 1
fi
docker exec "$WEB_NAME" chown -R www-data:www-data /var/www/html
"${WPCLI[@]}" --path=/var/www/html rewrite structure '/%postname%/' --hard >/dev/null
"${WPCLI[@]}" --path=/var/www/html rewrite flush --hard >/dev/null
APP_PASS="$("${WPCLI[@]}" --path=/var/www/html user application-password create wp_user "Thunderbird CI" --porcelain)"
test -n "$APP_PASS"
WP_AUTH="$(printf 'wp_user:%s' "$APP_PASS" | base64 -w0)"
curl -fsS \
  --cacert "$TMP/certs/ca.crt" \
  -H "Authorization: Basic $WP_AUTH" \
  "$WP_BASE_URL/wp-json/wp/v2/users/me?context=edit" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("id")==1 and d.get("slug")=="wp_user", d'
echo "PASS: real WordPress + real Application Password prepared"

WPCLI_BRIDGE="$TMP/wp-cli-bridge"
cat >"$WPCLI_BRIDGE" <<SH
#!/usr/bin/env bash
exec docker run --rm --user 0:0 \
  --network "$NET_NAME" \
  -v "$VOL_NAME":/var/www/html \
  -v /tmp:/tmp:ro \
  -e WORDPRESS_DB_HOST="$DB_NAME":3306 \
  -e WORDPRESS_DB_USER=wordpress \
  -e WORDPRESS_DB_PASSWORD=wordpress \
  -e WORDPRESS_DB_NAME=wordpress \
  wordpress:cli --allow-root "\$@"
SH
chmod +x "$WPCLI_BRIDGE"
"$WPCLI_BRIDGE" --path=/var/www/html core is-installed
echo "PASS: host-callable WP-CLI bridge prepared"

HELPER_DIR="$TMP/legacy-wordpress-helpers"
HELPER_USED="$TMP/legacy-helper-used.log"
mkdir -p "$HELPER_DIR"

cat >"$HELPER_DIR/find-today-post.sh" <<SH
#!/usr/bin/env bash
set -euo pipefail
echo find >>"$HELPER_USED"
month_full="\$(date +%B)"
month_abbr="\$(date +%b)"
day="\$((10#\$(date +%d)))"
weekday="\$(date +%A)"
year="\$(date +%Y)"
json="\$("$WPCLI_BRIDGE" --path=/var/www/html post list \
  --post_type=post --post_status=any \
  --fields=ID,post_title --format=json)"
python3 - "\$month_full" "\$month_abbr" "\$day" "\$weekday" "\$year" "\$json" <<'PY'
import json, re, sys
month_full, month_abbr, day, weekday, year, raw = sys.argv[1:]
items = json.loads(raw)
for item in items:
    title = str(item.get("post_title") or "")
    folded = title.casefold()
    if (
        (month_full.casefold() in folded or month_abbr.casefold() in folded)
        and re.search(rf"(?<!\d){re.escape(day)}(?!\d)", title)
        and weekday.casefold() in folded
        and year in title
    ):
        print(item["ID"])
        raise SystemExit(0)
print(f"No post found for today (must contain: {month_full}/{month_abbr}, {day}, {weekday}, {year})")
PY
SH

cat >"$HELPER_DIR/create-post.sh" <<SH
#!/usr/bin/env bash
set -euo pipefail
echo create >>"$HELPER_USED"
existing="\$("$HELPER_DIR/find-today-post.sh")"
if [[ "\$existing" =~ ^[0-9]+$ ]]; then
  echo "✔ Today's post exists: \$existing"
  exit 0
fi
month_full="\$(date +%B)"
day="\$((10#\$(date +%d)))"
weekday="\$(date +%A)"
year="\$(date +%Y)"
post_title="\$month_full \$day  \$weekday  \$year"
post_id="\$("$WPCLI_BRIDGE" --path=/var/www/html post create \
  --post_type=post --post_status=publish \
  --post_title="\$post_title" --porcelain)"
echo "✔ Created today's post: \$post_id"
SH
chmod +x "$HELPER_DIR/find-today-post.sh" "$HELPER_DIR/create-post.sh"
echo "PASS: legacy find-today-post.sh/create-post.sh fixture prepared"

echo "== Build production and instrumented XPI =="
chmod +x "$ROOT/packaging/build-xpi.sh"
"$ROOT/packaging/build-xpi.sh" "$TMP/base.xpi"
python3 "$ROOT/tests/check-xpi.py" "$TMP/base.xpi"
mkdir -p "$TMP/addon"
(cd "$TMP/addon" && unzip -q "$TMP/base.xpi")

python3 - "$TMP/addon" "$APP_PASS" "$WPCLI_BRIDGE" "$WP_BASE_URL" "$HELPER_DIR" <<'PY'
from pathlib import Path
import json
import sys

root = Path(sys.argv[1])
app_password = sys.argv[2]
wp_cli_executable = sys.argv[3]
wp_base_url = sys.argv[4]
helper_dir = sys.argv[5]
manifest_path = root / "manifest.json"
manifest = json.loads(manifest_path.read_text())
permissions = manifest.setdefault("permissions", [])
report_host = "http://127.0.0.1/*"
if report_host not in permissions:
    permissions.append(report_host)
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

wordpress_page = root / "wordpress.js"
wordpress_page.write_text(wordpress_page.read_text() + r'''

const __WP_ACCEPTANCE_REPORT = "http://127.0.0.1:8766";
async function __wpAcceptPost(path, payload = {}) {
  await fetch(__WP_ACCEPTANCE_REPORT + path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
}
async function __wpAcceptWaitReceipt(action, timeoutMs = 30000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const receipt = await AssistantStorage.getLastReceipt();
    if (receipt?.action === action) return receipt;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error("timeout waiting for " + action);
}
async function __runRealWordPressAcceptance() {
  await new Promise(resolve => setTimeout(resolve, 1000));
  $("wp-url").value = __WP_BASE_URL__;
  $("wp-user").value = "wp_user";
  $("wp-password").value = __WP_APP_PASSWORD__;

  const quick = $("quick");
  quick.style.position = "fixed";
  quick.style.left = "24px";
  quick.style.top = "24px";
  quick.style.zIndex = "999999";
  quick.focus();
  quick.addEventListener("click", () => {
    void __wpAcceptPost("/quick-clicked");
  }, {once: true});
  const quickRect = quick.getBoundingClientRect();
  await __wpAcceptPost("/quick-geometry", {
    innerScreenX: window.mozInnerScreenX,
    innerScreenY: window.mozInnerScreenY,
    x: quickRect.x,
    y: quickRect.y,
    width: quickRect.width,
    height: quickRect.height,
  });
  await __wpAcceptPost("/quick-ready");

  const quickResult = await __wpAcceptWaitReceipt("connection.wordpress-quick");
  if (!quickResult.success) {
    throw new Error("quick test failed: " + (quickResult.summary || JSON.stringify(quickResult)));
  }
  const full = $("full");
  full.style.position = "fixed";
  full.style.left = "24px";
  full.style.top = "24px";
  full.style.zIndex = "999999";
  full.focus();
  const fullRect = full.getBoundingClientRect();
  await __wpAcceptPost("/full-geometry", {
    innerScreenX: window.mozInnerScreenX,
    innerScreenY: window.mozInnerScreenY,
    x: fullRect.x,
    y: fullRect.y,
    width: fullRect.width,
    height: fullRect.height,
  });
  await __wpAcceptPost("/full-ready");

  const fullResult = await __wpAcceptWaitReceipt("connection.wordpress-full-write", 45000);
  if (!fullResult.success) {
    throw new Error("full test failed: " + (fullResult.summary || JSON.stringify(fullResult)));
  }
  if (!fullResult.steps.some(step => step.name === "update + read-back TEST post")) {
    throw new Error("full test did not verify post update read-back");
  }
  if (!fullResult.steps.some(step => step.name === "read TEST media")) {
    throw new Error("full test did not verify media read-back");
  }

  await AssistantWordPress.saveConfig({
    transport: "wp-cli",
    wordpressPath: "/var/www/html",
    wpCliCommand: __WP_CLI_EXECUTABLE__,
    legacyHelperDir: __WP_HELPER_DIR__,
  });

  const cliQuick = await AssistantWordPress.quickTest();
  if (!cliQuick.success || cliQuick.transport !== "wp-cli") {
    throw new Error("WP-CLI quick test failed: " + (cliQuick.summary || JSON.stringify(cliQuick)));
  }

  const cliFull = await AssistantWordPress.fullWriteTest();
  if (!cliFull.success) {
    throw new Error("WP-CLI full test failed: " + (cliFull.summary || JSON.stringify(cliFull)));
  }

  const cliLog = await AssistantWordPress.createLog({
    content: "THUNDERBIRD REAL WPCLI DAILY LOG",
    files: [],
  });
  if (!cliLog.success || !cliLog.post?.id) {
    throw new Error("WP-CLI daily log failed: " + (cliLog.summary || JSON.stringify(cliLog)));
  }

  await AssistantWordPress.saveConfig({
    transport: "application-password",
    baseUrl: __WP_BASE_URL__,
    username: "wp_user",
    applicationPassword: __WP_APP_PASSWORD__,
    wordpressPath: "/var/www/html",
    wpCliCommand: __WP_CLI_EXECUTABLE__,
    legacyHelperDir: __WP_HELPER_DIR__,
  });

  const restLog = await AssistantWordPress.createLog({
    content: "THUNDERBIRD REAL REST DAILY LOG",
    files: [],
  });
  if (!restLog.success || restLog.post?.id !== cliLog.post.id) {
    throw new Error(
      "WP-CLI/REST daily log mismatch: " +
      JSON.stringify({cli: cliLog.post, rest: restLog.post, summary: restLog.summary})
    );
  }

  await __wpAcceptPost("/report", {
    ok: true,
    quick: true,
    fullWrite: true,
    cleanup: true,
    wpCliQuick: true,
    wpCliFull: true,
    dualDailyLog: true,
    dailyPostId: restLog.post.id,
  });
}
setTimeout(() => {
  __runRealWordPressAcceptance().catch(async error => {
    await __wpAcceptPost("/report", {
      ok: false,
      error: (error?.message || String(error)) + (error?.stack ? "\n" + error.stack : ""),
    });
  });
}, 500);
'''.replace("__WP_APP_PASSWORD__", json.dumps(app_password))
   .replace("__WP_CLI_EXECUTABLE__", json.dumps(wp_cli_executable))
   .replace("__WP_BASE_URL__", json.dumps(wp_base_url))
   .replace("__WP_HELPER_DIR__", json.dumps(helper_dir)) + "\n")

background = root / "background.js"
background.write_text(background.read_text() + r'''
setTimeout(() => {
  browser.tabs.create({
    url: browser.runtime.getURL("wordpress.html"),
  });
}, 1500);
''' + "\n")
PY

(cd "$TMP/addon" && zip -qr "$TMP/acceptance.xpi" .)

echo "== Start acceptance report endpoint =="
cat >"$TMP/report_server.py" <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys

root = Path(sys.argv[1])
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length)
        name = self.path.strip("/") or "unknown"
        if name == "report":
            (root / "report.json").write_bytes(data)
        else:
            (root / name).write_bytes(data)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
    def log_message(self, *_args):
        pass

HTTPServer(("127.0.0.1", 8766), Handler).serve_forever()
PY
python3 "$TMP/report_server.py" "$TMP" >/dev/null 2>&1 &
REPORT_PID=$!

echo "== Download official Thunderbird $TB_VERSION =="
curl -fL --retry 3 --retry-delay 2 \
  "https://archive.mozilla.org/pub/thunderbird/releases/$TB_VERSION/linux-x86_64/en-US/thunderbird-$TB_VERSION.tar.xz" \
  -o "$TMP/thunderbird.tar.xz"
tar -xJf "$TMP/thunderbird.tar.xz" -C "$TMP"

PROFILE="$TMP/profile"
mkdir -p "$PROFILE/extensions"
certutil -N -d "sql:$PROFILE" --empty-password
certutil -A -d "sql:$PROFILE" \
  -n "CalDAV Assistant Test CA" \
  -t "C,," \
  -i "$TMP/certs/ca.crt"
certutil -L -d "sql:$PROFILE" | grep -F "CalDAV Assistant Test CA"
EXT_ID='ZhouAndrew.thunderbird-taskfix-lab@addons.thunderbird.net'
cp "$TMP/acceptance.xpi" "$PROFILE/extensions/$EXT_ID.xpi"
cat >"$PROFILE/user.js" <<'EOF'
user_pref("app.update.enabled", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("extensions.autoDisableScopes", 0);
user_pref("extensions.enabledScopes", 15);
user_pref("xpinstall.signatures.required", false);
user_pref("mail.provider.suppress_dialog_on_startup", true);
user_pref("mailnews.start_page.override_url", "about:blank");
user_pref("mailnews.start_page.url", "about:blank");
EOF

echo "== Start real Thunderbird under Xvfb =="
Xvfb :99 -screen 0 1280x1024x24 >"$TMP/xvfb.log" 2>&1 &
XVFB_PID=$!
export DISPLAY=:99
sleep 0.5
openbox --sm-disable >"$TMP/openbox.log" 2>&1 &
WM_PID=$!
sleep 0.5
kill -0 "$WM_PID"
"$TMP/thunderbird/thunderbird" -no-remote -profile "$PROFILE" >"$TMP/thunderbird.stdout" 2>"$TMP/thunderbird.stderr" &
TB_PID=$!

for _ in $(seq 1 300); do
  [[ -f "$TMP/quick-ready" ]] && break
  sleep 0.1
done
[[ -f "$TMP/quick-ready" ]] || { echo "Tools did not become ready"; exit 1; }

echo "== Native click: run real WordPress quick authentication test =="
WIN="$(xdotool search --onlyvisible --pid "$TB_PID" | tail -n1)"
test -n "$WIN"
echo "WordPress tools popup window: $WIN"
xdotool getwindowgeometry "$WIN" || true

# The acceptance copy fixes wp-quick at left:24px/top:24px in a popup window.
# This is a real X mouse event, so Thunderbird's user-activation bookkeeping
# sees the same kind of click as a person pressing the button.
# Firefox exposes the exact content viewport origin through mozInnerScreenX/Y.
# Use that plus the real DOM button rectangle, then issue a native absolute X click.
# This avoids guessing title-bar/frame sizes and still satisfies the user-gesture gate.
read CLICK_X CLICK_Y < <(python3 - "$TMP/quick-geometry" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
print(
    round(d["innerScreenX"] + d["x"] + d["width"]/2),
    round(d["innerScreenY"] + d["y"] + d["height"]/2),
)
PY
)
echo "wp-quick absolute click: $CLICK_X,$CLICK_Y"
xdotool mousemove "$CLICK_X" "$CLICK_Y" click 1
for _ in $(seq 1 50); do
  [[ -f "$TMP/quick-clicked" ]] && break
  sleep 0.1
done
[[ -f "$TMP/quick-clicked" ]] || { echo "Native click did not reach wp-quick"; exit 1; }

for _ in $(seq 1 300); do
  [[ -f "$TMP/full-ready" ]] && break
  [[ -s "$TMP/report.json" ]] && break
  sleep 0.1
done
if [[ -s "$TMP/report.json" && ! -f "$TMP/full-ready" ]]; then
  cat "$TMP/report.json"
  exit 1
fi
[[ -f "$TMP/full-ready" ]] || { echo "Quick WordPress acceptance did not complete"; exit 1; }

echo "== Native mouse click: run real full WordPress write/read/update/media/delete =="
read FULL_X FULL_Y < <(python3 - "$TMP/full-geometry" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
print(
    round(d["innerScreenX"] + d["x"] + d["width"]/2),
    round(d["innerScreenY"] + d["y"] + d["height"]/2),
)
PY
)
echo "wp-full absolute click: $FULL_X,$FULL_Y"
xdotool mousemove "$FULL_X" "$FULL_Y" click 1

for _ in $(seq 1 600); do
  [[ -s "$TMP/report.json" ]] && break
  sleep 0.1
done
[[ -s "$TMP/report.json" ]] || { echo "No acceptance report"; exit 1; }

python3 - "$TMP/report.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
assert data.get("ok") is True, data
for key in ("quick", "fullWrite", "cleanup", "wpCliQuick", "wpCliFull", "dualDailyLog"):
    assert data.get(key) is True, (key, data)
print("REAL THUNDERBIRD + REAL WORDPRESS REST + WP-CLI ACCEPTANCE: PASS")
PY

grep -qx 'find' "$HELPER_USED"
grep -qx 'create' "$HELPER_USED"
echo "PASS: legacy find-today-post.sh and create-post.sh were really executed"

docker logs "$CADDY_NAME" >"$TMP/caddy.log" 2>&1 || true
docker logs "$WEB_NAME" >"$TMP/wordpress-web.log" 2>&1 || true
docker logs "$DB_NAME" >"$TMP/wordpress-db.log" 2>&1 || true
