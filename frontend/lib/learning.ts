import { Citation, WritingCitation } from "./api";
export type LearningKind = "mindmap" | "flashcards" | "quiz";
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
export type QuizQuestion = {
  id: string;
  question: string;
  options: string[];
  point?: string;
  selected: number | null;
  submitted: boolean;
  correct?: boolean;
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
