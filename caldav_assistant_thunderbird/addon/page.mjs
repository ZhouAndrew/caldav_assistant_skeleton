import {taskPage,pickerPage,logsPage,todayPage,wordpressPage,settingsPage,recordPage} from './views.mjs';
const app=document.querySelector('#app'),message=document.querySelector('#message'),route=new URLSearchParams(location.search);
let renderRevision=0,settings={},pickerSearch=route.get('search');
const api=async request=>{const result=await messenger.runtime.sendMessage(request);if(!result.ok)throw new Error(result.error);return result.value;};
const query=(name,input)=>api({type:'query',name,input});
function mount(spec) {
 const node=document.createElement(spec.tag);if(spec.text!==null)node.textContent=spec.text;
 for(const child of spec.children)node.append(mount(child));
 for(const [key,value] of Object.entries(spec.attrs)){if(key==='value'||key==='checked')node[key]=value;else node.setAttribute(key,value);}
 return node;
}
async function render() {
 const revision=++renderRevision;let view;
 if(route.has('id'))view=taskPage(await query('task',route.get('id')));
 else switch(route.get('view')) {
  case 'logs':view=logsPage(await query('logs'));break;
  case 'today':{const date=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());view=todayPage(date,await query('today',{date,timeZone:'Asia/Taipei'}));break;}
  case 'wordpress':view=wordpressPage(await query('outbox'));break;
  case 'settings':settings=await query('settings');view=settingsPage(settings);break;
  case 'record':view=recordPage();break;
  default:{const picker=await query('pickerSettings');picker.search=pickerSearch ?? picker.search;view=pickerPage(picker,await query('picker',picker));break;}
 }
 if(revision!==renderRevision)return;
 app.replaceChildren(...view.map(mount));
}
const value=name=>app.querySelector(`[name="${name}"]`).value;
app.addEventListener('click',async event=>{
 const button=event.target.closest('button[data-action]');if(!button || button.disabled)return;
 const action=button.dataset.action;button.disabled=true;message.textContent='';
 try {
  let result;
  if(['start','stop','complete','cancel'].includes(action)) {
   result=await api({type:'action',intent:action,taskId:route.get('id')});await render();
   message.textContent=result.wordpress==='queued'?`任务已保存；WordPress 待重试：${result.logError ?? ''}`:'任务已保存';
  } else if(action==='save-settings') {
   const wp={...settings.wordpress,enabled:app.querySelector('[name=wpEnabled]').checked,autoLogEnabled:app.querySelector('[name=wpAutoLog]').checked,mode:value('wpMode'),url:value('wpUrl'),username:value('wpUsername'),password:value('wpPassword'),wpPath:value('wpPath'),wpExecutable:value('wpExecutable')};
   wp.restConfigured=Boolean(wp.url && wp.username && wp.password);wp.wpCliConfigured=Boolean(wp.wpPath);
   await api({type:'settings',patch:{calendarId:value('calendarId'),wordpress:wp}});message.textContent='已保存';
  } else if(action==='record') {
   await api({type:'record',payload:{title:value('title'),content:value('content')}});message.textContent='记录已保存；发送状态见 WordPress 待发送列表';
  } else {result=await api({type:action});if(action==='retry')await render();message.textContent=JSON.stringify(result ?? {ok:true});}
 } catch(error){message.textContent=error.message;}finally{button.disabled=false;}
});
app.addEventListener('input',async event=>{
 if(event.target.name!=='search')return;
 const revision=++renderRevision;pickerSearch=event.target.value;
 try{const picker=await query('pickerSettings');picker.search=event.target.value;const tasks=await query('picker',picker);if(revision===renderRevision)app.querySelector('#tasks').replaceWith(mount(pickerPage(picker,tasks)[2]));}catch(error){message.textContent=error.message;}
});
const refresh=()=>render().catch(error=>message.textContent=error.message);
messenger.runtime.onMessage.addListener(event=>{if(event.type==='facts-changed' && (route.has('id') || route.get('view')==='today') || event.type==='outbox-changed' && route.get('view')==='wordpress')refresh();});
document.addEventListener('visibilitychange',()=>{if(!document.hidden && !['settings','record'].includes(route.get('view')))refresh();});
refresh();
