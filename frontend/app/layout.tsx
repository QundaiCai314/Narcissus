import type { Metadata } from "next";
import "./globals.css";
import "./editorial.css";
import "./study.css";

export const metadata: Metadata = {
  title: "Narcissus · 从阅读到理解",
  description: "围绕你的资料提问与深度研读，让每个答案有据可查。",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
