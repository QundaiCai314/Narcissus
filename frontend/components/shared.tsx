"use client";
import Link from "next/link";
import { BookOpen, ArrowUpRight, LoaderCircle, LogOut } from "lucide-react";
import { api, post } from "@/lib/api";
import { useRouter } from "next/navigation";

export function Brand() {
  return (
    <Link className="brand" href="/">
      <span className="brand-icon">
        <BookOpen size={20} />
      </span>
      <span className="brand-name">Narcissus</span>
    </Link>
  );
}
export function PaperStudy() {
  return (
    <div className="paper-study" aria-hidden="true">
      <div className="study-orbit" />
      <div className="study-book study-book-back" />
      <div className="study-book study-book-front">
        <span className="study-edition">FIELD NOTES / 01</span>
        <span className="study-book-title">
          Narcissus
        </span>
        <div className="study-lines">
          <i />
          <i />
          <i />
        </div>
        <span className="study-imprint">THE ART OF UNDERSTANDING</span>
      </div>
      <div className="study-note">
        <span>READING NOTE</span>
        <p>
          好的问题，
          <br />
          是理解的开始。
        </p>
        <span className="study-note-rule" />
      </div>
      <span className="study-caption">COLLECT IDEAS. MAKE CONNECTIONS.</span>
    </div>
  );
}
export function Header({ children }: { children?: React.ReactNode }) {
  const router = useRouter();
  return (
    <header className="topbar">
      <Brand />
      <div className="header-actions">
        {children}
        <button
          className="icon-button"
          title="退出登录"
          aria-label="退出登录"
          onClick={async () => {
            try {
              await api("/auth/logout", post());
              router.push("/login");
            } catch {
              window.alert("退出失败，请重试");
            }
          }}
        >
          <LogOut size={18} />
        </button>
      </div>
    </header>
  );
}
export function Loading({ text = "正在加载…" }: { text?: string }) {
  return (
    <div className="loading">
      <LoaderCircle className="spin" size={20} />
      {text}
    </div>
  );
}
export function ErrorNotice({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="error-notice" role="alert">
      {message}
      {retry && (
        <button onClick={retry}>
          重试 <ArrowUpRight size={14} />
        </button>
      )}
    </div>
  );
}
