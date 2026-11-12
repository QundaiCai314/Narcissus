"use client";
import { ReactNode, useEffect, useRef } from "react";

// Native modal dialogs manage keyboard focus, Escape, and nested PDF previews.
// Keep editors mounted while closed so pending autosaves are not discarded.
export function WorkspaceDialog({ open, label, className = "", onClose, children }: {
  open: boolean; label: string; className?: string;
  onClose: () => void; children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-label={label}
      className={`workspace-dialog ${className}`}
      onClick={(e) => {
        const bounds = ref.current?.getBoundingClientRect();
        if (e.target === ref.current && bounds && (e.clientX < bounds.left || e.clientX > bounds.right || e.clientY < bounds.top || e.clientY > bounds.bottom)) {
          onClose();
        }
      }}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      {children}
    </dialog>
  );
}
