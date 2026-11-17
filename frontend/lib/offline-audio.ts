type SavedAudio={key:string;owner:string;salt:Uint8Array<ArrayBuffer>;iv:Uint8Array<ArrayBuffer>;data:ArrayBuffer;bytes:number;createdAt:number};
function database(){return new Promise<IDBDatabase>((resolve,reject)=>{const r=indexedDB.open('narcissus-offline-audio',1);r.onupgradeneeded=()=>{const s=r.result.createObjectStore('audio',{keyPath:'key'});s.createIndex('owner','owner');};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
async function transaction<T>(mode:IDBTransactionMode,work:(store:IDBObjectStore)=>IDBRequest<T>){const db=await database();try{return await new Promise<T>((resolve,reject)=>{const tx=db.transaction('audio',mode),r=work(tx.objectStore('audio'));tx.oncomplete=()=>resolve(r.result);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||new Error('离线存储中断'));});}finally{db.close();}}
async function key(pin:string,salt:Uint8Array<ArrayBuffer>){if(pin.length<8)throw new Error('离线口令至少8个字符');const material=await crypto.subtle.importKey('raw',new TextEncoder().encode(pin),'PBKDF2',false,['deriveKey']);return crypto.subtle.deriveKey({name:'PBKDF2',salt,iterations:150000,hash:'SHA-256'},material,{name:'AES-GCM',length:256},false,['encrypt','decrypt']);}
export function offlineList(owner:string){return transaction<SavedAudio[]>('readonly',s=>s.index('owner').getAll(owner));}
export async function saveOfflineAudio(owner:string,id:string,title:string,blob:Blob,pin:string){
 if(blob.size>80*1024*1024)throw new Error('音频超过80MB，请直接下载原音频');
 const existing=await offlineList(owner),identity=JSON.stringify([owner,id]);
 if(existing.filter(r=>r.key!==identity).reduce((n,r)=>n+r.bytes,0)+blob.size>250*1024*1024)throw new Error('离线空间已达250MB，请先移除旧音频');
 const meta=new TextEncoder().encode(JSON.stringify({title:title.slice(0,240),type:blob.type||'audio/wav'})),audio=new Uint8Array(await blob.arrayBuffer()),payload=new Uint8Array(4+meta.length+audio.length);new DataView(payload.buffer).setUint32(0,meta.length);payload.set(meta,4);payload.set(audio,4+meta.length);
 const salt=crypto.getRandomValues(new Uint8Array(16)),iv=crypto.getRandomValues(new Uint8Array(12)),data=await crypto.subtle.encrypt({name:'AES-GCM',iv},await key(pin,salt),payload);
 await transaction('readwrite',s=>s.put({key:identity,owner,salt,iv,data,bytes:blob.size,createdAt:Date.now()}));
}
export async function unlockAudio(row:SavedAudio,pin:string){
 try{const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:row.iv},await key(pin,row.salt),row.data),size=new DataView(plain).getUint32(0);if(size>4096)throw new Error();const meta=JSON.parse(new TextDecoder().decode(new Uint8Array(plain,4,size)));return {title:String(meta.title),blob:new Blob([plain.slice(4+size)],{type:meta.type})};}catch{throw new Error('口令不正确，或离线文件已损坏');}
}
export function removeOfflineAudio(key:string){return transaction('readwrite',s=>s.delete(key));}
