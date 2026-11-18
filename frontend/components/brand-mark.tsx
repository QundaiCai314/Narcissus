/** Original pixel N, drawn on the grid of a small desktop window. */
export function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <rect x="8" y="8" width="36" height="36" rx="3" fill="var(--color-blue, #9eb8d3)" />
      <rect x="3" y="3" width="36" height="36" rx="3" fill="var(--color-paper, #fffdf7)" stroke="currentColor" strokeWidth="1.5" />
      <path d="M3 12h36" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8 7h3v2H8zm5 0h3v2h-3zm5 0h3v2h-3z" fill="currentColor" />
      <path d="M11 31V17h4v4h4v4h4v-8h4v14h-4v-2h-4v-4h-4v6z" fill="currentColor" />
    </svg>
  );
}
