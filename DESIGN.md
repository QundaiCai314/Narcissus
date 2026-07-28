# XUEZI 1.1.0 Design Direction

## Intent

XUEZI 1.1.0 is a focused premium study console: quiet enough for long reading sessions, structured enough for repeated practice, and expressive through interaction rather than loud decoration.

## Foundations

- Canvas: pale blue-green `#EEF4F4`
- Surfaces: `#FFFFFF`, `#F5F9F8`
- Primary action: deep teal `#087F79`
- Secondary signal: blue `#285A76`
- Caution: amber `#A66B12`
- Error: brick red `#B24435`
- Text: `#112B34`; secondary text: `#4F6870`
- Radius: 10px controls, 12px items, 16px primary containers
- Spacing rhythm: 8 / 12 / 16 / 24 / 32px

## Product Rules

- Keep the current task visually dominant: upload, generate, practice, or analyze.
- Use mint only for primary actions and positive progress.
- Keep answer explanations readable on raised surfaces with generous line height.
- Use progress bars for every AI or parsing operation that can take more than a moment.
- Use motion for feedback: buttons lift on hover, cards rise subtly, selected options shift gently, and content enters with a short fade.
- Respect `prefers-reduced-motion` and keep animation under 420ms for routine interactions.
- Preserve visible focus states and keyboard-friendly controls.
- On narrow screens, stack panels and keep tab navigation horizontally scrollable.

## QA Checklist

- The initial screen renders without console errors.
- Primary buttons remain readable in default, hover, focus, disabled, and loading states.
- Long course names, knowledge points, URLs, and explanations wrap without horizontal overflow.
- Charts retain labels and meaningful contrast on dark surfaces.
- The 1.0.4 source folder remains unchanged.
