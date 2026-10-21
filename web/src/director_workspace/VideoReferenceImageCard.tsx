import { useState } from "react";
import { createPortal } from "react-dom";
import type {
  RecipeBinding,
  StructuredDirectorSnapshot,
  VideoReferenceImagePlan,
} from "../api";
import { useProtectedValue } from "./draft_protection";
import {
  assetById,
  GenerationCandidateList,
  MultiImageAssetPickerDialog,
  ZoomableImage,
} from "./shared";

export function VideoReferenceImageCard({
  snapshot,
  segmentId,
  sceneId,
  index,
  label,
  plan,
  binding,
  disabled,
  selectionDisabled,
  onCommand,
  onChoose,
  onRemove,
  onDescribe,
  onDismiss,
  onCancel,
}: {
  snapshot: StructuredDirectorSnapshot;
  segmentId: string;
  sceneId: string;
  index: number;
  label: string;
  plan?: VideoReferenceImagePlan;
  binding?: RecipeBinding;
  disabled: boolean;
  selectionDisabled: boolean;
  onCommand?: (name: string, args: Record<string, unknown>) => void;
  onChoose: (kind: "keyframe" | "reference") => void;
  onRemove: () => void;
  onDescribe: (description: string) => void;
  onDismiss?: (generationId: string) => void;
  onCancel?: (generationId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [referencesOpen, setReferencesOpen] = useState(false);
  const draft = useProtectedValue({
    prompt_text: plan?.prompt_text ?? "",
    description: plan?.description ?? binding?.description ?? "",
    visible_character_ids: plan?.visible_character_ids ?? [],
    character_references: plan?.character_references ?? [],
    reference_asset_ids: plan?.reference_asset_ids ?? [],
  });
  const asset = binding ? assetById(snapshot.assets, binding.asset_id) : null;
  const sourceKeyframe = binding
    ? snapshot.keyframe_plan?.keyframes.find(
        (item) => item.selected_asset_id === binding.asset_id,
      )
    : undefined;
  const candidates = plan
    ? snapshot.generations.filter(
        (item) =>
          item.kind === "video_reference_image" &&
          item.target_id === plan.id &&
          !item.dismissed,
      )
    : [];
  const active = candidates.find((item) =>
    ["submitting", "queued", "running", "submission_uncertain"].includes(
      item.phase,
    ),
  );
  const scope = { scene_ids: [sceneId] };
  const select = (assetId: string) =>
    onCommand?.("video.select_reference_image", {
      scope,
      segment_id: segmentId,
      slot_index: index,
      asset_id: assetId,
      description: binding?.description?.trim() || plan?.description || "",
    });
  const setLook = (characterId: string, lookId: string | null) =>
    draft.setValue((current) => ({
      ...current,
      character_references: [
        ...current.character_references.filter(
          (item) => item.character_id !== characterId,
        ),
        { character_id: characterId, look_id: lookId },
      ],
    }));
  return (
    <article
      className="video-reference-image-card"
      aria-label={`其他图片 ${index + 1}`}
    >
      <header>
        <strong>{label}</strong>
        <small>无时间位置 · 视觉参考</small>
      </header>
      {asset ? (
        <ZoomableImage
          src={asset.content_url}
          alt={asset.display_name ?? label}
        />
      ) : (
        <div className="video-reference-image-empty">
          {plan ? "已规划，等待生成或选图" : "尚未规划或选图"}
        </div>
      )}
      {binding ? (
        <small>
          {sourceKeyframe
            ? `关键帧 @${sourceKeyframe.id.slice(0, 6)}`
            : plan
              ? "生成参考图 / 资产库图片"
              : "资产库参考图"}
        </small>
      ) : null}
      {binding ? (
        <label>
          <span>实际内容与参考用途</span>
          <textarea
            aria-label={`其他图片 ${index + 1} 描述`}
            aria-invalid={!binding.description?.trim()}
            maxLength={2000}
            value={binding.description ?? ""}
            disabled={disabled}
            onChange={(event) => onDescribe(event.target.value)}
          />
        </label>
      ) : plan ? (
        <p>{plan.description}</p>
      ) : null}
      <div className="video-reference-image-actions">
        <button
          className="secondary-button"
          type="button"
          disabled={disabled || onCommand === undefined || active !== undefined}
          onClick={() => setOpen(true)}
        >
          规划 / 编辑
        </button>
        <button
          className="primary-button"
          type="button"
          disabled={
            disabled ||
            onCommand === undefined ||
            !plan?.prompt_text.trim() ||
            active !== undefined
          }
          onClick={() =>
            onCommand?.("video.generate_reference_image", {
              image_id: plan!.id,
            })
          }
        >
          生成候选
        </button>
        <button
          className="secondary-button"
          type="button"
          disabled={disabled}
          onClick={() => onChoose("keyframe")}
        >
          从关键帧选择
        </button>
        <button
          className="secondary-button"
          type="button"
          disabled={disabled}
          onClick={() => onChoose("reference")}
        >
          从资产库选择参考图
        </button>
        {binding ? (
          <button
            className="secondary-button"
            type="button"
            disabled={disabled}
            onClick={onRemove}
          >
            移除其他图片
          </button>
        ) : null}
      </div>
      {active ? <p role="status">{active.message}</p> : null}
      {active && onCancel && active.allowed_actions.includes("cancel") ? (
        <button disabled={disabled} onClick={() => onCancel(active.id)}>
          取消生成
        </button>
      ) : null}
      {plan ? (
        <GenerationCandidateList
          kind="keyframe"
          target={plan.id}
          assets={snapshot.assets}
          candidates={candidates}
          busy={disabled}
          renderCandidate={(_, candidate) =>
            candidate ? (
              <ZoomableImage
                src={candidate.content_url}
                alt={candidate.display_name ?? label}
              />
            ) : (
              <p>图片不可用</p>
            )
          }
          summary={`查看其他图片 ${index + 1} 候选（${candidates.length}）`}
          selectLabel="选择候选"
          selectedLabel="当前选择"
          onSelect={(generation) => {
            if (generation.output_asset_id) select(generation.output_asset_id);
          }}
          selectDisabled={(generation, candidate) =>
            disabled ||
            selectionDisabled ||
            onCommand === undefined ||
            !generation.allowed_actions.includes("select_output") ||
            candidate.id === binding?.asset_id
          }
          isSelected={(_, candidate) => candidate?.id === binding?.asset_id}
          onDismiss={(generationId) => onDismiss?.(generationId)}
          dismissLabel="隐藏候选"
          dismissConfirmation="隐藏这条图片候选？"
          dismissAllowed={(generation) =>
            generation.allowed_actions.includes("dismiss_history") &&
            onDismiss !== undefined
          }
        />
      ) : null}
      {open
        ? createPortal(
            <div className="scene-asset-picker-backdrop">
              <section
                className="scene-asset-picker-dialog reference-image-plan-dialog"
                role="dialog"
                aria-modal="true"
                aria-label={`规划其他图片 ${index + 1}`}
              >
                <h2>规划其他图片 {index + 1}</h2>
                <p>
                  只描述视觉参考所需内容，不指定视频起止时刻。保存规划后可生成候选；选择图片才会进入视频输入。
                </p>
                <label>
                  参考用途
                  <textarea
                    aria-label="参考图片用途"
                    value={draft.value.description}
                    maxLength={2000}
                    disabled={disabled}
                    onChange={(event) =>
                      draft.setValue((current) => ({
                        ...current,
                        description: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  画面正文
                  <textarea
                    aria-label="参考图片画面正文"
                    value={draft.value.prompt_text}
                    maxLength={18000}
                    disabled={disabled}
                    onChange={(event) =>
                      draft.setValue((current) => ({
                        ...current,
                        prompt_text: event.target.value,
                      }))
                    }
                  />
                </label>
                <fieldset>
                  <legend>可见角色与造型</legend>
                  {snapshot.reference_library.characters.map((character) => (
                    <div key={character.id}>
                      <label>
                        <input
                          type="checkbox"
                          checked={draft.value.visible_character_ids.includes(
                            character.id,
                          )}
                          disabled={disabled}
                          onChange={(event) =>
                            draft.setValue((current) => ({
                              ...current,
                              visible_character_ids: event.target.checked
                                ? [
                                    ...current.visible_character_ids,
                                    character.id,
                                  ]
                                : current.visible_character_ids.filter(
                                    (id) => id !== character.id,
                                  ),
                              character_references: event.target.checked
                                ? current.character_references
                                : current.character_references.filter(
                                    (item) =>
                                      item.character_id !== character.id,
                                  ),
                            }))
                          }
                        />
                        {character.name}
                      </label>
                      {draft.value.visible_character_ids.includes(
                        character.id,
                      ) ? (
                        <select
                          aria-label={`${character.name} 参考造型`}
                          disabled={disabled}
                          value={
                            draft.value.character_references.some(
                              (item) => item.character_id === character.id,
                            )
                              ? (draft.value.character_references.find(
                                  (item) => item.character_id === character.id,
                                )?.look_id ?? "__none")
                              : ""
                          }
                          onChange={(event) => {
                            if (event.target.value === "")
                              draft.setValue((current) => ({
                                ...current,
                                character_references:
                                  current.character_references.filter(
                                    (item) =>
                                      item.character_id !== character.id,
                                  ),
                              }));
                            else
                              setLook(
                                character.id,
                                event.target.value === "__none"
                                  ? null
                                  : event.target.value,
                              );
                          }}
                        >
                          <option value="">
                            {character.looks.length === 1
                              ? "默认造型"
                              : "请选择本图造型"}
                          </option>
                          <option value="__none">不提交该角色的造型图</option>
                          {character.looks.map((look) => (
                            <option key={look.id} value={look.id}>
                              {look.name}
                            </option>
                          ))}
                        </select>
                      ) : null}
                    </div>
                  ))}
                </fieldset>
                <p>显式生图参考：{draft.value.reference_asset_ids.length}/5</p>
                <button
                  className="secondary-button"
                  disabled={disabled}
                  onClick={() => setReferencesOpen(true)}
                >
                  选择生图参考
                </button>
                {draft.conflict ? (
                  <p role="alert">
                    规划已更新，当前草稿已保留；关闭后重读再保存。
                  </p>
                ) : null}
                <div>
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={
                      disabled ||
                      draft.conflict ||
                      !draft.value.prompt_text.trim() ||
                      !draft.value.description.trim()
                    }
                    onClick={() =>
                      onCommand?.("video.save_reference_image_plan", {
                        scope,
                        segment_id: segmentId,
                        slot_index: index,
                        ...draft.value,
                      })
                    }
                  >
                    保存规划
                  </button>
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => {
                      if (
                        !draft.dirty ||
                        window.confirm("关闭并放弃未保存的图片规划？")
                      ) {
                        draft.reset();
                        setOpen(false);
                      }
                    }}
                  >
                    关闭
                  </button>
                </div>
                {referencesOpen ? (
                  <MultiImageAssetPickerDialog
                    title="选择其他图片的生图参考"
                    ariaLabel="参考图片生图输入"
                    assets={snapshot.assets.filter((item) =>
                      item.media_type.startsWith("image/"),
                    )}
                    selectedAssetIds={draft.value.reference_asset_ids}
                    maxSelected={5}
                    busy={disabled}
                    onClose={() => setReferencesOpen(false)}
                    onChange={(assetIds) =>
                      draft.setValue((current) => ({
                        ...current,
                        reference_asset_ids: assetIds,
                      }))
                    }
                  />
                ) : null}
              </section>
            </div>,
            document.body,
          )
        : null}
    </article>
  );
}
