import { NARRATION_LANGUAGE_LABELS } from "./narration";
import { useEffect, useState } from "react";
import type {
  Scene,
  Shot,
  ShotSegment,
  StructuredDirectorSnapshot,
} from "../api";
import type { StoryTarget } from "../api/projection";
import { stableStringify } from "./draft_protection";
import { shotNumber } from "./script_index";
import { TextArea, TextField, toggleId } from "./shared";

// 对白说话者下拉框里“引用库外说话者”的哨兵值；提交时写 character_id=null 与 speaker_label。
const EXTERNAL_SPEAKER = "__external_speaker__";

type Draft = { scene: Scene; shot?: Shot; segment?: ShotSegment };
export function NodeEditor({
  snapshot,
  target,
  scene,
  shot,
  segment,
  busy,
  error,
  onSave,
  onDirty,
}: {
  snapshot: StructuredDirectorSnapshot;
  target: StoryTarget;
  scene: Scene;
  shot?: Shot;
  segment?: ShotSegment;
  busy: boolean;
  error: string | null;
  onSave: (scenes: Scene[], expectedRevision?: number) => void;
  onDirty: (dirty: boolean) => void;
}) {
  const [edit, setEdit] = useState<{
    value: Draft;
    base: string;
    revision: number;
  } | null>(null);
  const live = { scene, shot, segment };
  const dirty = !!edit && stableStringify(edit.value) !== edit.base;
  const conflict = !!edit && edit.revision !== snapshot.revision;
  const [submitted, setSubmitted] = useState<string | null>(null);
  useEffect(() => {
    onDirty(dirty);
    return () => onDirty(false);
  }, [dirty, onDirty]);
  useEffect(() => {
    if (!edit || !submitted || busy || error) return;
    const expected = JSON.parse(submitted) as Scene[];
    // Only close when Core has returned the exact submitted script fields.
    const current = snapshot.director_script?.scenes;
    const wanted = expected.find((s) => s.id === scene.id);
    const actual = current?.find((s) => s.id === scene.id);
    const fields = (s: Scene | undefined) =>
      target.level === "scene"
        ? s && [
            s.title,
            s.summary,
            s.setting,
            s.narration_cues.map((c) => [c.zh?.text ?? "", c.en?.text ?? ""]),
          ]
        : target.level === "shot"
          ? s?.shots.find((x) => x.id === target.id)
          : s?.segments.find((x) => x.id === target.id);
    if (
      snapshot.revision !== edit.revision &&
      JSON.stringify(fields(wanted)) === JSON.stringify(fields(actual))
    ) {
      setEdit(null);
      setSubmitted(null);
    }
  }, [snapshot, busy, error, submitted, edit, scene.id, target]);
  const canEdit = snapshot.allowed_actions.includes("edit_script");
  if (!edit)
    return canEdit ? (
      <button
        className="secondary-button"
        disabled={busy}
        onClick={() => {
          setEdit({
            value: structuredClone(live),
            base: stableStringify(live),
            revision: snapshot.revision,
          });
          setSubmitted(null);
        }}
      >
        编辑这一段
      </button>
    ) : null;
  const value = edit.value;
  const update = (v: Draft) => setEdit({ ...edit, value: v });
  const setScene = (s: Scene) => update({ ...value, scene: s });
  const setShot = (s: Shot) => update({ ...value, shot: s });
  const setSegment = (s: ShotSegment) => update({ ...value, segment: s });
  const savedTiming =
    target.level === "segment"
      ? snapshot.dialogue_timing_warnings.find((item) => item.segment_id === target.id)
      : undefined;
  const segmentShotIds = value.segment?.shot_ids ?? [];
  const segmentStart = segmentShotIds.length
    ? Math.max(
        0,
        value.scene.shots.findIndex((item) => item.id === segmentShotIds[0]),
      )
    : 0;
  const segmentEnd = segmentShotIds.length
    ? Math.max(
        segmentStart,
        value.scene.shots.findIndex(
          (item) => item.id === segmentShotIds[segmentShotIds.length - 1],
        ),
      )
    : segmentStart;
  const segmentIndex = segment ? scene.segments.indexOf(segment) : -1;
  const previousSegment =
    segmentIndex > 0 ? scene.segments[segmentIndex - 1] : undefined;
  const continues =
    segment !== undefined &&
    previousSegment?.shot_ids.at(-1) === value.segment?.shot_ids[0];
  const boundary = value.segment?.boundary_from_previous ?? {
    reason: "continuity_anchor" as const,
    continuity_instruction: "",
  };
  // 覆盖区间只是输入辅助；是否合法（跳过、倒序、非边界重复）由 Core 校验。
  const setCoverage = (start: number, end: number) => {
    const low = Math.min(start, end);
    const high = Math.max(start, end);
    const shotIds = value.scene.shots.slice(low, high + 1).map((item) => item.id);
    const shares = previousSegment?.shot_ids.at(-1) === shotIds[0];
    setSegment({
      ...value.segment!,
      shot_ids: shotIds,
      boundary_from_previous: shares
        ? (value.segment!.boundary_from_previous ?? {
            reason: "continuity_anchor" as const,
            continuity_instruction: "",
          })
        : null,
    });
  };
  return (
    <form
      className="story-node-editor"
      aria-label="编辑当前内容"
      onSubmit={(event) => {
        event.preventDefault();
        if (!dirty || conflict || busy || !canEdit) return;
        const scenes = snapshot.director_script!.scenes.map((s) =>
          s.id !== scene.id
            ? s
            : target.level === "scene"
              ? {
                  ...s,
                  title: value.scene.title,
                  summary: value.scene.summary,
                  setting: value.scene.setting,
                  narration_cues: value.scene.narration_cues,
                }
              : target.level === "shot"
                ? {
                    ...s,
                    shots: s.shots.map((h) => (h.id === shot?.id ? value.shot! : h)),
                  }
                : {
                    ...s,
                    segments: s.segments.map((g) =>
                      g.id === segment?.id ? value.segment! : g,
                    ),
                  },
        );
        setSubmitted(JSON.stringify(scenes));
        onSave(scenes, edit.revision);
      }}
    >
      {conflict ? (
        <p role="alert">
          内容已由其他操作更新。草稿已保留，请复制需要的文字后取消，重新打开最新内容再编辑；当前草稿不能覆盖新版本。
        </p>
      ) : null}
      {error ? <p role="alert">{error} 输入已保留。</p> : null}
      <fieldset disabled={busy || !canEdit}>
        {target.level === "scene" ? (
          <>
            <TextField
              label="标题"
              value={value.scene.title}
              required
              onChange={(title) => setScene({ ...value.scene, title })}
            />
            <TextArea
              label="场景摘要"
              value={value.scene.summary}
              required
              onChange={(summary) => setScene({ ...value.scene, summary })}
            />
            <TextArea
              label="本 Scene 时空与环境"
              value={value.scene.setting}
              required
              onChange={(setting) => setScene({ ...value.scene, setting })}
            />
            {!snapshot.workspace_layers.narration_unlocked
              ? value.scene.narration_cues.flatMap((c, i) =>
                  snapshot.narration_languages.map((language) => (
                  <TextArea
                    key={`${c.id}:${language}`}
                    label={`旁白 ${i + 1} · ${NARRATION_LANGUAGE_LABELS[language]}`}
                    value={c[language]!.text}
                    onChange={(text) =>
                      setScene({
                        ...value.scene,
                        narration_cues: value.scene.narration_cues.map((x) =>
                          x.id === c.id ? { ...x, [language]: { ...x[language], text } } : x,
                        ),
                      })
                    }
                  />
                  )),
                )
              : null}
          </>
        ) : null}
        {target.level === "shot" && value.shot ? (
          <>
            <fieldset className="character-checkboxes">
              <legend>画面中可见角色</legend>
              {snapshot.reference_library.characters.map((c) => (
                <label key={c.id}>
                  <input
                    type="checkbox"
                    checked={value.shot!.visible_character_ids.includes(c.id)}
                    onChange={() =>
                      setShot({
                        ...value.shot!,
                        visible_character_ids: toggleId(
                          value.shot!.visible_character_ids,
                          c.id,
                        ),
                      })
                    }
                  />
                  {c.name}
                </label>
              ))}
            </fieldset>
            {(
              [
                ["composition", "构图"],
                ["camera_movement", "摄影机运动"],
                ["action", "镜头动作"],
                ["audio_direction", "声音方向"],
              ] as const
            ).map(([key, label]) => (
              <TextArea
                key={key}
                label={label}
                value={value.shot![key]}
                onChange={(text) => setShot({ ...value.shot!, [key]: text })}
              />
            ))}
            <TextField
              label="入镜转场（可空）"
              value={value.shot.transition_in ?? ""}
              onChange={(transition_in) =>
                setShot({
                  ...value.shot!,
                  transition_in: transition_in || null,
                })
              }
            />
          </>
        ) : null}
        {target.level === "segment" && value.segment ? (
          <>
            <fieldset className="segment-coverage">
              <legend>覆盖区间（shot_ids）</legend>
              <label className="card-field">
                <span>起始镜头</span>
                <select
                  value={String(segmentStart)}
                  onChange={(e) =>
                    setCoverage(Number(e.target.value), segmentEnd)
                  }
                >
                  {value.scene.shots.map((item, i) => (
                    <option key={item.id} value={String(i)}>
                      镜头 {i + 1} · {item.action.slice(0, 24)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="card-field">
                <span>结束镜头</span>
                <select
                  value={String(segmentEnd)}
                  onChange={(e) =>
                    setCoverage(segmentStart, Number(e.target.value))
                  }
                >
                  {value.scene.shots.map((item, i) => (
                    <option key={item.id} value={String(i)}>
                      镜头 {i + 1} · {item.action.slice(0, 24)}
                    </option>
                  ))}
                </select>
              </label>
              <p className="muted-copy">
                一个片段覆盖一段连续的镜头；保存时由 Core 校验是否跳过镜头、倒序或重复覆盖。
              </p>
            </fieldset>
            <label className="card-field">
              <span>预估时长（秒）</span>
              <input
                type="number"
                min="0.2"
                step="0.1"
                value={value.segment.duration_estimate_seconds}
                onChange={(e) =>
                  setSegment({
                    ...value.segment!,
                    duration_estimate_seconds: Number(e.target.value),
                  })
                }
              />
            </label>
            {savedTiming ? (
              <em role="note">
                已保存版本的对白约需 {savedTiming.estimated_seconds} 秒，超过预估时长
              </em>
            ) : null}
            <TextArea
              label="本段动作"
              value={value.segment.action}
              required
              onChange={(action) => setSegment({ ...value.segment!, action })}
            />
            {value.segment.dialogue_lines.map((line, i) => (
              <div key={i}>
                <label className="card-field">
                  <span>对白角色</span>
                  <select
                    value={line.character_id ?? EXTERNAL_SPEAKER}
                    onChange={(e) =>
                      setSegment({
                        ...value.segment!,
                        dialogue_lines: value.segment!.dialogue_lines.map(
                          (l, j) =>
                            j !== i
                              ? l
                              : e.target.value === EXTERNAL_SPEAKER
                                ? { ...l, character_id: null, speaker_label: l.speaker_label ?? "" }
                                : { ...l, character_id: e.target.value, speaker_label: null },
                        ),
                      })
                    }
                  >
                    {snapshot.reference_library.characters.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                    {line.character_id !== null &&
                    !snapshot.reference_library.characters.some(
                      (c) => c.id === line.character_id,
                    ) ? (
                      <option value={line.character_id}>
                        已移出 @{line.character_id.slice(0, 6)}
                      </option>
                    ) : null}
                    <option value={EXTERNAL_SPEAKER}>引用库外说话者</option>
                  </select>
                </label>
                {line.character_id === null ? (
                  <TextField
                    label="说话者称呼"
                    value={line.speaker_label ?? ""}
                    onChange={(speaker_label) =>
                      setSegment({
                        ...value.segment!,
                        dialogue_lines: value.segment!.dialogue_lines.map(
                          (l, j) => (j === i ? { ...l, speaker_label } : l),
                        ),
                      })
                    }
                  />
                ) : null}
                <TextArea
                  label="对白"
                  value={line.text}
                  required
                  onChange={(text) =>
                    setSegment({
                      ...value.segment!,
                      dialogue_lines: value.segment!.dialogue_lines.map(
                        (l, j) => (j === i ? { ...l, text } : l),
                      ),
                    })
                  }
                />
                <TextField
                  label="说话方式"
                  value={line.delivery}
                  onChange={(delivery) =>
                    setSegment({
                      ...value.segment!,
                      dialogue_lines: value.segment!.dialogue_lines.map(
                        (l, j) => (j === i ? { ...l, delivery } : l),
                      ),
                    })
                  }
                />
              </div>
            ))}
            {continues ? (
              <>
                <p className="muted-copy">
                  本段与上一片段共享镜头{" "}
                  {shotNumber(scene, value.segment.shot_ids[0])}
                  ，延续同一镜头时必须填写切分原因与边界连续性说明。
                </p>
                <label className="card-field">
                  <span>与上一段的切分原因</span>
                  <select
                    value={boundary.reason}
                    onChange={(e) =>
                      setSegment({
                        ...value.segment!,
                        boundary_from_previous: {
                          ...boundary,
                          reason: e.target.value as NonNullable<
                            ShotSegment["boundary_from_previous"]
                          >["reason"],
                        },
                      })
                    }
                  >
                    {Object.entries({
                      model_constraint: "模型约束",
                      continuity_anchor: "连续性锚点",
                      control_boundary: "控制边界",
                      failure_cost: "失败成本",
                    }).map(([k, l]) => (
                      <option key={k} value={k}>
                        {l}
                      </option>
                    ))}
                  </select>
                </label>
                <TextArea
                  label="边界连续性说明"
                  value={boundary.continuity_instruction}
                  required
                  onChange={(continuity_instruction) =>
                    setSegment({
                      ...value.segment!,
                      boundary_from_previous: {
                        ...boundary,
                        continuity_instruction,
                      },
                    })
                  }
                />
              </>
            ) : (
              <p className="muted-copy">
                本段从新镜头开始，不与上一片段共享边界 Shot，不需要延续说明。
              </p>
            )}
          </>
        ) : null}
      </fieldset>
      <p>保存会由 Core 校验当前 revision 并更新相关下游依赖，历史素材保留。</p>
      <button
        className="primary-button"
        type="submit"
        disabled={busy || !dirty || conflict || !canEdit}
      >
        保存脚本修改
      </button>
      <button
        className="secondary-button"
        type="button"
        disabled={busy}
        onClick={() => {
          if (!dirty || window.confirm("放弃未保存的修改？")) {
            setEdit(null);
            setSubmitted(null);
          }
        }}
      >
        取消编辑
      </button>
    </form>
  );
}
