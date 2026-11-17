"use client";
import {useEffect,useState} from 'react';
import {Header} from '@/components/shared';
import {api,errorText} from '@/lib/api';
import {offlineList,unlockAudio,removeOfflineAudio} from '@/lib/offline-audio';
type Rows=Awaited<ReturnType<typeof offlineList>>;
export default function Offline(){
 const [rows,setRows]=useState<Rows>([]),[pin,setPin]=useState(''),[error,setError]=useState(''),[source,setSource]=useState(''),[title,setTitle]=useState(''),[owner,setOwner]=useState('');
 useEffect(()=>{let active=true;async function load(){let id=new URLSearchParams(location.search).get('owner')||'';try{const user=await api<{id:string}>('/auth/me');if(user.id)id=user.id;}catch{if(!id)try{id=localStorage.getItem('narcissus.offline-owner')||'';}catch{}}
  if(!id){setError('请先在线打开音频详情，设置口令并保存离线音频。');return;}if(active){setOwner(id);try{const value=await offlineList(id);if(active)setRows(value);}catch(e){if(active)setError(errorText(e));}}}void load();return()=>{active=false;};},[]);
 useEffect(()=>()=>{if(source)URL.revokeObjectURL(source);},[source]);
 return <><Header/><main className="home parity-library"><h1>离线音频库</h1><p>已保存的音频可断网解锁播放。清除浏览器数据或更换设备后需要重新保存。</p><label>离线口令<input aria-label="解锁离线口令" type="password" maxLength={100} value={pin} onChange={e=>setPin(e.target.value)}/></label>{error&&<p role="alert">{error}</p>}{!rows.length&&<p>此账号暂无离线音频。</p>}{rows.map((row,i)=><article className="directory-coverage" key={row.key}><span>音频{i+1} · {(row.bytes/1024/1024).toFixed(1)}MB · {new Date(row.createdAt).toLocaleDateString()}</span><button className="button" disabled={pin.length<8} onClick={async()=>{try{const value=await unlockAudio(row,pin);setSource(URL.createObjectURL(value.blob));setTitle(value.title);setError('');}catch(e){setError(errorText(e));}}}>解锁播放</button><button className="text-button" onClick={async()=>{try{await removeOfflineAudio(row.key);setRows(await offlineList(owner));setSource('');setTitle('');setError('');}catch(e){setError(errorText(e));}}}>移除离线副本</button></article>)}{source&&<section><h2>{title}</h2><audio controls src={source}/><button className="text-button" onClick={()=>{setSource('');setPin('');setTitle('');}}>锁定播放器</button></section>}</main></>;
}
