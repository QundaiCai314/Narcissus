import type {LearningItem} from './learning';
import {revealPath} from './mindmap-layout';

export type Camera={x:number;y:number;z:number};
export type ViewportSize={width:number;height:number};
export type NodeRect={x:number;y:number;height:number};
export type ReadingPosition={schema:1;signature:string;selected:string;collapsed:string[];camera:Camera;viewport:ViewportSize;savedAt:number};
const finite=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value);
export function progressKey(user:string|undefined,notebook:string|undefined,set:string,version:number){
  if(!user||!notebook||set==='directory-preview'||!Number.isInteger(version)||version<1)return null;
  return 'narcissus.mindmap-reading.v1:'+JSON.stringify([user,notebook,set,version]);
}
export function graphSignature(items:LearningItem[]){
  const content=JSON.stringify(items.map(item=>[item.id,item.parent_id??null,item.title??'',item.directory?.kind??'']));
  let hash=2166136261;for(let i=0;i<content.length;i++){hash^=content.charCodeAt(i);hash=Math.imul(hash,16777619);}
  return `${items.length}:${(hash>>>0).toString(16)}`;
}
export function readPosition(raw:string|null,signature:string,items:LearningItem[],now=Date.now()):ReadingPosition|null{
  if(!raw||raw.length>200000)return null;
  try{
    const data=JSON.parse(raw),ids=new Set(items.map(item=>item.id));
    if(data.schema!==1||data.signature!==signature||!ids.has(data.selected)||!Array.isArray(data.collapsed)||data.collapsed.length>items.length)return null;
    if(!finite(data.savedAt)||now-data.savedAt>30*86400000||data.savedAt>now+300000)return null;
    const c=data.camera,s=data.viewport;
    if(!c||![c.x,c.y,c.z].every(finite)||Math.abs(c.x)>1e7||Math.abs(c.y)>1e7||c.z<.12||c.z>2.5)return null;
    if(!s||![s.width,s.height].every(finite)||s.width<1||s.height<1||s.width>100000||s.height>100000)return null;
    if(!data.collapsed.every((id:unknown)=>typeof id==='string'))return null;
    const parents=new Set(items.map(item=>item.parent_id));
    const collapsed=revealPath(items,data.selected,new Set<string>(data.collapsed.filter((id:string)=>ids.has(id)&&parents.has(id))));
    return {...data,collapsed:[...collapsed]};
  }catch{return null;}
}
export function fitCamera(width:number,height:number,size:ViewportSize):Camera{
  const z=Math.max(.12,Math.min(1.2,(size.width-24)/width,(size.height-30)/height));
  return {x:(size.width-width*z)/2,y:(size.height-height*z)/2,z};
}
export function resizeCamera(camera:Camera,before:ViewportSize,after:ViewportSize,target?:NodeRect):Camera{
  if(before.width===after.width&&before.height===after.height)return camera;
  let z=camera.z;
  if(target)z=Math.max(.12,Math.min(z,(after.width-24)/220,(after.height-24)/target.height));
  let x=after.width/2-(before.width/2-camera.x)/camera.z*z;
  let y=after.height/2-(before.height/2-camera.y)/camera.z*z;
  if(target&&(x+target.x*z<12||x+(target.x+220)*z>after.width-12||y+target.y*z<12||y+(target.y+target.height)*z>after.height-12)){
    x=after.width/2-(target.x+110)*z;y=after.height/2-(target.y+target.height/2)*z;
  }
  return {x,y,z};
}
