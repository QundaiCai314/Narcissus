"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowUpRight, UserRound } from "lucide-react";
import { api } from "@/lib/api";

export type AccountUser = { id: string; email: string };

export function ProfileAvatar({ email = "", large = false }: { email?: string; large?: boolean }) {
  const initial = Array.from(email.split("@")[0] || "").slice(0, 2).join("").toUpperCase();
  return <span className={`profile-avatar${large ? " profile-avatar-large" : ""}`} aria-hidden="true">
    {initial ? <span>{initial}</span> : <UserRound size={large ? 32 : 18} strokeWidth={1.5} />}
    <i />
  </span>;
}

export function ProfileLink({ email: suppliedEmail, compact = false, onNavigate }: {
  email?: string; compact?: boolean; onNavigate?: () => boolean;
}) {
  const [email, setEmail] = useState(suppliedEmail || "");
  useEffect(() => {
    if (suppliedEmail !== undefined) { setEmail(suppliedEmail); return; }
    const controller = new AbortController();
    api<AccountUser>("/auth/me", { signal: controller.signal }).then(user => setEmail(user.email)).catch(() => {});
    return () => controller.abort();
  }, [suppliedEmail]);
  return <Link href="/account" className={`profile-link${compact ? " profile-link-compact" : ""}`}
    aria-label="个人资料" title={email ? `个人资料 · ${email}` : "个人资料"}
    onNavigate={event => { if (onNavigate && !onNavigate()) event.preventDefault(); }}>
    <ProfileAvatar email={email} />
    <span className="profile-link-label">个人资料</span>
    {!compact && <ArrowUpRight className="profile-link-arrow" size={14} aria-hidden="true" />}
  </Link>;
}
