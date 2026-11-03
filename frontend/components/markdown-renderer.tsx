"use client";
import React, { useState } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import { Citation, WritingCitation } from "@/lib/api";
import { sourcePosition } from "@/lib/sources";
import { Check, Copy } from "lucide-react";

interface MarkdownRendererProps {
  content: string;
  citations?: (Citation | WritingCitation)[];
  onCitation?: (c: Citation) => void;
  className?: string;
}

function renderMath(tex: string, displayMode: boolean) {
  try {
    const html = katex.renderToString(tex, {
      displayMode,
      throwOnError: false,
    });
    return <span dangerouslySetInnerHTML={{ __html: html }} />;
  } catch {
    return <code>{tex}</code>;
  }
}

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };

  return (
    <div className="md-code-block">
      <div className="md-code-header">
        <span className="md-code-lang">{language || "text"}</span>
        <button
          type="button"
          className="md-code-copy"
          onClick={handleCopy}
          title={copied ? "已复制" : "复制代码"}
          aria-label={copied ? "已复制" : "复制代码"}
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
          <span>{copied ? "已复制" : "复制"}</span>
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

export function MarkdownRenderer({
  content,
  citations = [],
  onCitation,
  className = "",
}: MarkdownRendererProps) {
  // Parse inline tokens: code, bold, italic, links, and [citation]
  function renderInline(text: string): React.ReactNode[] {
    // Regex matches:
    // 1. Citation: \[(\d+)\]
    // 2. Inline Code: `([^`]+)`
    // 3. Bold: \*\*([^*]+)\*\*
    // 4. Italic: \*([^*]+)\*
    // 5. Link: \[([^\]]+)\]\((https?:\/\/[^\s)]+)\)
    // 6. Math: \$([^$\n]+)\$
    const tokenRegex = /(\[\d+\]|`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\(https?:\/\/[^\s)]+\)|\$[^$\n]+\$)/g;
    const parts = text.split(tokenRegex);

    return parts.map((part, index) => {
      if (!part) return null;

      // 1. Citation check: [12]
      const citeMatch = part.match(/^\[(\d+)\]$/);
      if (citeMatch) {
        const labelNum = Number(citeMatch[1]);
        const found = citations.find((c) => c.label === labelNum);
        if (found) {
          const isDeleted = "state" in found && found.state === "deleted";
          const title = `${found.filename || "资料"} · ${sourcePosition(found as Citation)}`;
          return (
            <button
              key={index}
              type="button"
              className={`inline-citation ${isDeleted ? "deleted" : ""}`}
              disabled={isDeleted}
              title={isDeleted ? "原始资料已删除" : title}
              onClick={() => onCitation && onCitation(found as Citation)}
            >
              {labelNum}
            </button>
          );
        }
        return (
          <span key={index} className="missing-citation" title="相关资料已删除或未匹配">
            [{labelNum}]
          </span>
        );
      }

      // 2. Math check: $E(R_i) = R_f + \beta_i (R_m - R_f)$
      const mathMatch = part.match(/^\$([^$\n]+)\$$/);
      if (mathMatch) {
        const expr = mathMatch[1].trim();
        // Skip pure currency like $100 or $99.95
        if (expr && !/^\d+(?:\.\d+)?$/.test(expr)) {
          return (
            <span key={index} className="md-math-inline">
              {renderMath(expr, false)}
            </span>
          );
        }
      }

      // 3. Inline Code: `code`
      if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
        return (
          <code key={index} className="md-inline-code">
            {part.slice(1, -1)}
          </code>
        );
      }

      // 4. Bold: **bold**
      if (part.startsWith("**") && part.endsWith("**") && part.length >= 4) {
        return <strong key={index}>{renderInline(part.slice(2, -2))}</strong>;
      }

      // 5. Italic: *italic*
      if (part.startsWith("*") && part.endsWith("*") && part.length >= 2) {
        return <em key={index}>{renderInline(part.slice(1, -1))}</em>;
      }

      // 6. Link: [title](url)
      const linkMatch = part.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
      if (linkMatch) {
        return (
          <a
            key={index}
            href={linkMatch[2]}
            target="_blank"
            rel="noopener noreferrer"
            className="md-link"
          >
            {linkMatch[1]}
          </a>
        );
      }

      return part;
    });
  }

  // Parse markdown lines into blocks (headings, code blocks, tables, blockquotes, lists, paragraphs)
  const lines = content.split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced Code Block: ```lang
    if (line.trim().startsWith("```")) {
      const lang = line.trim().slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      blocks.push(
        <CodeBlock
          key={`code-${blocks.length}`}
          code={codeLines.join("\n")}
          language={lang}
        />
      );
      continue;
    }

    // Block Math: $$ ... $$
    if (line.trim().startsWith("$$")) {
      const trimmed = line.trim();
      if (trimmed.length > 2 && trimmed.endsWith("$$") && trimmed.slice(2, -2).trim()) {
        blocks.push(
          <div key={`math-${blocks.length}`} className="md-math-block">
            {renderMath(trimmed.slice(2, -2).trim(), true)}
          </div>
        );
        i++;
        continue;
      }
      const mathLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().endsWith("$$")) {
        mathLines.push(lines[i]);
        i++;
      }
      if (i < lines.length && lines[i].trim().endsWith("$$")) {
        const lastPart = lines[i].trim().slice(0, -2).trim();
        if (lastPart) mathLines.push(lastPart);
        i++;
      }
      blocks.push(
        <div key={`math-${blocks.length}`} className="md-math-block">
          {renderMath(mathLines.join("\n"), true)}
        </div>
      );
      continue;
    }

    // Horizontal Rule: --- or ***
    if (/^(\*{3,}|-{3,}|_{3,})$/.test(line.trim())) {
      blocks.push(<hr key={`hr-${blocks.length}`} className="md-hr" />);
      i++;
      continue;
    }

    // Headings: # through ######
    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const headingContent = renderInline(headingMatch[2]);
      const key = `h-${blocks.length}`;
      if (level === 1) blocks.push(<h1 key={key} className="md-h1">{headingContent}</h1>);
      else if (level === 2) blocks.push(<h2 key={key} className="md-h2">{headingContent}</h2>);
      else if (level === 3) blocks.push(<h3 key={key} className="md-h3">{headingContent}</h3>);
      else if (level === 4) blocks.push(<h4 key={key} className="md-h4">{headingContent}</h4>);
      else if (level === 5) blocks.push(<h5 key={key} className="md-h5">{headingContent}</h5>);
      else blocks.push(<h6 key={key} className="md-h6">{headingContent}</h6>);
      i++;
      continue;
    }

    // Blockquote: > text
    if (line.trim().startsWith(">")) {
      const quoteLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        quoteLines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      blocks.push(
        <blockquote key={`quote-${blocks.length}`} className="md-blockquote">
          {quoteLines.map((ql, qidx) => (
            <p key={qidx}>{renderInline(ql)}</p>
          ))}
        </blockquote>
      );
      continue;
    }

    // Markdown Table: lines starting and ending with |
    if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
      const tableRows: string[][] = [];
      let hasHeaderSep = false;
      while (i < lines.length && lines[i].trim().startsWith("|") && lines[i].trim().endsWith("|")) {
        const rowText = lines[i].trim();
        // check if separator row like |---|---|
        if (/^\|(\s*[-:]+[-| :]*\s*)\|$/.test(rowText)) {
          hasHeaderSep = true;
        } else {
          const cells = rowText
            .slice(1, -1)
            .split("|")
            .map((c) => c.trim());
          tableRows.push(cells);
        }
        i++;
      }
      if (tableRows.length > 0) {
        const headerRow = hasHeaderSep ? tableRows[0] : null;
        const bodyRows = hasHeaderSep ? tableRows.slice(1) : tableRows;
        blocks.push(
          <div key={`table-${blocks.length}`} className="md-table-wrap">
            <table className="md-table">
              {headerRow && (
                <thead>
                  <tr>
                    {headerRow.map((h, colIdx) => (
                      <th key={colIdx}>{renderInline(h)}</th>
                    ))}
                  </tr>
                </thead>
              )}
              <tbody>
                {bodyRows.map((row, rowIdx) => (
                  <tr key={rowIdx}>
                    {row.map((cell, cellIdx) => (
                      <td key={cellIdx}>{renderInline(cell)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
        continue;
      }
    }

    // Unordered List: - or * or +
    if (/^\s*[-*+]\s+/.test(line)) {
      const listItems: string[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        listItems.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={`ul-${blocks.length}`} className="md-ul">
          {listItems.map((item, itemIdx) => (
            <li key={itemIdx}>{renderInline(item)}</li>
          ))}
        </ul>
      );
      continue;
    }

    // Ordered List: 1. or 2.
    if (/^\s*\d+\.\s+/.test(line)) {
      const listItems: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        listItems.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i++;
      }
      blocks.push(
        <ol key={`ol-${blocks.length}`} className="md-ol">
          {listItems.map((item, itemIdx) => (
            <li key={itemIdx}>{renderInline(item)}</li>
          ))}
        </ol>
      );
      continue;
    }

    // Blank line
    if (!line.trim()) {
      blocks.push(<div key={`gap-${blocks.length}`} className="md-gap" />);
      i++;
      continue;
    }

    // Regular Paragraph: collect contiguous non-empty lines
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trim().startsWith("```") &&
      !lines[i].trim().startsWith("$$") &&
      !lines[i].trim().startsWith(">") &&
      !lines[i].trim().startsWith("#") &&
      !/^\s*[-*+]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !(lines[i].trim().startsWith("|") && lines[i].trim().endsWith("|"))
    ) {
      paraLines.push(lines[i]);
      i++;
    }

    if (paraLines.length > 0) {
      blocks.push(
        <p key={`p-${blocks.length}`} className="md-p">
          {paraLines.map((pl, plIdx) => (
            <React.Fragment key={plIdx}>
              {renderInline(pl)}
              {plIdx < paraLines.length - 1 && <br />}
            </React.Fragment>
          ))}
        </p>
      );
    }
  }

  return <div className={`markdown-body ${className}`}>{blocks}</div>;
}
