"use client";
import { useEffect, useRef, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Eye, EyeOff, BookOpen, MousePointer2 } from "lucide-react";
import { api, post, errorText } from "@/lib/api";
import { Brand } from "@/components/shared";
import { passwordStrength } from "@/lib/password-strength";
import "./auth.css";

type Options = { email_delivery_available: boolean };
type Challenge = { challenge_id: string; expires_in: number; retry_after: number };
export default function Login() {
  const router = useRouter();
  const [register, setRegister] = useState(false), [email, setEmail] = useState(""), [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState(""), [code, setCode] = useState(""), [visible, setVisible] = useState(false), [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false), [sending, setSending] = useState(false);
  const [options, setOptions] = useState<Options | null>(null), [optionsFailed, setOptionsFailed] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [challenge, setChallenge] = useState(""), [expires, setExpires] = useState(0), [retry, setRetry] = useState(0), [now, setNow] = useState(0);
  const generation = useRef(0), emailInput = useRef<HTMLInputElement>(null), sendingController = useRef<AbortController | null>(null);
  const strength = passwordStrength(password), seconds = Math.max(0, Math.ceil((retry - now) / 1000)), expired = !!expires && now >= expires;
  async function loadOptions() {
    setOptionsFailed(false);
    try { setOptions(await api<Options>("/auth/registration-options")); } catch { setOptionsFailed(true); }
  }
  useEffect(() => {
    api("/auth/me").then(() => router.replace("/")).catch(() => {
      if (new URLSearchParams(window.location.search).has("expired")) setError("登录已过期，请重新登录");
    });
    void loadOptions();
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => { clearInterval(clock); sendingController.current?.abort(); };
  }, [router]);
  function changeEmail(value: string) {
    setEmail(value); generation.current++; sendingController.current?.abort();
    setSending(false); setChallenge(""); setCode(""); setExpires(0); setRetry(0); setNotice(""); setError("");
  }
  function changeMode(value: boolean) {
    if (busy || sending) return;
    setRegister(value); setError(""); setVisible(false); setConfirm(""); setTouched(false); setPassword("");
  }
  async function sendCode() {
    if (sending || seconds > 0 || !options?.email_delivery_available || !emailInput.current?.reportValidity()) return;
    const version = generation.current, controller = new AbortController(); sendingController.current = controller;
    setSending(true); setError(""); setNotice(""); setChallenge(""); setCode(""); setExpires(0);
    try {
      const result = await api<Challenge>("/auth/email-code", { ...post({ email: email.trim() }), signal: controller.signal });
      if (version !== generation.current) return;
      const time = Date.now(); setNow(time); setChallenge(result.challenge_id);
      setExpires(time + result.expires_in * 1000); setRetry(time + result.retry_after * 1000);
      setNotice("验证码已发送，10 分钟内有效；请留意垃圾邮件。");
    } catch (e) { if (version === generation.current && !controller.signal.aborted) setError(errorText(e)); }
    finally { if (version === generation.current) setSending(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy || sending) return; setError("");
    if (register) {
      setTouched(true);
      if (strength.problem) { setError(strength.problem); return; }
      if (confirm !== password) { setError("两次输入的密码不一致"); return; }
      if (!options?.email_delivery_available) { setError("注册邮件暂未开通，请稍后再试；已有账号可登录。"); return; }
      if (!challenge || expired) { setError("请先获取有效的邮箱验证码"); return; }
      if (!/^\d{6}$/.test(code)) { setError("请输入邮件中的 6 位验证码"); return; }
    }
    setBusy(true);
    try {
      await api("/auth/" + (register ? "register" : "login"), post({ email: email.trim(), password,
        ...(register ? { confirm_password: confirm, challenge_id: challenge, verification_code: code } : {}) }));
      router.replace("/");
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return (
    <main className="account-desktop">
      <a className="account-skip" href="#account-form">跳至账号表单</a>
      <header className="account-masthead"><Brand /><span className="desktop-pixel" aria-hidden="true"><BookOpen size={20} /></span></header>
      <div className="account-spread">
        <section className="vacation-print" aria-label="阅读与好奇">
          <img src="/auth/poolside-riso-v3.webp" alt="浅蓝色遮阳伞与泳池的双墨色度假印画" width={1024} height={1280} fetchPriority="high" />
          <div className="vacation-copy"><h1>让好奇，<br />放个小假。</h1><p>留一点时间，给新的发现。</p></div>
          <MousePointer2 className="vacation-cursor" size={42} aria-hidden="true" />
        </section>
        <section className="account-window" aria-labelledby="account-title">
          <div className="account-window-bar"><span className="window-pixels" aria-hidden="true"><i /><i /><i /></span><span>你的书房</span><span className="window-square" aria-hidden="true" /></div>
          <div className="account-window-body">
            <div className="account-modes" aria-label="账号操作"><button type="button" aria-pressed={!register} disabled={busy || sending} onClick={() => changeMode(false)}>登录</button><button type="button" aria-pressed={register} disabled={busy || sending} onClick={() => changeMode(true)}>注册</button></div>
            <h2 id="account-title">{register ? "留一页，给新发现" : "回到你的书房"}</h2>
            <p className="account-welcome">{register ? "从一个账号，开始你的阅读收藏。" : "接着上次的好奇，继续读下去。"}</p>
            <form id="account-form" onSubmit={submit} aria-label={register ? "注册账号" : "登录账号"}>
              <fieldset disabled={busy}>
                <label className="account-field" htmlFor="account-email">邮箱地址</label>
                <input ref={emailInput} id="account-email" name="email" type="email" autoComplete="email" required maxLength={254} value={email} placeholder="you@example.com" onChange={(e) => changeEmail(e.target.value)} />
                {register && <div className="verification-group"><label className="account-field" htmlFor="account-code">邮箱验证码</label><div className="verification-row"><input id="account-code" name="verification_code" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} required placeholder="6 位验证码" disabled={!challenge || expired || sending} onChange={(e) => setCode(e.target.value.replace(/[^0-9]/g, ""))} /><button type="button" className="send-code" disabled={sending || seconds > 0 || !options?.email_delivery_available || !email.trim()} onClick={sendCode}>{sending ? "发送中…" : seconds > 0 ? `${seconds} 秒后重发` : challenge || expired ? "重新获取" : "获取验证码"}</button></div>
                  <div className="verification-status" role="status">{optionsFailed ? <>暂时无法检查注册服务。<button type="button" onClick={loadOptions}>重试</button></> : !options ? "正在检查注册服务…" : !options.email_delivery_available ? "注册邮件暂未开通，已有账号可正常登录。" : expired ? "验证码已过期，请重新获取。" : notice}</div></div>}
                <label className="account-field" htmlFor="account-password">密码</label>
                <div className="account-password"><input id="account-password" name="password" type={visible ? "text" : "password"} autoComplete={register ? "new-password" : "current-password"} required maxLength={256} value={password} placeholder={register ? "至少 10 位，建议 15 位以上" : "输入你的密码"} aria-describedby={register && password ? "password-guidance" : undefined} onChange={(e) => { setPassword(e.target.value); setError(""); }} /><button type="button" aria-label={visible ? "隐藏密码" : "显示密码"} aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>
                {register && password && <div id="password-guidance" className="password-guidance" data-score={strength.score}><div className="strength-heading"><span>安全性参考：{strength.label}</span><span aria-hidden="true" className="strength-bars">{[1, 2, 3, 4].map((n) => <i key={n} data-filled={n <= strength.score} />)}</span></div><p>{strength.hint}</p></div>}
                {register && <><label className="account-field" htmlFor="account-confirm">确认密码</label><input id="account-confirm" name="confirm_password" type={visible ? "text" : "password"} autoComplete="new-password" required maxLength={256} value={confirm} placeholder="再次输入密码" aria-invalid={touched && confirm !== password} aria-describedby={touched && confirm !== password ? "confirm-error" : undefined} onBlur={() => setTouched(true)} onChange={(e) => { setConfirm(e.target.value); setError(""); }} />{touched && confirm !== password && <p id="confirm-error" className="account-inline-error">两次输入的密码不一致</p>}</>}
                {error && <p className="account-error" role="alert">{error}</p>}
                <button className="account-submit" type="submit" disabled={busy || sending || (register && (!options?.email_delivery_available || !challenge || expired))}><span>{busy ? "请稍候…" : register ? "创建我的书房" : "进入书房"}</span><ArrowRight size={20} /></button>
              </fieldset>
            </form>
            <div className="account-switch"><span>{register ? "已经有账号了？" : "还没有自己的书房？"}</span><button type="button" disabled={busy || sending} onClick={() => changeMode(!register)}>{register ? "回到登录" : "创建账号"}</button></div>
          </div>
        </section>
      </div>
    </main>
  );
}
