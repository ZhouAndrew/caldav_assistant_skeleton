// Pure page functions: descriptors contain no DOM, storage, clock or API calls.
const e=(tag,text=null,attrs={},children=[])=>({tag,text,attrs,children});
const action=(text,name)=>e('button',text,{'data-action':name});
export function taskPage(model) {return [e('h1',model.title),e('p',`${model.status ?? '无状态'} · ${model.elapsedSeconds} 秒`),e('pre',model.description),...(model.error?[e('p',model.error)]:[]),...model.actions.map(intent=>action({start:'开始',stop:'停止',complete:'完成',cancel:'取消'}[intent],intent))];}
export function pickerPage(settings,tasks) {return [e('h1','选择任务'),e('input',null,{name:'search',placeholder:'搜索任务',value:settings.search ?? ''}),e('ul',null,{id:'tasks'},tasks.map(task=>e('li',null,{},[e('a',task.title,{href:`page.html?id=${encodeURIComponent(task.id)}`})])))];}
export function logsPage(records) {return [e('h1','日志'),...records.map(r=>e('pre',JSON.stringify(r,null,2)))];}
export function todayPage(date,records) {return [e('h1',date+' 工作记录'),...records.map(r=>e('section',null,{},[e('h2',r.title),e('p',`${r.start} → ${r.end ?? '进行中'} · ${r.result ?? ''}`)]))];}
export function wordpressPage(outbox) {return [e('h1','WordPress'),action('连接测试','wp-test'),action('完整读写测试（临时草稿及图片）','wp-full-test'),action('重试待发送记录','retry'),...outbox.map(r=>e('section',null,{},[e('h2',r.title),e('p',r.error ?? '待发送'),e('pre',r.content ?? JSON.stringify(r.session))]))];}
const field=(label,name,value,type='text')=>e('label',label,{},[e('input',null,{name,value:value ?? '',type})]);
export function settingsPage(settings) {
 const wp=settings.wordpress ?? {};
 return [e('h1','设置'),field('日历 ID（留空显示全部）','calendarId',settings.calendarId),e('h2','WordPress'),e('label','启用 WordPress',{},[e('input',null,{name:'wpEnabled',type:'checkbox',checked:Boolean(wp.enabled)})]),e('label','自动保存工作记录',{},[e('input',null,{name:'wpAutoLog',type:'checkbox',checked:wp.autoLogEnabled!==false})]),e('label','连接方式',{},[e('select',null,{name:'wpMode',value:wp.mode ?? 'auto'},['auto','rest','wp-cli'].map(value=>e('option',{auto:'自动',rest:'Application Password','wp-cli':'WP-CLI'}[value],{value})))]),field('网址','wpUrl',wp.url,'url'),field('用户名','wpUsername',wp.username),field('Application Password','wpPassword',wp.password,'password'),field('WordPress 本地目录','wpPath',wp.wpPath),field('WP-CLI 可执行文件（留空自动查找）','wpExecutable',wp.wpExecutable),action('保存','save-settings'),action('核验并恢复当前任务','recover')];
}
export function recordPage() {return [e('h1','写记录'),e('input',null,{name:'title',placeholder:'标题'}),e('textarea',null,{name:'content',placeholder:'记录内容'}),action('保存草稿','record')];}
