"""Provision disposable official Thunderbird/WordPress dependencies for CI.
Uses system PHP with sqlite3/pdo_sqlite, not any user WordPress installation.
"""
from pathlib import Path
from urllib.request import urlretrieve
import tempfile,zipfile,tarfile,subprocess,json,shutil
root=Path(tempfile.mkdtemp(prefix='assistant-fixtures-'))
def download(url,name):
 path=root/name;urlretrieve(url,path);return path
tb=download('https://archive.mozilla.org/pub/thunderbird/releases/153.1.0esr/linux-x86_64/en-US/thunderbird-153.1.0esr.tar.xz','thunderbird.tar.xz')
with tarfile.open(tb) as archive:archive.extractall(root,filter='data')
wp=download('https://wordpress.org/wordpress-7.1.2.zip','wordpress.zip')
with zipfile.ZipFile(wp) as archive:archive.extractall(root)
plugin=download('https://downloads.wordpress.org/plugin/sqlite-database-integration.latest-stable.zip','sqlite.zip')
with zipfile.ZipFile(plugin) as archive:archive.extractall(root/'wordpress/wp-content/plugins')
shutil.copy(root/'wordpress/wp-content/plugins/sqlite-database-integration/db.copy',root/'wordpress/wp-content/db.php')
phar=download('https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar','wp-cli.phar')
cli=root/'wp';cli.write_text(f'#!/bin/sh\nexec php "{phar}" --allow-root "$@"\n');cli.chmod(0o755)
subprocess.run([str(cli),'--path='+str(root/'wordpress'),'config','create','--dbname=acceptance','--dbuser=test','--skip-check'],check=True)
subprocess.run([str(cli),'--path='+str(root/'wordpress'),'config','set','WP_ENVIRONMENT_TYPE','local'],check=True)
subprocess.run([str(cli),'--path='+str(root/'wordpress'),'core','install','--url=http://127.0.0.1:18080','--title=Acceptance','--admin_user=testadmin','--admin_password=Acceptance-only-local-123','--admin_email=test@example.invalid','--skip-email'],check=True)
router=root/'router.php';router.write_text("<?php $path=parse_url($_SERVER['REQUEST_URI'],PHP_URL_PATH);if(str_starts_with($path,'/wp-json/')){$_GET['rest_route']=substr($path,8);require __DIR__.'/wordpress/index.php';}elseif(is_file(__DIR__.'/wordpress'.$path)){return false;}else{require __DIR__.'/wordpress/index.php';}")
env={'THUNDERBIRD_BINARY':str(root/'thunderbird/thunderbird'),'WP_EXECUTABLE':str(cli),'WP_PATH':str(root/'wordpress'),'PHP_EXECUTABLE':shutil.which('php'),'PHP_INI':subprocess.check_output(['php','-r','echo php_ini_loaded_file();'],text=True),'WP_ROUTER':str(router)}
target=Path(__file__).resolve().parents[1]/'artifacts/fixture-env.json';target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(env,indent=2)+'\n')
print('Disposable fixture environment:',target)
