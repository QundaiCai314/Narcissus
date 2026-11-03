import type { Writing } from "./api";
import type { SourceUnit } from "./sources";
export type Candidate = {id:string;title:string;url:string;domain:string;snippet:string;status:string;error?:string;selected:boolean;document_id?:string;existing_document_id?:string;published_at?:string;fetched_at?:string;action:string;attempts:number;units?:SourceUnit[];details?:{warnings?:string[];user_adjusted?:boolean};};
export type ReportLink = {request_key:string;writing_id:string;version:number;created_at:string;sources:{id:string;version:number;filename:string}[];writing?:Writing};
export type Research = {id:string;question:string;params:{requirements:string;language:string;selected_document_ids?:string[]};status:string;error?:string;queries:string[];attempts:number;usage:unknown[];created_at:string;candidates:Candidate[];reports:ReportLink[]};
export type Capabilities = {configured:boolean;provider:string;notice:string;max_results:number;max_fetches:number;daily_searches:number};
export const researchStatus:Record<string,string>={queued:"等待处理",running:"处理中",complete:"搜索完成",waiting:"等待获取",preview:"可预览",importing:"导入中",imported:"导入中",ready:"已可用",failed:"失败",cancelled:"已取消",deleted:"原始资料已删除",awaiting_confirmation:"需要确认重复或不完整资料"};
