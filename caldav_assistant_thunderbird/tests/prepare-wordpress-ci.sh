#!/usr/bin/env bash
# Disposable CI fixture only. Never use an existing site or database.
set -euo pipefail
RUNTIME="${1:?Fresh runtime directory required}"
TB_VERSION="${2:-153.1.0esr}"
[[ ! -e "$RUNTIME" ]] || { echo 'Refusing an existing runtime'; exit 1; }
mkdir -p "$RUNTIME/deps"
RUNTIME="$(realpath "$RUNTIME")"
ln -s /usr "$RUNTIME/deps/usr"
curl -fL --retry 3 "https://archive.mozilla.org/pub/thunderbird/releases/$TB_VERSION/linux-x86_64/en-US/thunderbird-$TB_VERSION.tar.xz" -o "$RUNTIME/thunderbird.tar.xz"
tar -xJf "$RUNTIME/thunderbird.tar.xz" -C "$RUNTIME"
curl -fL --retry 3 https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar -o "$RUNTIME/wp-cli.phar"
cat > "$RUNTIME/wpcli" <<SH
#!/usr/bin/env bash
exec /usr/bin/php8.3 "$RUNTIME/wp-cli.phar" --allow-root "\$@"
SH
chmod +x "$RUNTIME/wpcli"
# The accepted driver supplies -c php.ini; load the normal system CLI extensions.
cp /etc/php/8.3/cli/php.ini "$RUNTIME/php.ini"
mariadb-install-db --no-defaults --basedir=/usr --datadir="$RUNTIME/mysql" --auth-root-authentication-method=normal > "$RUNTIME/db-init.log"
DB_PID=''
cleanup() {
  if [[ -n "$DB_PID" ]]; then kill "$DB_PID" 2>/dev/null || true; wait "$DB_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT
mariadbd --no-defaults --basedir=/usr --datadir="$RUNTIME/mysql" --socket= --port=13306 --bind-address=127.0.0.1 --user=root > "$RUNTIME/db-setup.log" 2>&1 &
DB_PID=$!
READY=0
for _ in $(seq 1 100); do
  if mariadb --no-defaults -h127.0.0.1 -P13306 -uroot -e 'SELECT 1;' >/dev/null 2>&1; then READY=1; break; fi
  sleep .2
done
[[ "$READY" == 1 ]]
mariadb --no-defaults -h127.0.0.1 -P13306 -uroot -e 'CREATE DATABASE wordpress;'
"$RUNTIME/wpcli" core download --path="$RUNTIME/wp"
"$RUNTIME/wpcli" config create --path="$RUNTIME/wp" --dbname=wordpress --dbuser=root --dbpass='' --dbhost=127.0.0.1:13306 --extra-php <<'PHP'
define('WP_ENVIRONMENT_TYPE', 'local');
PHP
"$RUNTIME/wpcli" core install --path="$RUNTIME/wp" --url=https://localhost:18443 --title='Isolated Acceptance' --admin_user=acceptance --admin_password=fixture-only-password --admin_email=acceptance@example.test --skip-email
"$RUNTIME/wpcli" user application-password create acceptance 'Disposable CI acceptance' --path="$RUNTIME/wp" --porcelain > "$RUNTIME/wp-app-password.txt"
chmod 600 "$RUNTIME/wp-app-password.txt"
"$RUNTIME/wpcli" rewrite structure '/%postname%/' --path="$RUNTIME/wp" --hard
