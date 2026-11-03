const fs=require('fs');
const pptxgen=require('pptxgenjs');
const scenes=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const pptx=new pptxgen();
pptx.defineLayout({name:'NARCISSUS',width:scenes[0].width/96,height:scenes[0].height/96});pptx.layout='NARCISSUS';
pptx.author='Narcissus';pptx.subject='原始资料引用见每页讲解备注';pptx.title=scenes[0].title;
pptx.theme={headFontFace:'Noto Sans CJK SC',bodyFontFace:'Noto Sans CJK SC',lang:'zh-CN'};
for(const scene of scenes){
 const slide=pptx.addSlide();
 for(const n of scene.nodes){
  const box={x:n.x/96,y:n.y/96,w:n.w/96,h:n.h/96};
  if(n.type==='rect')slide.addShape(pptx.ShapeType.rect,{...box,fill:{color:n.color},line:{color:n.color,transparency:100}});
  else if(n.type==='text')slide.addText(n.text,{...box,fontFace:'Noto Sans CJK SC',fontSize:n.size*.75,color:n.color,bold:false,margin:0,breakLine:false,vertAnchor:'top',valign:'top',wrap:false,paraSpaceAfterPt:0,transparency:0});
  else slide.addChart(pptx.ChartType.bar,[{name:n.data[0].operation==='ratio_percent'?'%':n.data[0].unit,labels:[...n.data].reverse().map(d=>`${d.label}（${d.operation==='ratio_percent'?'%':d.unit}） ${d.period} [${d.refs.join('][')}]`),values:[...n.data].reverse().map(d=>d.value)}],{...box,barDir:'bar',catAxisLabelFontFace:'Noto Sans CJK SC',valAxisLabelFontFace:'Noto Sans CJK SC',dataLabelFormatCode:'0.####',dataLabelPosition:'outEnd',showValue:true,showLegend:false,catAxisLabelFontSize:16,valAxisLabelFontSize:14,dataLabelColor:'26344B',dataLabelBkgrdColor:'FFFFFF',chartColors:[n.color],showBorder:false,showTitle:false});
 }
 slide.addNotes(scene.notes);
}
pptx.writeFile({fileName:process.argv[3]}).catch(()=>process.exit(1));
