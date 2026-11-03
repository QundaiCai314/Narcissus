import { WritingCitation } from './api';
export type AudioParagraph = { id: string; chapter: string; speaker: 'A' | 'B'; text: string; refs: number[]; edited?: boolean };
export type AudioScript = { title: string; intro: string; intro_edited?: boolean; paragraphs: AudioParagraph[] };
export type AudioRender = {
  id: string; overview_id: string; revision: number; status: string; error: string | null;
  voices: Record<string,string>; model: string; duration_ms: number | null; created_at: string;
  completed_segments: number; total_segments: number; uncertain_segments: number; characters: number;
  snapshot?: {script: AudioScript; citations: WritingCitation[]}; citations?: WritingCitation[];
  timeline?: {paragraph_id:string; start_ms:number; end_ms:number}[];
};
export type AudioOverview = { latest_render?: AudioRender | null;
  id: string; notebook_id: string; title: string; status: string; error: string | null;
  revision: number; model: string | null; created_at: string; estimated_seconds: number;
  params: {mode:'single'|'duo'; length:'short'|'standard'|'deep'; topic:string; audience:string; voice_a:string; voice_b:string};
  sources: {id:string; filename:string; version:number; state:string}[];
  script?: AudioScript; citations?: WritingCitation[]; renders?: AudioRender[];
};
export const audioStatus: Record<string,string> = {queued:'等待处理',generating:'正在生成讲稿',draft:'待确认讲稿',synthesizing:'正在合成音频',merging:'正在合并音频',complete:'已完成',failed:'处理失败',cancelled:'已取消'};
export function audioTime(ms: number) { const s=Math.floor(ms/1000); return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`; }
