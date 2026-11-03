"use client";
import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { api, post, errorText } from "@/lib/api";
import { Brand, ErrorNotice, PaperStudy } from "@/components/shared";

export default function Login() {
  const router = useRouter();
  const [register, setRegister] = useState(false),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    api("/auth/me")
      .then(() => router.replace("/"))
      .catch(() => {
        if (new URLSearchParams(window.location.search).has("expired"))
          setError("登录已过期，请重新登录");
      });
  }, [router]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(
        "/auth/" + (register ? "register" : "login"),
        post({ email, password }),
      );
      router.replace("/");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-shell">
      <div className="auth-intro">
        <Brand />
        <div className="intro-copy">
          <span className="eyebrow">A QUIET PLACE FOR IDEAS</span>
          <h1>
            在字里行间，
            <br />
            遇见新的理解。
          </h1>
          <p>
            把散落的文档放进一本笔记。
            <br />
            从一个问题开始，连接知识，回到出处。
          </p>
          <PaperStudy />
        </div>
        <div className="intro-foot">
          <ShieldCheck size={16} /> 资料仅自己可见 · 答案可追溯原文
        </div>
      </div>
      <div className="auth-form-side">
        <form className="auth-form" onSubmit={submit}>
          <span className="eyebrow">你的个人知识空间</span>
          <h2>{register ? "开启你的第一本笔记" : "欢迎回来"}</h2>
          <p>
            {register
              ? "使用邮箱创建账号，开始整理与探索。"
              : "继续阅读，继续发现。"}
          </p>
          {error && <ErrorNotice message={error} />}
          <label>
            邮箱地址
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              placeholder="you@example.com"
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            密码
            <input
              type="password"
              autoComplete={register ? "new-password" : "current-password"}
              required
              minLength={10}
              maxLength={128}
              value={password}
              placeholder="至少 10 位字符"
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button className="button primary full" disabled={busy}>
            {busy ? "请稍候…" : register ? "创建账号" : "登录"}
            <ArrowRight size={18} />
          </button>
          <div className="auth-switch">
            {register ? "已有账号？" : "还没有账号？"}
            <button
              type="button"
              onClick={() => {
                setRegister(!register);
                setError("");
              }}
            >
              {register ? "登录" : "注册账号"}
            </button>
          </div>
          <p className="privacy-note">
            Narcissus根据你提供的资料辅助研读。
            <br />
            重要结论，请通过引用核对原文。
          </p>
        </form>
      </div>
    </main>
  );
}
