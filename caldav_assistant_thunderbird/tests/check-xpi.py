"""Contract test of the exact deliverable, independent of source-directory loading."""
import json, re, sys, zipfile
from pathlib import Path
with zipfile.ZipFile(sys.argv[1]) as z:
    assert z.testzip() is None
    names=set(z.namelist())
    required={'manifest.json','background.js','workspace.html','workspace.js','workspace.css','core/storage.js','core/action-plan.js','core/executor.js','api/TaskFix/schema.json','api/TaskFix/implementation.js','api/ThunderbirdCalDAV/schema.json','api/ThunderbirdCalDAV/implementation.js'}
    assert required <= names, required-names
    assert not any(re.search(r'task-picker|legacy-runtime|fixture|node_modules|\.typed-build|(^|/)tests/',n) for n in names)
    manifest=json.loads(z.read('manifest.json'))
    assert manifest['version']==json.loads(Path('package.json').read_text())['version']
    assert manifest['browser_specific_settings']['gecko']['strict_min_version']=='153.0.2'
    assert manifest['browser_specific_settings']['gecko']['strict_max_version']=='153.1.*'
    assert 'nativeMessaging' not in manifest['permissions']
    assert manifest['background']['scripts'].index('core/action-plan.js') < manifest['background']['scripts'].index('core/executor.js')
    core=z.read('core/action-plan.js').decode()
    assert core==Path('addon/core/action-plan.js').read_text()
    for forbidden in ('browser.', 'document.', 'Date.now(', 'new Date(', 'randomUUID(', 'fetch(', 'require('):
        assert forbidden not in core, forbidden
    js='\n'.join(z.read(n).decode() for n in names if n.endswith('.js'))
    for forbidden in ('KEY_RUNTIME','getLegacyRuntime','setRuntime','clearRuntime','caldavAssistant.runtime','task-picker'):
        assert forbidden not in js, forbidden
    executor=z.read('core/executor.js').decode()
    for call in ('planWorkAction','AssistantActionPlan.compare','getTask','updateTask','getSelectedTasks','setCurrentWorkId','persistResult'):
        assert call in executor, call
    assert 'createEvent' not in executor
    workspace=z.read('workspace.js').decode()
    assert 'assistant-work-action' in workspace
    assert 'state.current' not in workspace and 'taskByRef' not in workspace
    for action in ('stop','complete','cancel'): assert action in workspace
    assert 'start-button' not in z.read('workspace.html').decode()
    toolbar=z.read('content/native-start.js').decode()
    background=z.read('background.js').decode()
    assert 'task-actions-toolbar' in toolbar and 'task-actions-markcompleted' in toolbar
    assert 'deriveStartAvailability' in background and 'AssistantExecutor.start(null,selection)' in background
    assert 'updateTask' not in toolbar and 'planWorkAction' not in toolbar
    for n in names:
        if n.endswith('.html'):
            html=z.read(n).decode()
            for src in re.findall(r'<script[^>]*src="([^"?]+)',html): assert src in names,(n,src)
print('XPI frozen contract: PASS')
