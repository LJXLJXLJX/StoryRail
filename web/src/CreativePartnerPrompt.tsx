import { useState } from "react";
import { copyText } from "./director_workspace/clipboard";
import { creativePartnerPrompt, directorPlanConvertPrompt } from "./creativePrompts";

const PROMPTS = {
  partner: {
    lead: "还没有方案？",
    button: "复制创作搭档提示词",
    text: creativePartnerPrompt,
    fallbackLabel: "创作搭档提示词（手动复制）",
    copied: "已复制。发给你常用的 AI，慢慢聊出想法，再把最终方案贴回来。",
  },
  convert: {
    lead: "已有分镜表或其它格式的方案？",
    button: "复制方案整理提示词",
    text: directorPlanConvertPrompt,
    fallbackLabel: "方案整理提示词（手动复制）",
    copied: "已复制。连同原方案一起发给 AI，再把整理后的方案贴回来。",
  },
} as const;

type PromptKind = keyof typeof PROMPTS;

export function CreativePartnerPrompt() {
  const [copy, setCopy] = useState<{
    kind: PromptKind;
    state: "copying" | "copied" | "failed";
  } | null>(null);

  async function handleCopy(kind: PromptKind) {
    setCopy({ kind, state: "copying" });
    try {
      setCopy({ kind, state: (await copyText(PROMPTS[kind].text)) ? "copied" : "failed" });
    } catch {
      setCopy({ kind, state: "failed" });
    }
  }

  const copying = copy?.state === "copying";
  return (
    <div className="creative-partner-entry">
      {(Object.keys(PROMPTS) as PromptKind[]).map((kind) => (
        <div className="creative-partner-action" key={kind}>
          <span>{PROMPTS[kind].lead}</span>
          <button
            type="button"
            className="creative-partner-copy"
            disabled={copying}
            onClick={() => void handleCopy(kind)}
          >
            {copying && copy.kind === kind ? "正在复制…" : PROMPTS[kind].button}
          </button>
        </div>
      ))}
      <p role="status">
        {copy?.state === "copied"
          ? PROMPTS[copy.kind].copied
          : copy?.state === "failed"
            ? "未能自动复制。点击下方文本全选后手动复制，发给你常用的 AI。"
            : "发给你常用的 AI，从一个想法慢慢聊起，或把已有方案整理成 StoryRail 格式，最后把方案贴回来。"}
      </p>
      {copy?.state === "failed" ? (
        <label className="creative-partner-fallback">
          <span>{PROMPTS[copy.kind].fallbackLabel}</span>
          <textarea
            readOnly
            rows={8}
            value={PROMPTS[copy.kind].text}
            onFocus={(event) => event.currentTarget.select()}
          />
        </label>
      ) : null}
    </div>
  );
}
