import type {LearningItem} from './learning';

export type Positioned={node:LearningItem;x:number;y:number;height:number};
export function revealPath(items:LearningItem[],id:string,collapsed:Set<string>) {
  const next=new Set(collapsed),byId=new Map(items.map(item=>[item.id,item]));let current=byId.get(id);
  while(current?.parent_id){next.delete(current.parent_id);current=byId.get(current.parent_id);}
  return next;
}
export function layoutMindmap(all:LearningItem[],collapsed=new Set<string>()) {
  const children=new Map<string,LearningItem[]>();
  all.forEach(node=>{if(node.parent_id)children.set(node.parent_id,[...(children.get(node.parent_id)||[]),node]);});
  const nodes:Positioned[]=[],heights=new Map<string,number>();
  const height=(node:LearningItem)=>Math.max(44,Math.ceil(Array.from(node.title||'').length/12)*24+16);
  function measure(node:LearningItem):number {
    const kids=collapsed.has(node.id)?[]:children.get(node.id)||[];
    const h=Math.max(height(node),kids.reduce((sum,kid)=>sum+measure(kid),0)+Math.max(0,kids.length-1)*16);
    heights.set(node.id,h);return h;
  }
  function place(node:LearningItem,depth:number,top:number) {
    const h=heights.get(node.id)||76;nodes.push({node,x:20+depth*292,y:top+h/2-height(node)/2,height:height(node)});
    let offset=top;
    if(!collapsed.has(node.id))for(const child of children.get(node.id)||[]){place(child,depth+1,offset);offset+=(heights.get(child.id)||44)+16;}
  }
  const root=all.find(node=>!node.parent_id);
  if(root){measure(root);place(root,0,20);}
  return {nodes,children,width:Math.max(280,...nodes.map(n=>n.x+240)),height:Math.max(180,...nodes.map(n=>n.y+n.height+20))};
}

const escape=(value:string)=>value.replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[char]!));
export function mindmapSvg(items:LearningItem[],title:string,colors:{paper:string;ink:string;line:string;accent:string}) {
  const layout=layoutMindmap(items),byId=new Map(layout.nodes.map(n=>[n.node.id,n]));
  const paths=layout.nodes.map(n=>{
    const p=byId.get(n.node.parent_id||'');
    return p?`<path d="M${p.x+220} ${p.y+p.height/2} C${p.x+255} ${p.y+p.height/2},${n.x-35} ${n.y+n.height/2},${n.x} ${n.y+n.height/2}" fill="none" stroke="${escape(colors.line)}" stroke-width="2"/>`:'';
  }).join('');
  const nodes=layout.nodes.map(n=>{
    const chars=Array.from(n.node.title||''),lines=[];
    for(let i=0;i<chars.length;i+=12)lines.push(chars.slice(i,i+12).join(''));
    const text=lines.map((line,i)=>`<tspan x="${n.x+12}" y="${n.y+26+i*24}">${escape(line)}</tspan>`).join('');
    return `<g><title>${escape(n.node.title||'')}</title><rect x="${n.x}" y="${n.y}" width="220" height="${n.height-2}" rx="4" fill="${escape(colors.paper)}" stroke="${escape(colors.accent)}"/><text fill="${escape(colors.ink)}" font-size="16" font-family="Noto Serif CJK SC, Noto Serif SC, SimSun, serif">${text}</text></g>`;
  }).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${layout.width}" height="${layout.height}" viewBox="0 0 ${layout.width} ${layout.height}" role="img"><title>${escape(title)}</title><rect width="100%" height="100%" fill="${escape(colors.paper)}"/>${paths}${nodes}</svg>`;
}
