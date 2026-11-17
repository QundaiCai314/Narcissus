export function ocrRisks(text:string){
 const risks:string[]=[];
 if(/[A-Za-z][。．][A-Za-z]/.test(text))risks.push('字母间出现中文句点，可能是下标或乘号误识别。');
 if(/\b8B\b/.test(text))risks.push('出现“8B”，请核对是否为变量、数字或希腊字母；不会自动替换。');
 if(/\ufffd|[\ue000-\uf8ff]/.test(text))risks.push('包含不可辨认或私用区字符。');
 if(/(?:\S+\s{3,}){2,}\S+/.test(text))risks.push('存在多列间距，可能为表格；请核对行列对应。');
 return risks;
}
export function tableMarkdown(text:string){
 const rows=text.replace(/\r/g,'').trim().split('\n').map(line=>line.split('\t').map(cell=>cell.trim().replace(/\|/g,'\\|')));
 if(!text.trim()||rows.length>100||Math.max(...rows.map(r=>r.length))>20)throw new Error('表格最多100行、20列；使用Tab分列、换行分行。');
 const width=Math.max(...rows.map(r=>r.length));const line=(row:string[])=>'| '+Array.from({length:width},(_,i)=>row[i]||'').join(' | ')+' |';
 return [line(rows[0]),line(Array(width).fill('---')),...rows.slice(1).map(line)].join('\n');
}
