import {readFileSync,writeFileSync} from 'node:fs';
const source = readFileSync(new URL('../../caldav_assistant_thunderbird/src/core.ts',import.meta.url),'utf8');
writeFileSync(new URL('../src/generated-core.ts',import.meta.url),source.replace('namespace AssistantActionPlan {','export namespace AssistantActionPlan {'));
