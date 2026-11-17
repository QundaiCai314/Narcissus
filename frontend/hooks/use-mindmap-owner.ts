"use client";
import {useEffect,useState} from 'react';
import {api} from '@/lib/api';

// No email fallback or cross-mount identity cache: a new login gets its own key.
export function useMindmapOwner(enabled:boolean){
  const [owner,setOwner]=useState<{id:string|null;checked:boolean}>({id:null,checked:false});
  useEffect(()=>{
    if(!enabled)return;
    let disposed=false,sequence=0;
    async function check(){
      const request=++sequence;
      try{
        const value=await api<{id:string}>('/auth/me');
        if(!disposed&&request===sequence)setOwner({id:typeof value.id==='string'&&value.id?value.id:null,checked:true});
      }catch{if(!disposed&&request===sequence)setOwner({id:null,checked:true});}
    }
    void check();window.addEventListener('focus',check);
    return()=>{disposed=true;window.removeEventListener('focus',check);};
  },[enabled]);
  return enabled?owner:{id:null,checked:true};
}
