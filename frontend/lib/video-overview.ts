export async function composeVideo(pdfBytes:ArrayBuffer,audioBytes:ArrayBuffer,audioContext:AudioContext,onProgress:(value:number)=>void,signal:AbortSignal){
 if(typeof MediaRecorder==='undefined'||!HTMLCanvasElement.prototype.captureStream)throw new Error('当前浏览器不支持视频导出，请使用新版Chrome或Edge');
 const mime=['video/webm;codecs=vp9,opus','video/webm;codecs=vp8,opus','video/webm'].find(t=>MediaRecorder.isTypeSupported(t));if(!mime)throw new Error('当前浏览器不支持WebM导出');
 const pdfjs=await import('pdfjs-dist');pdfjs.GlobalWorkerOptions.workerSrc='/pdfjs/pdf.worker.min.mjs';
 const task=pdfjs.getDocument({data:new Uint8Array(pdfBytes),cMapUrl:'/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:'/pdfjs/standard_fonts/',wasmUrl:'/pdfjs/wasm/'});
 let recorder:MediaRecorder|undefined,stream:MediaStream|undefined,source:AudioBufferSourceNode|undefined,encodingError:Error|undefined;
 const check=()=>{if(signal.aborted)throw new Error('视频导出已取消');if(encodingError)throw encodingError;};
 try{
  const pdf=await task.promise,audio=await audioContext.decodeAudioData(audioBytes);
  if(pdf.numPages>30||audio.duration>300||audio.duration<.1)throw new Error('本次视频最多30页、5分钟，请使用较短成果');
  const canvas=document.createElement('canvas');canvas.width=1280;canvas.height=720;const ctx=canvas.getContext('2d');if(!ctx)throw new Error('无法创建视频画布');
  async function draw(index:number){check();const page=await pdf.getPage(index),base=page.getViewport({scale:1}),viewport=page.getViewport({scale:Math.min(1280/base.width,720/base.height)}),slide=document.createElement('canvas');slide.width=Math.ceil(viewport.width);slide.height=Math.ceil(viewport.height);await page.render({canvas:slide,viewport}).promise;ctx!.fillStyle='#f7f5ee';ctx!.fillRect(0,0,1280,720);ctx!.drawImage(slide,(1280-slide.width)/2,(720-slide.height)/2);}
  await draw(1);check();stream=canvas.captureStream(12);const destination=audioContext.createMediaStreamDestination();source=audioContext.createBufferSource();source.buffer=audio;source.connect(destination);for(const track of destination.stream.getAudioTracks())stream.addTrack(track);
  const chunks:BlobPart[]=[];recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:1500000,audioBitsPerSecond:96000});
  const done=new Promise<Blob>(resolve=>{recorder!.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};recorder!.onstop=()=>resolve(new Blob(chunks,{type:mime}));recorder!.onerror=()=>{encodingError=new Error('视频编码失败');};});
  recorder.start(500);source.start();const started=audioContext.currentTime,deadline=performance.now()+(audio.duration+30)*1000;
  for(let i=1;i<=pdf.numPages;i++){if(i>1)await draw(i);const until=audio.duration*i/pdf.numPages;while(audioContext.currentTime-started<until){check();if(performance.now()>deadline)throw new Error('录制超时，请保持页面在前台后重试');onProgress(Math.min(99,(audioContext.currentTime-started)/audio.duration*100));await new Promise(resolve=>setTimeout(resolve,80));}}
  check();recorder.stop();const blob=await Promise.race([done,new Promise<never>((_,reject)=>setTimeout(()=>reject(new Error('视频编码未完成，请重试')),10000))]);check();onProgress(100);return blob;
 }finally{try{source?.stop();}catch{}source?.disconnect();if(recorder&&recorder.state!=='inactive')recorder.stop();stream?.getTracks().forEach(t=>t.stop());await task.destroy();await audioContext.close();}
}
