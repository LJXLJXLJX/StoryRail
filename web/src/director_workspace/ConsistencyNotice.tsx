import { useState } from "react";
import { copyText } from "./clipboard";
import { consistencySummary, formatConsistencyTask, type ContentChange } from "./consistency";

export function ConsistencyNotice({ project, changes, reminder, onDismiss }: {
  project: { id: string; title: string }; changes: ContentChange[];
  reminder: string | null; onDismiss: () => void;
}) {
  const text = formatConsistencyTask(project, changes);
  const [result, setResult] = useState<{ text: string; copied: boolean } | null>(null);
  return <aside className="consistency-notice" aria-label="内容修改提醒">
    <p role="status">{consistencySummary(changes)}</p>
    {reminder ? <p>{reminder}</p> : null}
    <div className="consistency-actions">
      <button className="secondary-button" onClick={async () => setResult({ text, copied: await copyText(text) })}>复制校对任务</button>
      <button className="text-button" onClick={onDismiss}>关闭提醒</button>
    </div>
    {result?.text === text ? result.copied ? <p role="status">已复制，请发给当前项目的 Agent</p> : <label>自动复制失败，请全选下方任务手动复制<textarea aria-label="手动复制校对任务" readOnly value={text} onFocus={e => e.currentTarget.select()} /></label> : null}
  </aside>;
}
