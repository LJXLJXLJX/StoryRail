import type { ReactNode } from "react";

interface MarkdownTextProps {
  markdown: string;
}

export function MarkdownText({ markdown }: MarkdownTextProps) {
  return <div className="markdown-text">{markdown.split("\n").map(renderLine)}</div>;
}

function renderLine(line: string, index: number): ReactNode {
  const trimmed = line.trim();
  const key = `${index}-${line}`;
  if (trimmed.length === 0) {
    return <div className="markdown-space" key={key} aria-hidden="true" />;
  }
  if (trimmed.startsWith("### ")) {
    return <h4 key={key}>{renderInline(trimmed.slice(4))}</h4>;
  }
  if (trimmed.startsWith("## ")) {
    return <h3 key={key}>{renderInline(trimmed.slice(3))}</h3>;
  }
  if (trimmed.startsWith("# ")) {
    return <h2 key={key}>{renderInline(trimmed.slice(2))}</h2>;
  }
  if (trimmed.startsWith("- ")) {
    return (
      <div className="markdown-bullet" key={key}>
        <span aria-hidden="true">—</span>
        <span>{renderInline(trimmed.slice(2))}</span>
      </div>
    );
  }
  return <p key={key}>{renderInline(line)}</p>;
}

function renderInline(text: string): ReactNode[] {
  return text.split(/(\*\*.*?\*\*|`.*?`)/g).filter(Boolean).map((part, index) => {
    const key = `${index}-${part}`;
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }
    return part;
  });
}
