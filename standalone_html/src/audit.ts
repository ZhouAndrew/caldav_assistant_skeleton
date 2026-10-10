export type AuditScope = 'workflow'|'connection'|'wordpress'|'system';
export interface AuditRecord {
  readonly id:string; readonly timestamp:string; readonly localDate:string;
  readonly scope:AuditScope; readonly action:string; readonly success:boolean;
  readonly summary:string; readonly details?:unknown;
}
export interface AuditStore {
  list():Promise<readonly AuditRecord[]>;
  put(record:AuditRecord):Promise<void>;
  clear(localDate?:string):Promise<void>;
}

export function localDateKey(value:Date|string=new Date()) {
  const date=value instanceof Date?value:new Date(value);
  if(!Number.isFinite(date.getTime())) return '';
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);
  const part=(name:string)=>parts.find(item=>item.type===name)?.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}

export function filterAudit(records:readonly AuditRecord[],options:{scope?:string;date?:string;search?:string}) {
  const search=(options.search??'').trim().toLowerCase();
  return Object.freeze(records.filter(record=>(!options.scope||record.scope===options.scope)&&
    (!options.date||record.localDate===options.date)&&(!search||JSON.stringify(record).toLowerCase().includes(search))));
}

export function readableAudit(records:readonly AuditRecord[]) {
  return records.map(record=>`${record.timestamp}  ${record.scope}  ${record.success?'✓':'✗'}  ${record.summary}`).join('\n');
}

export function memoryAuditStore():AuditStore {
  const records=new Map<string,AuditRecord>();
  return Object.freeze({
    list:async()=>Object.freeze([...records.values()].sort((a,b)=>a.timestamp.localeCompare(b.timestamp))),
    put:async (record:AuditRecord)=>{records.set(record.id,record);},
    clear:async (date?:string)=>{for(const [id,record] of records) if(!date||record.localDate===date) records.delete(id);},
  });
}

export function openAuditStore():Promise<AuditStore> {
  return new Promise((resolve,reject)=>{
    const request=indexedDB.open('caldav-assistant-standalone',2);
    request.onupgradeneeded=()=>{
      if(!request.result.objectStoreNames.contains('audit')) request.result.createObjectStore('audit',{keyPath:'id'});
      if(!request.result.objectStoreNames.contains('wordpress-captures')) request.result.createObjectStore('wordpress-captures',{keyPath:'id'});
    };
    request.onerror=()=>reject(new Error('Audit storage unavailable'));
    request.onsuccess=()=>{
      const db=request.result;
      function operation<T>(mode:IDBTransactionMode,run:(store:IDBObjectStore)=>IDBRequest<T>) {
        return new Promise<T>((ok,fail)=>{const result=run(db.transaction('audit',mode).objectStore('audit'));result.onsuccess=()=>ok(result.result);result.onerror=()=>fail(new Error('Audit storage unavailable'));});
      }
      resolve(Object.freeze({
        list:async()=>Object.freeze((await operation<AuditRecord[]>('readonly',store=>store.getAll())).sort((a,b)=>a.timestamp.localeCompare(b.timestamp))),
        put:async (record:AuditRecord)=>{await operation('readwrite',store=>store.put(record));},
        clear:async (date?:string)=>{if(!date){await operation('readwrite',store=>store.clear());return;}for(const record of await operation<AuditRecord[]>('readonly',store=>store.getAll())) if(record.localDate===date) await operation('readwrite',store=>store.delete(record.id));},
      }));
    };
  });
}
