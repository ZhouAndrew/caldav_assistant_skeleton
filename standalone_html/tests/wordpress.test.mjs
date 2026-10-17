import {test} from 'node:test';
import assert from 'node:assert/strict';
import {captureBlock,createCaptureOutbox,createWordPress} from '../.build/wordpress.js';
globalThis.btoa ??= value=>Buffer.from(value,'binary').toString('base64');
test('capture block escapes text, filenames and URLs',()=>{
 const html=captureBlock({id:'one',at:'2026-10-08T00:00:00Z',content:'<script>x</script>'},[{url:'https://wp/a?x=1&y=2',type:'image/png',name:'<photo>'}]);
 assert.doesNotMatch(html,/<script>/);assert.match(html,/&lt;script&gt;/);assert.match(html,/x=1&amp;y=2/);assert.match(html,/alt="&lt;photo&gt;"/);
});
test('daily post ambiguity fails closed',async()=>{
 const post={id:1,link:'https://wp/post',title:{rendered:'CalDAV Assistant Work Log 2026-10-08'},content:{raw:''}};
 const client=createWordPress({config:{baseUrl:'https://wp',username:'u',applicationPassword:'p'},fetch:async()=>new Response(JSON.stringify([post,{...post,id:2}]),{status:200,headers:{'Content-Type':'application/json'}})});
 await assert.rejects(client.findDaily(new Date('2026-10-08T04:00:00Z')),{code:'Conflict'});
});
test('append creates, uploads, writes and reads back exact content',async()=>{
 let content='';const calls=[];
 const fetch=async(url,init={})=>{calls.push([String(url),init.method??'GET']);const path=new URL(url).pathname+new URL(url).search;
  if(path.includes('/posts?'))return json([]);
  if(path.endsWith('/posts'))return json({id:9});
  if(path.includes('/media'))return json({id:7,source_url:'https://wp/media/a.png',mime_type:'image/png'});
  if(path.endsWith('/posts/9')&&init.method==='POST'){content=JSON.parse(init.body).content;return json({id:9});}
  if(path.includes('/posts/9?'))return json({id:9,link:'https://wp/p',title:{rendered:'CalDAV Assistant Work Log 2026-10-08'},content:{raw:content}});
  throw Error(path);
 };
 const client=createWordPress({config:{baseUrl:'https://wp',username:'u',applicationPassword:'p'},fetch});
 const receipt=await client.append({id:'capture-1',at:'2026-10-08T04:00:00Z',content:'hello',files:[{name:'a.png',type:'image/png',bytes:new Uint8Array([1]).buffer}]});
 assert.equal(receipt.verified,true);assert.match(receipt.post.content,/capture-1/);assert.equal(calls.filter(item=>item[1]==='POST').length,3);
});
function json(value){return new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});}
test('durable outbox stops on failure and retries without losing order',async()=>{
 const rows=[],store={list:async()=>rows.slice(),put:async value=>{rows.push(value);},delete:async id=>{rows.splice(rows.findIndex(item=>item.id===id),1);}};
 const outbox=createCaptureOutbox(store),sent=[];
 await outbox.enqueue({id:'two',at:'2026-10-08T00:01:00Z',content:'2',files:[]});await outbox.enqueue({id:'one',at:'2026-10-08T00:00:00Z',content:'1',files:[]});
 assert.deepEqual(await outbox.flush({append:async capture=>{sent.push(capture.id);throw Error('offline');}}),{sent:0,pending:2});
 assert.deepEqual(sent,['one']);sent.length=0;
 assert.deepEqual(await outbox.flush({append:async capture=>{sent.push(capture.id);}}),{sent:2,pending:0});assert.deepEqual(sent,['one','two']);
});
