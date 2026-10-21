import { DismissibleDialog } from "../DismissibleDialog";
import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type {
  Scene,
  Shot,
  ShotSegment,
  StructuredDirectorSnapshot,
} from "../api";
import type { ScriptChange, ScriptImpact, ScriptSegmentDraft } from "../api";
import { useUnsavedChanges } from "./draft_protection";
import { findSegmentScene, segmentShotLabel, shotLabel } from "./script_index";
import { TextArea, TextField } from "./shared";

const REASONS: Record<
  NonNullable<ShotSegment["boundary_from_previous"]>["reason"],
  string
> = {
  model_constraint: "模型约束",
  continuity_anchor: "连续性锚点",
  control_boundary: "控制边界",
  failure_cost: "失败成本",
};

/** 影响预览里的服务端对象 ID 到人类可读标签；未知类型原样显示。 */
export function scriptImpactLabel(
  item: string,
  snapshot: StructuredDirectorSnapshot,
): string {
  const scenes = snapshot.director_script?.scenes ?? [];
  const [kind, id, extra] = item.split(":");
  const scene = scenes.find((entry) => entry.id === id);
  const segmentScene = findSegmentScene(scenes, id);
  const segment = segmentScene?.segments.find((entry) => entry.id === id);
  const segmentName = segmentScene
    ? `片段 ${segmentScene.segments.indexOf(segment!) + 1} · ${segmentShotLabel(segmentScene, segment!)}`
    : id.slice(0, 6);
  const labels: Record<string, string> = {
    keyframe_selection: "关键帧图片选择",
    video_selection: `片段视频选择 · ${segmentName}`,
    video_upscale_selection: `片段超分选择 · ${segmentName}`,
    scene_final: `场景成片 · ${scene?.title ?? id.slice(0, 6)}`,
    final_assembly: "最终成片装配",
    workflow_status: "流程状态",
    narration_selection: `旁白音频选择 · ${extra ?? id.slice(0, 6)}`,
    new_generation: "新的生成任务",
    asset_history: "资产历史",
    generation_history: "生成历史",
  };
  if (kind === "scene_final" && scene) return labels[kind];
  return labels[kind] ?? `${kind}${id ? ` · ${id.slice(0, 6)}` : ""}`;
}

/**
 * Scene 页“镜头设计”下的新增镜头入口：新 Shot 只能并入一个已有 Segment，
 * 或者新建一个只覆盖它的 Segment；覆盖由 Core 校验，保存走 v33 整卡。
 */
export function InsertShotSection({
  snapshot,
  scene,
  busy,
  error,
  disabled,
  onSave,
}: {
  snapshot: StructuredDirectorSnapshot;
  scene: Scene;
  busy: boolean;
  error: string | null;
  disabled: boolean;
  onSave: (scenes: Scene[], expectedRevision?: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [submittedRevision, setSubmittedRevision] = useState<number | null>(null);
  const [ownership, setOwnership] = useState<"attach" | "new_segment">(
    scene.segments.length ? "attach" : "new_segment",
  );
  const [segmentId, setSegmentId] = useState(
    scene.segments.at(-1)?.id ?? "",
  );
  const [composition, setComposition] = useState("请补充画面构图。");
  const [cameraMovement, setCameraMovement] = useState("固定机位。");
  const [action, setAction] = useState("请补充镜头内发生的动作。");
  const [audioDirection, setAudioDirection] = useState("");
  const [visibleCharacters, setVisibleCharacters] = useState<string[]>([]);
  const [newDuration, setNewDuration] = useState(3);
  const [newAction, setNewAction] = useState("请补充这一段的连续动作。");
  useUnsavedChanges(open);
  useEffect(() => {
    if (submittedRevision !== null && snapshot.revision !== submittedRevision) {
      setOpen(false);
      setSubmittedRevision(null);
    }
  }, [snapshot.revision, submittedRevision]);
  const canAttach = scene.segments.length > 0 && segmentId !== "";
  const submit = () => {
    const shotId = `new:${crypto.randomUUID()}`;
    const shot: Shot = {
      id: shotId,
      visible_character_ids: visibleCharacters,
      composition,
      camera_movement: cameraMovement,
      action,
      audio_direction: audioDirection,
      transition_in: null,
    };
    const scenes = (snapshot.director_script?.scenes ?? []).map((item) => {
      if (item.id !== scene.id) return item;
      if (ownership === "attach") {
        const target = item.segments.find((entry) => entry.id === segmentId);
        if (target === undefined) return item;
        const shots = [...item.shots];
        const firstIndex = shots.findIndex(
          (entry) => entry.id === target.shot_ids[0],
        );
        const tailIndex = shots.findIndex(
          (entry) => entry.id === target.shot_ids.at(-1),
        );
        // 新镜头紧跟在目标 Segment 的最后一个覆盖 Shot 之后，区间随之延长。
        shots.splice(tailIndex + 1, 0, shot);
        const shotIds = shots
          .slice(firstIndex, tailIndex + 2)
          .map((value) => value.id);
        return {
          ...item,
          shots,
          segments: item.segments.map((entry) =>
            entry.id === target.id
              ? { ...entry, shot_ids: shotIds }
              : entry,
          ),
        };
      }
      return {
        ...item,
        shots: [...item.shots, shot],
        segments: [
          ...item.segments,
          {
            id: `new:${crypto.randomUUID()}`,
            shot_ids: [shotId],
            duration_estimate_seconds: newDuration,
            action: newAction,
            dialogue_lines: [],
            boundary_from_previous: null,
          },
        ],
      };
    });
    setSubmittedRevision(snapshot.revision);
    onSave(scenes, snapshot.revision);
  };
  if (!open)
    return (
      <button
        className="secondary-button"
        type="button"
        disabled={busy || disabled}
        onClick={() => {
          setOwnership(scene.segments.length ? "attach" : "new_segment");
          setSegmentId(scene.segments.at(-1)?.id ?? "");
          setOpen(true);
        }}
      >
        新增镜头
      </button>
    );
  return (
    <form
      className="script-structure-form"
      aria-label="新增镜头"
      onSubmit={(event) => {
        event.preventDefault();
        if (busy || (ownership === "attach" && !canAttach)) return;
        submit();
      }}
    >
      {error ? <p role="alert">{error} 输入已保留。</p> : null}
      <fieldset disabled={busy}>
        <legend>新增镜头</legend>
        <fieldset className="script-ownership">
          <legend>新镜头归属</legend>
          <label>
            <input
              type="radio"
              name="insert-shot-ownership"
              checked={ownership === "attach"}
              disabled={scene.segments.length === 0}
              onChange={() => setOwnership("attach")}
            />
            并入已有片段
          </label>
          <label>
            <input
              type="radio"
              name="insert-shot-ownership"
              checked={ownership === "new_segment"}
              onChange={() => setOwnership("new_segment")}
            />
            新建片段
          </label>
        </fieldset>
        {ownership === "attach" ? (
          <label className="card-field">
            <span>并入哪个片段</span>
            <select
              value={segmentId}
              onChange={(event) => setSegmentId(event.target.value)}
            >
              {scene.segments.map((entry, index) => (
                <option key={entry.id} value={entry.id}>
                  片段 {index + 1} · {segmentShotLabel(scene, entry)}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <>
            <label className="card-field">
              <span>新片段预估时长（秒）</span>
              <input
                type="number"
                min="0.2"
                step="0.1"
                value={newDuration}
                onChange={(event) => setNewDuration(Number(event.target.value))}
              />
            </label>
            <TextArea
              label="新片段动作"
              value={newAction}
              required
              onChange={setNewAction}
            />
          </>
        )}
        <fieldset className="character-checkboxes">
          <legend>画面中可见角色</legend>
          {snapshot.reference_library.characters.map((card) => (
            <label key={card.id}>
              <input
                type="checkbox"
                checked={visibleCharacters.includes(card.id)}
                onChange={() =>
                  setVisibleCharacters((current) =>
                    current.includes(card.id)
                      ? current.filter((value) => value !== card.id)
                      : [...current, card.id],
                  )
                }
              />
              {card.name}
            </label>
          ))}
        </fieldset>
        <TextArea
          label="构图"
          value={composition}
          required
          onChange={setComposition}
        />
        <TextField
          label="摄影机运动"
          value={cameraMovement}
          required
          onChange={setCameraMovement}
        />
        <TextArea label="镜头动作" value={action} required onChange={setAction} />
        <TextField
          label="声音方向"
          value={audioDirection}
          onChange={setAudioDirection}
        />
      </fieldset>
      <button
        className="primary-button"
        type="submit"
        disabled={busy || (ownership === "attach" && !canAttach)}
      >
        保存新镜头
      </button>
      <button
        className="secondary-button"
        type="button"
        disabled={busy}
        onClick={() => setOpen(false)}
      >
        取消新增镜头
      </button>
    </form>
  );
}

type Pending = {
  change: ScriptChange;
  key: string;
  impact: ScriptImpact | null;
  previewed: string | null;
};

function boundaryDraft(
  segment: ShotSegment,
): NonNullable<ScriptSegmentDraft["boundary_from_previous"]> {
  return (
    segment.boundary_from_previous ?? {
      reason: "continuity_anchor",
      continuity_instruction: "",
    }
  );
}

function segmentFields(segment: ShotSegment): ScriptSegmentDraft {
  return {
    shot_ids: [...segment.shot_ids],
    duration_estimate_seconds: segment.duration_estimate_seconds,
    action: segment.action,
    dialogue_lines: segment.dialogue_lines,
    boundary_from_previous: segment.boundary_from_previous,
  };
}

/**
 * Segment 结构修改入口：拆分 / 合并都用 script.apply_operations，并先展示
 * project.preview_impact 的服务端影响预览；失败保留输入并显示服务端错误。
 */
export function SegmentStructureActions({
  snapshot,
  scene,
  segment,
  busy,
  error,
  disabled,
  onPreview,
  onApply,
}: {
  snapshot: StructuredDirectorSnapshot;
  scene: Scene;
  segment: ShotSegment;
  busy: boolean;
  error: string | null;
  disabled: boolean;
  onPreview?: (change: ScriptChange, revision: number) => Promise<ScriptImpact>;
  onApply?: (change: ScriptChange, revision: number) => Promise<boolean>;
}) {
  const [mode, setMode] = useState<"split" | "merge" | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [working, setWorking] = useState(false);
  const [localError, setLocalError] = useState("");
  useUnsavedChanges(mode !== null);
  if (!onPreview || !onApply) return null;
  const segmentIndex = scene.segments.indexOf(segment);
  const next = scene.segments[segmentIndex + 1];
  const previous = segmentIndex > 0 ? scene.segments[segmentIndex - 1] : undefined;
  const mergeLeft = next ? segment : previous;
  const mergeRight = next ?? segment;
  const close = () => {
    setMode(null);
    setPending(null);
    setLocalError("");
  };
  const preview = async (change: ScriptChange, key: string) => {
    setWorking(true);
    setLocalError("");
    try {
      setPending({
        change,
        key,
        impact: await onPreview(change, snapshot.revision),
        previewed: key,
      });
    } catch (caught) {
      setLocalError(caught instanceof Error ? caught.message : "无法读取影响预览。");
    } finally {
      setWorking(false);
    }
  };
  const apply = async () => {
    if (!pending?.impact) return;
    if (pending.impact.revision !== snapshot.revision) return;
    setWorking(true);
    try {
      if (await onApply(pending.change, pending.impact.revision)) close();
    } catch (caught) {
      setLocalError(caught instanceof Error ? caught.message : "保存失败。");
    } finally {
      setWorking(false);
    }
  };
  const stale =
    pending?.impact !== undefined && pending.impact !== null
      ? pending.impact.revision !== snapshot.revision
      : false;
  const outdated = pending !== null && pending.previewed !== pending.key;
  return (
    <>
      <div className="story-reader-tools script-structure-tools">
        <button
          className="secondary-button"
          type="button"
          disabled={busy || disabled}
          onClick={() => {
            setMode("split");
            setPending(null);
            setLocalError("");
          }}
        >
          拆分片段
        </button>
        <button
          className="secondary-button"
          type="button"
          disabled={busy || disabled || scene.segments.length < 2}
          onClick={() => {
            setMode("merge");
            setPending(null);
            setLocalError("");
          }}
        >
          {next ? "与下一片段合并" : "与上一片段合并"}
        </button>
      </div>
      {mode === "split" ? (
        <SplitDialog
          scene={scene}
          segment={segment}
          snapshot={snapshot}
          busy={busy}
          error={error}
          working={working}
          localError={localError}
          pending={pending}
          stale={stale}
          outdated={outdated}
          onClose={close}
          onPreview={preview}
          onApply={apply}
        />
      ) : null}
      {mode === "merge" && mergeLeft && mergeRight ? (
        <MergeDialog
          scene={scene}
          left={mergeLeft}
          right={mergeRight}
          snapshot={snapshot}
          busy={busy}
          error={error}
          working={working}
          localError={localError}
          pending={pending}
          stale={stale}
          outdated={outdated}
          onClose={close}
          onPreview={preview}
          onApply={apply}
        />
      ) : null}
    </>
  );
}

function DialogFrame({
  label,
  busy,
  onClose,
  children,
}: {
  label: string;
  busy: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  return createPortal(
    <div className="scene-asset-picker-backdrop">
      <DismissibleDialog onClose={onClose}
        className="scene-asset-picker-dialog script-structure-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={label}
      >
        <header>
          <h2>{label}</h2>
          <button
            className="secondary-button"
            type="button"
            disabled={busy}
            onClick={onClose}
          >
            取消
          </button>
        </header>
        {children}
      </DismissibleDialog>
    </div>,
    document.body,
  );
}

function ImpactReview({
  impact,
  snapshot,
  stale,
  outdated,
  busy,
  onApply,
  disabled,
}: {
  impact: ScriptImpact;
  snapshot: StructuredDirectorSnapshot;
  stale: boolean;
  outdated: boolean;
  busy: boolean;
  onApply: () => void;
  disabled: boolean;
}) {
  return (
    <section aria-label="服务端影响预览">
      <h3>服务端影响预览</h3>
      <p>
        {impact.will_write
          ? `确认后保存修改，涉及 ${impact.changed_ids.length} 个对象。`
          : "与当前状态相同，无需修改。"}
      </p>
      <h4>将失效的内容</h4>
      {impact.invalidated.length ? (
        <ul>
          {impact.invalidated.map((item) => (
            <li key={item}>{scriptImpactLabel(item, snapshot)}</li>
          ))}
        </ul>
      ) : (
        <p>无下游内容失效。</p>
      )}
      <p className="muted-copy">
        保留：
        {impact.preserved
          .map(
            (item) =>
              ({
                asset_history: "资产历史",
                generation_history: "生成历史",
              })[item] ?? item,
          )
          .join("、") || "无额外变更"}
      </p>
      {stale ? <p role="alert">项目已更新，请取消并重新预览。</p> : null}
      {outdated ? (
        <p role="alert">输入已修改，请重新预览影响。</p>
      ) : null}
      <button
        className="primary-button"
        type="button"
        disabled={busy || stale || outdated || disabled || !impact.will_write}
        onClick={onApply}
      >
        确认保存
      </button>
    </section>
  );
}

function SplitDialog({
  scene,
  segment,
  snapshot,
  busy,
  error,
  working,
  localError,
  pending,
  stale,
  outdated,
  onClose,
  onPreview,
  onApply,
}: {
  scene: Scene;
  segment: ShotSegment;
  snapshot: StructuredDirectorSnapshot;
  busy: boolean;
  error: string | null;
  working: boolean;
  localError: string;
  pending: Pending | null;
  stale: boolean;
  outdated: boolean;
  onClose: () => void;
  onPreview: (change: ScriptChange, key: string) => Promise<void>;
  onApply: () => Promise<void>;
}) {
  const options = segment.shot_ids.flatMap((shotId, index) => {
    const items: { key: string; label: string }[] = [
      {
        key: `inside:${index}`,
        label: `在${shotLabel(scene, shotId)}内部拆（两段共享该镜头，第二段必须延续）`,
      },
    ];
    if (index < segment.shot_ids.length - 1)
      items.push({
        key: `after:${index}`,
        label: `在${shotLabel(scene, shotId)}之后拆（剪辑，不共享边界）`,
      });
    return items;
  });
  const [pointKey, setPointKey] = useState(options[0].key);
  const half = Math.round((segment.duration_estimate_seconds / 2) * 10) / 10;
  const [firstDuration, setFirstDuration] = useState(half);
  const [secondDuration, setSecondDuration] = useState(
    Math.max(
      0.2,
      Math.round((segment.duration_estimate_seconds - half) * 10) / 10,
    ),
  );
  const [firstAction, setFirstAction] = useState(segment.action);
  const [secondAction, setSecondAction] = useState(segment.action);
  const [dialogueSplitIndex, setDialogueSplitIndex] = useState(
    segment.dialogue_lines.length,
  );
  const boundary = boundaryDraft(segment);
  const [reason, setReason] = useState(boundary.reason);
  const [continuity, setContinuity] = useState("");
  const [kind, rawIndex] = pointKey.split(":");
  const index = Number(rawIndex);
  const inside = kind === "inside";
  const firstShotIds = segment.shot_ids.slice(0, index + 1);
  const secondShotIds = segment.shot_ids.slice(inside ? index : index + 1);
  const firstDialogueLines = segment.dialogue_lines.slice(0, dialogueSplitIndex);
  const secondDialogueLines = segment.dialogue_lines.slice(dialogueSplitIndex);
  const speakerName = (line: ShotSegment["dialogue_lines"][number]) =>
    line.speaker_label ??
    snapshot.reference_library.characters.find(
      (character) => character.id === line.character_id,
    )?.name ??
    "未命名角色";
  const dialogueSummary = (lines: ShotSegment["dialogue_lines"]) =>
    lines.length
      ? lines
          .map((line) => `${speakerName(line)}：${line.text}`)
          .join(" / ")
      : "无对白";
  const change: ScriptChange = {
    name: "script.apply_operations",
    arguments: {
      scope: { scene_ids: [scene.id] },
      operations: [
        {
          op: "split_segment",
          segment_id: segment.id,
          preserve_id: "first",
          first: {
            ...segmentFields(segment),
            shot_ids: firstShotIds,
            duration_estimate_seconds: firstDuration,
            action: firstAction,
            dialogue_lines: firstDialogueLines,
          },
          second: {
            shot_ids: secondShotIds,
            duration_estimate_seconds: secondDuration,
            action: secondAction,
            dialogue_lines: secondDialogueLines,
            boundary_from_previous: inside
              ? { reason, continuity_instruction: continuity }
              : null,
          },
        },
      ],
    },
  };
  const key = JSON.stringify(change);
  const incomplete = inside && !continuity.trim();
  return (
    <DialogFrame label="拆分片段" busy={busy} onClose={onClose}>
      {error ? <p role="alert">{error} 输入已保留。</p> : null}
      {localError ? <p role="alert">{localError}</p> : null}
      <fieldset disabled={busy || working}>
        <legend>拆分点</legend>
        <label className="card-field">
          <span>拆分方式</span>
          <select
            value={pointKey}
            onChange={(event) => setPointKey(event.target.value)}
          >
            {options.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <p className="muted-copy">
          前段覆盖 {firstShotIds.map((id) => shotLabel(scene, id)).join("、")}；
          后段覆盖 {secondShotIds.map((id) => shotLabel(scene, id)).join("、")}。
        </p>
        <label className="card-field">
          <span>前段预估时长（秒）</span>
          <input
            type="number"
            min="0.2"
            step="0.1"
            value={firstDuration}
            onChange={(event) => setFirstDuration(Number(event.target.value))}
          />
        </label>
        <TextArea
          label="前段动作"
          value={firstAction}
          required
          onChange={setFirstAction}
        />
        <label className="card-field">
          <span>后段预估时长（秒）</span>
          <input
            type="number"
            min="0.2"
            step="0.1"
            value={secondDuration}
            onChange={(event) => setSecondDuration(Number(event.target.value))}
          />
        </label>
        <TextArea
          label="后段动作"
          value={secondAction}
          required
          onChange={setSecondAction}
        />
        {segment.dialogue_lines.length ? (
          <fieldset className="script-dialogue-allocation">
            <legend>对白分配</legend>
            <label className="card-field">
              <span>对白分界</span>
              <select
                value={dialogueSplitIndex}
                onChange={(event) =>
                  setDialogueSplitIndex(Number(event.target.value))
                }
              >
                {Array.from(
                  { length: segment.dialogue_lines.length + 1 },
                  (_, splitIndex) => (
                    <option key={splitIndex} value={splitIndex}>
                      {splitIndex === 0
                        ? "全部对白放入后段"
                        : splitIndex === segment.dialogue_lines.length
                          ? "全部对白保留在前段"
                          : `在第 ${splitIndex} 句后拆（前段 ${splitIndex} 句，后段 ${segment.dialogue_lines.length - splitIndex} 句）`}
                    </option>
                  ),
                )}
              </select>
            </label>
            <div className="script-dialogue-allocation-preview">
              <p>
                <strong>前段 · {firstDialogueLines.length} 句</strong>
                <span>{dialogueSummary(firstDialogueLines)}</span>
              </p>
              <p>
                <strong>后段 · {secondDialogueLines.length} 句</strong>
                <span>{dialogueSummary(secondDialogueLines)}</span>
              </p>
            </div>
            <p className="muted-copy">
              这里只移动完整对白，不修改正文或表演。原句 ID、生成候选和已选 TTS
              都会保留；拆分后只需重新校准两个片段的发声起点。
            </p>
          </fieldset>
        ) : (
          <p className="muted-copy">本片段没有对白，无需分配。</p>
        )}
        {inside ? (
          <>
            <p className="muted-copy">
              两段共享同一镜头，后段必须填写延续说明（boundary_from_previous）。
            </p>
            <label className="card-field">
              <span>切分原因</span>
              <select
                value={reason}
                onChange={(event) =>
                  setReason(
                    event.target.value as NonNullable<
                      ShotSegment["boundary_from_previous"]
                    >["reason"],
                  )
                }
              >
                {Object.entries(REASONS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <TextArea
              label="边界连续性说明"
              value={continuity}
              required
              onChange={setContinuity}
            />
          </>
        ) : null}
      </fieldset>
      {pending?.impact ? (
        <ImpactReview
          impact={pending.impact}
          snapshot={snapshot}
          stale={stale}
          outdated={outdated}
          busy={busy || working}
          disabled={incomplete}
          onApply={() => void onApply()}
        />
      ) : null}
      <button
        className="secondary-button"
        type="button"
        disabled={busy || working || incomplete}
        onClick={() => void onPreview(change, key)}
      >
        {pending?.impact ? "重新预览影响" : "预览影响"}
      </button>
    </DialogFrame>
  );
}

function MergeDialog({
  scene,
  left,
  right,
  snapshot,
  busy,
  error,
  working,
  localError,
  pending,
  stale,
  outdated,
  onClose,
  onPreview,
  onApply,
}: {
  scene: Scene;
  left: ShotSegment;
  right: ShotSegment;
  snapshot: StructuredDirectorSnapshot;
  busy: boolean;
  error: string | null;
  working: boolean;
  localError: string;
  pending: Pending | null;
  stale: boolean;
  outdated: boolean;
  onClose: () => void;
  onPreview: (change: ScriptChange, key: string) => Promise<void>;
  onApply: () => Promise<void>;
}) {
  const union = [...new Set([...left.shot_ids, ...right.shot_ids])];
  const [duration, setDuration] = useState(
    Math.round(
      (left.duration_estimate_seconds + right.duration_estimate_seconds) * 10,
    ) / 10,
  );
  const [action, setAction] = useState(`${left.action}\n${right.action}`);
  const change: ScriptChange = {
    name: "script.apply_operations",
    arguments: {
      scope: { scene_ids: [scene.id] },
      operations: [
        {
          op: "merge_adjacent_segments",
          left_segment_id: left.id,
          right_segment_id: right.id,
          preserve_id: "left",
          merged: {
            shot_ids: union,
            duration_estimate_seconds: duration,
            action,
            dialogue_lines: [
              ...left.dialogue_lines,
              ...right.dialogue_lines,
            ],
            boundary_from_previous: left.boundary_from_previous,
          },
        },
      ],
    },
  };
  const key = JSON.stringify(change);
  return (
    <DialogFrame label="合并相邻片段" busy={busy} onClose={onClose}>
      {error ? <p role="alert">{error} 输入已保留。</p> : null}
      {localError ? <p role="alert">{localError}</p> : null}
      <fieldset disabled={busy || working}>
        <legend>合并范围</legend>
        <p className="muted-copy">
          合并片段 {scene.segments.indexOf(left) + 1}（
          {segmentShotLabel(scene, left)}）与片段{" "}
          {scene.segments.indexOf(right) + 1}（{segmentShotLabel(scene, right)}）；
          覆盖为并集 {union.map((id) => shotLabel(scene, id)).join("、")}。
        </p>
        <label className="card-field">
          <span>合并后预估时长（秒）</span>
          <input
            type="number"
            min="0.2"
            step="0.1"
            value={duration}
            onChange={(event) => setDuration(Number(event.target.value))}
          />
        </label>
        <TextArea label="合并后动作" value={action} required onChange={setAction} />
      </fieldset>
      {pending?.impact ? (
        <ImpactReview
          impact={pending.impact}
          snapshot={snapshot}
          stale={stale}
          outdated={outdated}
          busy={busy || working}
          disabled={!action.trim()}
          onApply={() => void onApply()}
        />
      ) : null}
      <button
        className="secondary-button"
        type="button"
        disabled={busy || working || !action.trim()}
        onClick={() => void onPreview(change, key)}
      >
        {pending?.impact ? "重新预览影响" : "预览影响"}
      </button>
    </DialogFrame>
  );
}
