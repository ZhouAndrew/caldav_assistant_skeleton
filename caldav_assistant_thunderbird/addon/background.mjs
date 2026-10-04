import {createServices} from './services.mjs';
import {createStore} from './store.mjs';
import {createWordPress} from './wordpress.mjs';
import {migrateOnce} from './migration.mjs';
const services = createServices({tasks:messenger.assistantNative,store:createStore(messenger.storage.local),wordpress:createWordPress(fetch,messenger.assistantNative.wpCli),clock:()=>new Date(Math.floor(Date.now()/1000)*1000).toISOString(),identity:()=>crypto.randomUUID()});
const initialize=()=>migrateOnce({storage:messenger.storage.local,tasks:messenger.assistantNative}).then(()=>services.recover());
let ready=initialize();
const queries = {task:async id=>{await ready;return services.queryTask(id);},picker:s=>services.queryPicker(s),pickerSettings:()=>services.queryPickerSettings(),today:input=>services.queryToday(input),logs:()=>services.queryLogs(),outbox:()=>services.queryOutbox(),settings:()=>services.querySettings()};
messenger.runtime.onMessage.addListener(async message=>{
  if(message.type==='facts-changed'||message.type==='outbox-changed')return;
  try {
    let value;
    if (message.type === 'query' && queries[message.name]) value = await queries[message.name](message.input);
    else if (message.type === 'action') {await ready;value = await services.command(message.intent,message.taskId);messenger.runtime.sendMessage({type:'facts-changed'}).catch(()=>{});}
    else if (message.type === 'recover') {ready=initialize();value=await ready;messenger.runtime.sendMessage({type:'facts-changed'}).catch(()=>{});}
    else if (message.type === 'settings') value = await services.saveSettings(message.patch);
    else if (message.type === 'retry') value = await services.retryOutbox();
    else if (message.type === 'wp-test') value = await services.wordpressTest();
    else if (message.type === 'wp-full-test') value = await services.wordpressFullTest();
    else if (message.type === 'record') value = await services.writeRecord(message.payload);
    else throw new Error('UNKNOWN_COMMAND');
    return {ok:true,value};
  } catch(error) {return {ok:false,error:error.message};}
});
messenger.spaces.create('caldav_assistant','page.html').catch(error=>console.error(error));
// Startup recovery is explicit, separate from every query/render.
ready.catch(error=>messenger.storage.local.set({'caldavAssistant.recoveryError':error.message}));
const retryBackground=()=>services.retryOutbox().then(()=>messenger.runtime.sendMessage({type:'outbox-changed'})).catch(error=>console.error('WordPress Outbox:',error.message));
ready.then(retryBackground,()=>{});
messenger.alarms.create('wordpress-outbox',{periodInMinutes:5});
messenger.alarms.onAlarm.addListener(alarm=>{if(alarm.name==='wordpress-outbox')retryBackground();});
