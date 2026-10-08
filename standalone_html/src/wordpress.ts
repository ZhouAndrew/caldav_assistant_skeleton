export interface WordPressConfig { readonly baseUrl: string; readonly username: string; readonly applicationPassword: string }
export interface DailyPost { readonly id: number; readonly title: string; readonly link: string; readonly content: string }
export interface CaptureFile { readonly name: string; readonly type: string; readonly bytes: ArrayBuffer }
export interface Capture { readonly id: string; readonly at: string; readonly content: string; readonly files: readonly CaptureFile[] }
export interface CaptureReceipt { readonly post: DailyPost; readonly verified: true }

export class WordPressError extends Error {
  constructor(readonly code: 'Permission'|'Unavailable'|'Validation'|'Conflict') { super(`WordPress ${code}`); }
}
function trimSlash(value: string) { return value.trim().replace(/\/+$/, ''); }
function titleFor(date: Date) {
  const parts = new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);
  const part=(name:string)=>parts.find(item=>item.type===name)?.value;
  return `CalDAV Assistant Work Log ${part('year')}-${part('month')}-${part('day')}`;
}
function escapeHtml(value: string) { return value.replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]!)); }
export function captureBlock(capture: Pick<Capture,'id'|'at'|'content'>, media: readonly {url:string;type:string;name:string}[]) {
  if (!capture.id || !Number.isFinite(Date.parse(capture.at))) throw new WordPressError('Validation');
  const marker=`<!-- caldav-assistant-capture:${escapeHtml(capture.id)} -->`;
  const text=capture.content ? `<pre>${escapeHtml(capture.content)}</pre>` : '';
  const files=media.map(item=>item.type.startsWith('image/')
    ? `<figure><img src="${escapeHtml(item.url)}" alt="${escapeHtml(item.name)}"></figure>`
    : `<p><a href="${escapeHtml(item.url)}">${escapeHtml(item.name)}</a></p>`).join('\n');
  return `${marker}\n<section data-caldav-assistant-capture="${escapeHtml(capture.id)}"><time>${escapeHtml(capture.at)}</time>${text}${files}</section>`;
}
export function createWordPress(options:{config:WordPressConfig;fetch:typeof fetch}) {
  const base=trimSlash(options.config.baseUrl); let origin: string;
  try { const url=new URL(base); if(!['http:','https:'].includes(url.protocol)||url.username||url.password) throw 0; origin=url.origin; }
  catch { throw new WordPressError('Validation'); }
  const bytes=new TextEncoder().encode(`${options.config.username}:${options.config.applicationPassword.replace(/\s+/g,'')}`);
  const authorization='Basic '+btoa(Array.from(bytes,b=>String.fromCharCode(b)).join(''));
  async function request(path:string,init:RequestInit={}) {
    const url=new URL('/wp-json/wp/v2'+path,base);
    if(url.origin!==origin) throw new WordPressError('Validation');
    const headers=new Headers(init.headers);headers.set('Authorization',authorization);
    let response:Response;
    try { response=await options.fetch(url,{...init,headers,redirect:'error',cache:'no-store',credentials:'omit',signal:AbortSignal.timeout(15000)}); }
    catch { throw new WordPressError('Unavailable'); }
    if(!response.ok) throw new WordPressError(response.status===401||response.status===403?'Permission':response.status===409||response.status===412?'Conflict':'Unavailable');
    try { return await response.json() as any; } catch { throw new WordPressError('Validation'); }
  }
  function project(post:any):DailyPost {
    if(!Number.isSafeInteger(post?.id)||typeof post?.link!=='string'||typeof post?.title?.rendered!=='string'||typeof post?.content?.raw!=='string') throw new WordPressError('Validation');
    return Object.freeze({id:post.id,title:post.title.rendered,link:post.link,content:post.content.raw});
  }
  async function findDaily(date=new Date(),create=false) {
    const title=titleFor(date);const rows=await request(`/posts?context=edit&status=publish,draft&search=${encodeURIComponent(title)}&per_page=20`);
    if(!Array.isArray(rows)) throw new WordPressError('Validation');
    const matches=rows.map(project).filter(post=>post.title===title);
    if(matches.length>1) throw new WordPressError('Conflict');
    if(matches[0]) return matches[0];
    if(!create) return null;
    const result=await request('/posts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,status:'publish',content:''})});
    if(!Number.isSafeInteger(result?.id)) throw new WordPressError('Validation');
    const created=project(await request(`/posts/${result.id}?context=edit`));
    if(created.title!==title||created.content!=='') throw new WordPressError('Validation');
    return created;
  }
  async function upload(file:CaptureFile,parent:number) {
    const headers=new Headers({'Content-Type':file.type||'application/octet-stream','Content-Disposition':`attachment; filename="${file.name.replace(/["\r\n]/g,'_')}"`});
    const item=await request(`/media?post=${parent}`,{method:'POST',headers,body:file.bytes});
    if(!Number.isSafeInteger(item?.id)||typeof item?.source_url!=='string') throw new WordPressError('Validation');
    return {url:item.source_url,type:String(item.mime_type||file.type),name:file.name};
  }
  async function append(capture:Capture):Promise<CaptureReceipt> {
    const post=await findDaily(new Date(capture.at),true); if(!post) throw new WordPressError('Validation');
    const marker=`<!-- caldav-assistant-capture:${capture.id} -->`;
    if(post.content.includes(marker)) return {post,verified:true};
    const media=[];for(const file of capture.files) media.push(await upload(file,post.id));
    const expected=post.content+(post.content?'\n\n':'')+captureBlock(capture,media);
    await request(`/posts/${post.id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:expected})});
    const actual=project(await request(`/posts/${post.id}?context=edit`));
    if(actual.content!==expected||!actual.content.includes(marker)) throw new WordPressError('Validation');
    return Object.freeze({post:actual,verified:true});
  }
  return Object.freeze({findDaily,append});
}
