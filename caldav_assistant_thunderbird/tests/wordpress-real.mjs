// Actual WordPress HTTP + actual WP-CLI process. No fake transport responses.
import {createWordPress} from '../addon/wordpress.mjs';
import {createServices} from '../addon/services.mjs';
import {createStore} from '../addon/store.mjs';
import {execFile} from 'node:child_process';import {promisify} from 'node:util';
import assert from 'node:assert/strict';
const run=promisify(execFile),cli=process.env.WP_EXECUTABLE,path=process.env.WP_PATH;
const password=process.env.WP_TEST_PASSWORD,url=process.env.WP_TEST_URL;
let cliCalls=0;
// Same PHP domain operations; native Subprocess adapter is separately exercised inside Thunderbird.
const wpcli=async(op,payload)=>{
 cliCalls++;
 if(op==='test')return JSON.parse((await run(cli,[`--path=${path}`,'eval',"echo wp_json_encode(['transport'=>'wp-cli','site'=>get_bloginfo('name')]);"])).stdout);
 assert.equal(op,'createLog');
 const content=Buffer.from(JSON.stringify(payload)).toString('base64');
 const php=`$p=json_decode(base64_decode('${content}'),true);$slug='caldav-session-'.$p['id'];$old=get_posts(['name'=>$slug,'post_status'=>'any','numberposts'=>1]);$id=$old?$old[0]->ID:wp_insert_post(['post_title'=>$p['title'],'post_content'=>wp_json_encode($p['session']),'post_status'=>'draft','post_name'=>$slug]);echo wp_json_encode(['id'=>$id]);`;
 return JSON.parse((await run(cli,[`--path=${path}`,'eval',php])).stdout);
};
const wp=createWordPress(fetch,wpcli),data={};const store=createStore({get:async k=>({[k]:structuredClone(data[k])}),set:async o=>Object.assign(data,structuredClone(o)),remove:async k=>{delete data[k];}});
const config={enabled:true,mode:'auto',restConfigured:true,wpCliConfigured:true,url,username:'testadmin',password,wpPath:path,wpExecutable:cli};
await store.saveSettings({wordpress:config});
const services=createServices({tasks:{list:async()=>[]},store,wordpress:wp,clock:()=>new Date().toISOString(),identity:()=>crypto.randomUUID()});
const profile=await services.wordpressTest();assert.equal(profile.id,1);assert.equal(cliCalls,0);
const full=await services.wordpressFullTest();assert.equal(full.checks.length,6);
const id=crypto.randomUUID();await services.writeRecord({id,title:'真实记录测试',content:'正文\n中文与换行'});assert.equal((await store.outbox()).length,0);
// Real 401 response from wrong Application Password. Auto reaches real CLI.
await store.saveSettings({wordpress:{...config,password:'wrong-password'}});const fallback=await services.wordpressTest();assert.equal(fallback.transport,'wp-cli');assert.equal(cliCalls,1);
await store.saveSettings({wordpress:{...config,password:'wrong-password',mode:'rest'}});await assert.rejects(services.wordpressTest(),/401/);assert.equal(cliCalls,1);
let subscriber;
try{subscriber=(await run(cli,[`--path=${path}`,'user','get','limited','--field=ID'])).stdout.trim();}
catch{subscriber=(await run(cli,[`--path=${path}`,'user','create','limited','limited@example.invalid','--role=subscriber','--user_pass=Acceptance-limited-only','--porcelain'])).stdout.trim();}
const limitedPassword=(await run(cli,[`--path=${path}`,'user','application-password','create',subscriber,'Acceptance limited','--porcelain'])).stdout.trim();
const limited={...config,username:'limited',password:limitedPassword};
await store.saveSettings({wordpress:limited});await services.writeRecord({title:'403 自动回退测试',content:'实际权限不足'});assert.equal(cliCalls,2,JSON.stringify(await store.outbox()));assert.equal((await store.outbox()).length,0);
await store.saveSettings({wordpress:{...limited,mode:'rest'}});await services.writeRecord({title:'403 严格模式测试',content:'留在 Outbox'});assert.equal(cliCalls,2);assert.match((await store.outbox())[0].error,/403/);
await store.saveSettings({wordpress:config});await services.retryOutbox();assert.equal((await store.outbox()).length,0);
// Actual unavailable URL and unavailable CLI: durable Outbox, later actual REST retry.
await store.saveSettings({wordpress:{...config,url:'http://127.0.0.1:19999',wpCliConfigured:false}});
await services.writeRecord({title:'离线记录测试',content:'不丢失'});assert.equal((await store.outbox()).length,1);
await store.saveSettings({wordpress:config});await services.retryOutbox();assert.equal((await store.outbox()).length,0);
// Stable session slug deduplicates delivery after an uncertain response.
const duplicate={id,title:'去重测试',session:{start:'2026-10-03T09:00:00Z',end:'2026-10-03T09:10:00Z',result:'stop'}};
const one=await wp.rest('createLog',duplicate,config),two=await wp.rest('createLog',duplicate,config);assert.equal(one.id,two.id);
const posts=JSON.parse((await run(cli,[`--path=${path}`,'post','list','--post_status=any','--format=json'])).stdout);
for(const p of posts)if(p.post_title.includes('测试')||p.post_name===`caldav-session-${id}`)await run(cli,[`--path=${path}`,'post','delete',String(p.ID),'--force']);
console.log(JSON.stringify({wordpress:'actual local WordPress with SQLite integration',checks:['REST authenticated Quick Test','REST draft/media full CRUD cleanup','Auto real REST 401 → real WP-CLI','explicit REST 401 no CLI fallback','Auto real subscriber REST 403 → real WP-CLI','explicit REST 403 persists Outbox without CLI fallback','network failure durable Outbox','real REST retry','session retry deduplication'],passed:true}));
