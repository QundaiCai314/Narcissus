---
name: xuezi-knowledge-structure
description: Structured course-document ingestion for XUEZI. Use when extracting chapters, subject-aware knowledge points, difficulties, misconceptions, and question directions from one or more uploaded documents.
---

# XUEZI Knowledge Structure

1. Preserve uploaded files and extracted chunks as the raw source layer.
2. Identify the subject before naming knowledge points; use the user's subject selection as evidence, not as an unconditional answer.
3. Process long sources in batches for coverage, then run a global consolidation pass across all chunks.
4. Merge synonyms and parent-child duplicates. A knowledge point may cover many chunks; never create one point per paragraph.
5. Exclude copyright pages, cataloging data, ISBN, publisher, printing, edition, pricing, and other publication metadata from learning content.
6. Each final knowledge point must include a student-friendly name, learning goal, detailed explanation, boundary or condition, common mistake, and assessment angle.
7. Keep source chunk IDs only as hidden traceability metadata. Never expose internal IDs in student-facing explanations.
8. When a later upload changes the source set, rebuild the outline from all current chunks and replace stale AI labels instead of appending a second outline.
9. Apply the four-step teacher method: rough-read for the core theme, cut by logical structure, extract the smallest independently testable unit, then rate its teaching weight.
10. Classify each unit as concept, principle, or application; rate it as core mastery, understand-only, or broad reading; attach a concrete teaching requirement and assessment method.
