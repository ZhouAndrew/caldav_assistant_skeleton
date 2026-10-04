from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib,json
root=Path(__file__).resolve().parents[1]
output=root/'artifacts';output.mkdir(exist_ok=True)
target=output/'CalDAV-Assistant-cleanroom-0.4.0-candidate.xpi'
with ZipFile(target,'w',ZIP_DEFLATED) as archive:
    for file in sorted((root/'addon').rglob('*')):
        if file.is_file():archive.write(file,file.relative_to(root/'addon'))
with ZipFile(target) as archive:
    names=archive.namelist()
    forbidden=['legacy-runtime','restore-snapshot','work-timing','TaskFix','executor.js']
    assert not any(word in name for word in forbidden for name in names)
    for name in names:
        content=archive.read(name).decode()
        assert not any(word in content for word in ['X-CALDAV-ASSISTANT-WORK-SESSION','switchAway','pauseTask','resumeTask'])
        if name!='migration.mjs':assert 'caldavAssistant.runtime' not in content
print(json.dumps({'file':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'files':len(names)}))
