"use client";
import {useState} from 'react';
import {api,request,errorText} from '@/lib/api';
import {saveOfflineAudio} from '@/lib/offline-audio';
export function OfflineAudioSave({id,title}:{id:string;title:string}){
 const [pin,setPin]=useState(''),[busy,setBusy]=useState(false),[status,setStatus]=useState(''),[owner,setOwner]=useState('');
 async function save(){setBusy(true);setStatus('');try{const user=await api<{id:string}>('/auth/me');if(!user.id)throw new Error('无法确认当前账号');const blob=await (await request(`/audio-renders/${id}/file`)).blob();await saveOfflineAudio(user.id,id,title,blob,pin);setOwner(user.id);try{localStorage.setItem('narcissus.offline-owner',user.id);}catch{}setPin('');setStatus('离线音频已加密保存在此浏览器。忘记口令需移除后重新保存。');}catch(e){setStatus(errorText(e));}finally{setBusy(false);}}
 return <details className="directory-coverage"><summary>保存到离线音频库</summary><p className="muted">仅保存在当前浏览器，需设置口令解锁；离线库不保存登录凭据。不会重新合成音频。</p><label>离线口令<input aria-label="设置离线口令" type="password" minLength={8} maxLength={100} autoComplete="new-password" value={pin} onChange={e=>setPin(e.target.value)}/></label><button className="button" disabled={busy||pin.length<8} onClick={()=>void save()}>{busy?'正在加密保存…':'加密保存此音频'}</button>{status&&<p role="status">{status}</p>}<a className="text-button" href={owner?`/offline?owner=${encodeURIComponent(owner)}`:'/offline'}>打开离线音频库</a></details>;
}
