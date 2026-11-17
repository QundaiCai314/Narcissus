import { Citation, WritingCitation } from "./api";
export type LearningKind = "mindmap" | "flashcards" | "quiz";
export const questionTypes = {
  single: { label: "单项选择题", points: 2 },
  multiple: { label: "多项选择题", points: 3 },
  true_false: { label: "判断题", points: 2 },
  fill_blank: { label: "填空题", points: 4 },
  term: { label: "名词解释", points: 5 },
  short_answer: { label: "简答题", points: 8 },
  calculation: { label: "计算与证明题", points: 10 },
  essay: { label: "论述题", points: 12 },
  case_analysis: { label: "材料分析题", points: 12 },
} as const;
export type QuestionType = keyof typeof questionTypes;
export const objectiveTypes: QuestionType[] = [
  "single",
  "multiple",
  "true_false",
];
export type LearningItem = {
  id: string;
  title?: string;
  parent_id?: string | null;
  question?: string;
  answer?: string;
  explanation?: string;
  point?: string;
  options?: string[];
  refs: number[];
  source_entry_id?:string;
  directory?:{number:string|null;title:string;kind:string;printed_page:number|null;toc_pdf_page:number|null;target_pdf_page:number|null};
};
export type AttemptBrief = {
  id: string;
  status: string;
  mode: string;
  created_at: string;
  completed_at: string | null;
  answered: number;
  correct: number;
  total: number;
  score: number | null;
  delivery?: "practice" | "exam";
  earned_points?: number;
  total_points?: number;
  pending_review?: number;
  self_assessed?: boolean;
};
export type LearningSet = {
  id: string;
  family_id: string;
  version: number;
  kind: LearningKind;
  title: string;
  params: {
    topic: string;
    audience: string;
    difficulty: string;
    count: number;
    origin?:'outline';
    question_types?: QuestionType[];
    study_stage?: "university" | "postgraduate";
    subject?: string;
  };
  status: string;
  phase: string;
  attempts: number;
  error: string | null;
  warning: string | null;
  created_at: string;
  completed_at: string | null;
  model: string | null;
  count: number;
  sources: { id: string; filename: string; version: number; state: string }[];
  items?: LearningItem[];
  citations?: WritingCitation[];
  mastery?: { mastered: number; review: number; total: number };
  latest_attempt?: AttemptBrief | null;
  outline?:{entry_count:number;covered_entries:number;node_count:number;chapter_count:number;part_count:number;directory_depth:number;map_depth:number;source_name:string;pages_read:number[];model_calls:number;embedding_calls:number;review_pending:number};
  directory_reference?:DirectoryReference|null;
  directory_coverage?:DirectoryCoverage;
  coverage_review?:{basis:'model_planned_topics';expected_sections:string[];missing_sections:string[]};
  page_mapping?:{source_pdf:SourcePDF;ranges:PageRange[];entry_targets:PageTarget[];reference_fingerprint:string}|null;
  page_locations?:PageLocations;
};
export type SourcePDF={sha256:string;total_pages:number};
export type PageRange={printed_start:number;printed_end:number;pdf_start:number;pdf_end:number;verified:boolean};
export type PageTarget={entry_id:string;pdf_page:number;verified:boolean};
export type PageLocation={entry_id:string;number:string|null;title:string;printed_page:number|null;toc_pdf_page:number|null;body_pdf_page:number|null;method:string;verified:boolean;legacy_target_ignored:boolean};
export type PageLocations={available:false;reason:string}|{available:true;source_bound:boolean;stale:boolean;source_pdf:SourcePDF|null;entries:number;mapped:number;unmapped:number;locations:PageLocation[];reason:string};
export type DirectoryReference={title:string;source_name:string;entries:Record<string,unknown>[];pages_read:number[];source_pdf?:SourcePDF};
export type DirectoryDifference={id:string;number:string|null;title:string};
export type DirectoryCoverage={available:false;reason:string}|{
  available:true;basis:string;reference_confirmed:boolean;source_name:string;expected_entries:number;present_entries:number;healthy_entries:number;
  missing:DirectoryDifference[];misplaced:DirectoryDifference[];changed:DirectoryDifference[];duplicates:DirectoryDifference[];
  unexpected:{id:string;title:string}[];structural_issues:string[];review_pending:number;reference_fingerprint:string;complete:boolean;
  chapters:{id:string;number:string|null;title:string;expected:number;present:number;healthy:number;missing:number;misplaced:number;changed:number;duplicates:number}[];
};
export type CardProgress = {
  revision: number;
  states: Record<string, string>;
  order: string[];
  current_id: string | null;
  mode: "all" | "review";
  shuffled: boolean;
  updated_at: string;
};
export type QuizImage = { id: string; url: string; width: number; height: number };
export type QuizQuestion = {
  id: string;
  question: string;
  options: string[];
  point?: string;
  selected: number | null;
  question_type?: QuestionType;
  points?: number;
  selected_indices?: number[];
  text?: string;
  images?: QuizImage[];
  correct_indices?: number[];
  answer?: string;
  rubric?: { id: string; text: string; points: number }[];
  rubric_scores?: Record<string, number>;
  grading?: "automatic" | "self_pending" | "self_assessed" | "unanswered";
  earned?: number | null;
  submitted: boolean;
  correct?: boolean | null;
  correct_index?: number;
  explanation?: string;
  refs?: number[];
};
export type QuizAttempt = AttemptBrief & {
  set_id: string;
  version: number;
  revision: number;
  items: QuizQuestion[];
  weak_points: { point: string; wrong: number; refs: number[] }[];
  citations: WritingCitation[];
};
export type OnCitation = (c: Citation) => void;
export type LearningContext = { set_id: string; node_id: string };
export const kindNames: Record<LearningKind, string> = {
  mindmap: "思维导图",
  flashcards: "闪卡",
  quiz: "测验",
};
export const phaseNames: Record<string, string> = {
  queued: "等待生成",
  gathering: "正在阅读资料",
  generating: "正在整理学习内容",
  reviewing: "正在核对证据与题目",
  complete: "已就绪",
  failed: "生成失败",
  cancelled: "已取消",
};
