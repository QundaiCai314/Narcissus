"use client";
import {useRef,useState} from 'react';
import {FormulaPicker} from './formula-picker';
import {MarkdownRenderer} from './markdown-renderer';
import {ocrRisks,tableMarkdown} from '@/lib/ocr-risks';
export function SourceCorrection({label,value,onChange}:{label:string;value:string;onChange:(text:string)=>void}){
 const [formula,setFormula]=useState(false),[table,setTable]=useState(''),[error,setError]=useState(''),[preview,setPreview]=useState(false),[formulaDirty,setFormulaDirty]=useState(false);
 const area=useRef<HTMLTextAreaElement>(null);
 function insert(text:string){const start=area.current?.selectionStart??value.length,end=area.current?.selectionEnd??value.length;onChange(value.slice(0,start)+text+value.slice(end));}
 return <div className="source-correction"><div className="learning-toolbar"><button className="text-button" onClick={()=>setFormula(true)}>公式结构选板</button><button className="text-button" onClick={()=>setPreview(v=>!v)}>{preview?'继续修正':'预览公式与表格'}</button></div>{ocrRisks(value).map(t=><p className="source-warning" key={t}>{t}</p>)}<textarea ref={area} aria-label={label} rows={8} value={value} onChange={e=>onChange(e.target.value)}/>{formula&&<FormulaPicker initial="" initialDisplay editing={false} onInsert={(latex,display)=>{insert(display?'\n$$'+latex+'$$\n':'$'+latex+'$');setFormula(false);setFormulaDirty(false);return true;}} onClose={()=>{if(!formulaDirty||confirm('公式尚未插入，确定关闭？')){setFormula(false);setFormulaDirty(false);}}} onDirty={setFormulaDirty}/>}<details><summary>按原件修正表格</summary><p className="muted">从表格复制文字，Tab分列、换行分行；第一行为列标题。插入前请核对原件。</p><textarea aria-label="表格校对内容" rows={4} value={table} onChange={e=>setTable(e.target.value)}/><button className="text-button" onClick={()=>{try{insert('\n'+tableMarkdown(table)+'\n');setError('');setTable('');}catch(e){setError((e as Error).message);}}}>插入核对后的表格</button>{error&&<p role="alert">{error}</p>}</details>{preview&&<MarkdownRenderer content={value}/>}<p className="muted">人工修正会保存为新来源版本，不自动认定公式或表格已正确。</p></div>;
}
