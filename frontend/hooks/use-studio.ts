"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorText, Page, Writing } from "@/lib/api";
import { LearningSet } from "@/lib/learning";
import { AudioOverview } from "@/lib/audio";
import { Visual } from "@/lib/visuals";
type WritingBrief = Omit<Writing, "content" | "details" | "citations">;

export function useStudio(notebookId: string, revision: string) {
  const [writings, setWritings] = useState<WritingBrief[]>([]);
  const [audio, setAudio] = useState<AudioOverview[]>([]);
  const [learning, setLearning] = useState<LearningSet[]>([]);
  const [visuals, setVisuals] = useState<Visual[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [pages, setPages] = useState(1);
  const sequence = useRef(0);
  const refresh = useCallback(async () => {
    const ticket = ++sequence.current;
    try {
      const results = await Promise.all(Array.from({ length: pages }, async (_, i) => {
        const [writing, study, sound, visual] = await Promise.all([
          api<Page<WritingBrief>>(`/notebooks/${notebookId}/writings?limit=30&offset=${i * 30}`),
          api<Page<LearningSet>>(`/notebooks/${notebookId}/learning?limit=30&offset=${i * 30}`),
          api<Page<AudioOverview>>(`/notebooks/${notebookId}/audio?limit=30&offset=${i * 30}`),
          api<Page<Visual>>(`/notebooks/${notebookId}/visuals?limit=30&offset=${i * 30}`),
        ]);
        return { writing, study, sound, visual };
      }));
      if (ticket !== sequence.current) return;
      setWritings([...new Map(results.flatMap(p => p.writing.items).map(w => [w.id, w])).values()]);
      setLearning([...new Map(results.flatMap(p => p.study.items).map(w => [w.id, w])).values()]);
      setAudio([...new Map(results.flatMap(p => p.sound.items).map(w => [w.id, w])).values()]);
      setVisuals([...new Map(results.flatMap(p => p.visual.items).map(w => [w.id, w])).values()]);
      setMore(results[0].visual.total > pages * 30 || results[0].sound.total > pages * 30 || results[0].writing.total > pages * 30 || results[0].study.total > pages * 30);
      setError("");
    } catch (e) {
      if (ticket === sequence.current) setError(errorText(e));
    } finally {
      if (ticket === sequence.current) setLoading(false);
    }
  }, [notebookId, pages]);
  useEffect(() => {
    refresh();
  }, [refresh, revision]);

  useEffect(() => {
    const onFocus = () => { if (!document.hidden) refresh(); };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh]);

  useEffect(() => {
    const hasActiveJob =
      writings.some(w => w.job && ["queued", "running"].includes(w.job.status)) ||
      audio.some(a => ["queued", "running", "generating", "synthesizing", "merging"].includes(a.latest_render?.status || a.status)) ||
      learning.some(l => ["queued", "generating", "synthesizing"].includes(l.status) || ["generating", "validating"].includes(l.phase)) ||
      visuals.some(v => v.jobs?.some(j => ["queued", "running"].includes(j.status)));

    if (!hasActiveJob) return;

    const timer = setInterval(() => {
      if (!document.hidden) refresh();
    }, 3500);

    return () => clearInterval(timer);
  }, [writings, audio, learning, visuals, refresh]);
  return { writings, learning, audio, visuals, error, loading, more, refresh, loadMore: () => setPages(p => p + 1) };
}
