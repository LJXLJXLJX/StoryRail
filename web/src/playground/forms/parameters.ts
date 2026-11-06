// 逐能力的默认参数、wire 键集合与客户端校验。
// Core 仍会做权威校验；这里只用来禁用明显非法的提交（01 §6.2）。
import type { PlaygroundCapabilityId } from "../../api";
import { asAssetId, asNumber } from "./common";

export const AUDIO_EFFECT_PRESETS: Array<{ value: string; label: string }> = [
  { value: "walkie_talkie", label: "手持对讲机" },
  { value: "military_radio", label: "军用无线电" },
  { value: "weak_signal", label: "弱信号" },
  { value: "bad_signal", label: "信号不良" },
  { value: "dying_transmission", label: "逐渐中断" },
];

export function defaultParameters(
  capability: PlaygroundCapabilityId,
): Record<string, unknown> {
  switch (capability) {
    case "video.extract_frame":
      return { video_asset_id: null, frame_index: 0 };
    case "image.pano_view":
      return {
        image_asset_id: null,
        yaw_deg: 0,
        pitch_deg: 0,
        hfov_deg: 90,
        aspect_ratio: "16:9",
      };
    case "audio.remix":
      return {
        video_asset_id: null,
        voice_asset_id: null,
        background_asset_id: null,
        voice_gain_db: 0,
        background_gain_db: -6,
        voice_gain_start_seconds: null,
        voice_gain_end_seconds: null,
        background_gain_start_seconds: null,
        background_gain_end_seconds: null,
      };
    case "audio.effect":
      return {
        audio_asset_id: null,
        preset: "weak_signal",
        strength: 0.7,
        seed: 42,
        start_seconds: null,
        end_seconds: null,
      };
    case "audio.trim":
      return { audio_asset_id: null, start_seconds: 0, end_seconds: 0 };
  }
  return {};
}

/** 提交前构造完整参数对象：所有键都出现，可空的键显式传 null。 */
export function completeParameters(
  capability: PlaygroundCapabilityId,
  values: Record<string, unknown>,
): Record<string, unknown> {
  const merged: Record<string, unknown> = {
    ...defaultParameters(capability),
    ...values,
  };
  return merged;
}

function requireAsset(value: unknown, label: string): string | null {
  return asAssetId(value) === null ? `请为${label}选择素材。` : null;
}

function requireWindow(
  start: unknown,
  end: unknown,
  label: string,
): string | null {
  const from = typeof start === "number" ? start : null;
  const to = typeof end === "number" ? end : null;
  if (from === null && to === null) return null;
  if (from === null || to === null) return `${label}的起止时间必须同时填写。`;
  return from >= 0 && from < to ? null : `${label}必须满足 0 ≤ 起点 < 终点。`;
}

export function parametersError(
  capability: PlaygroundCapabilityId,
  values: Record<string, unknown>,
): string | null {
  switch (capability) {
    case "video.extract_frame":
      return (
        requireAsset(values.video_asset_id, "视频") ??
        (Number.isInteger(values.frame_index) && Number(values.frame_index) >= 0
          ? null
          : "帧号必须是非负整数。")
      );
    case "image.pano_view":
      // 角度范围由 Core 按生产全景裁切契约校验，这里只拦截缺素材与非数字。
      return (
        requireAsset(values.image_asset_id, "全景") ??
        (["yaw_deg", "pitch_deg", "hfov_deg"].every(
          (key) =>
            typeof values[key] === "number" &&
            Number.isFinite(values[key] as number),
        )
          ? null
          : "yaw、pitch、hfov 必须是数字。")
      );
    case "audio.remix": {
      const gain = (value: unknown, label: string) => {
        const number = asNumber(value, 0);
        return number < -100 || number > 24
          ? `${label}必须在 -100 到 24 dB 之间。`
          : null;
      };
      return (
        requireAsset(values.video_asset_id, "视频") ??
        requireAsset(values.voice_asset_id, "人声") ??
        requireAsset(values.background_asset_id, "背景声") ??
        gain(values.voice_gain_db, "人声增益") ??
        gain(values.background_gain_db, "背景增益") ??
        requireWindow(
          values.voice_gain_start_seconds,
          values.voice_gain_end_seconds,
          "人声增益区间",
        ) ??
        requireWindow(
          values.background_gain_start_seconds,
          values.background_gain_end_seconds,
          "背景增益区间",
        )
      );
    }
    case "audio.effect": {
      const strength = asNumber(values.strength, 0);
      return (
        requireAsset(values.audio_asset_id, "音频") ??
        (strength < 0 || strength > 1 ? "强度必须在 0 到 1 之间。" : null) ??
        requireWindow(values.start_seconds, values.end_seconds, "处理区间")
      );
    }
    case "audio.trim": {
      const start = asNumber(values.start_seconds, 0);
      const end = asNumber(values.end_seconds, 0);
      if (start < 0) return "截取起点不能小于 0。";
      return start < end ? null : "截取必须满足起点 < 终点。";
    }
  }
  return null;
}

/** 常用水平朝向：全景正中为 0°，顺时针为正。 */
export const PANO_YAW_PRESETS: Array<{ label: string; yaw: number }> = [
  { label: "正前", yaw: 0 },
  { label: "右", yaw: 90 },
  { label: "后", yaw: 180 },
  { label: "左", yaw: 270 },
];

export const PANO_HFOV_PRESETS = [60, 90];

/**
 * 一次提交多组参数的批量预设：Web 依次调用 submit_run，Core 没有批量接口。
 * 返回 null 表示该能力没有批量预设。
 */
export function batchVariants(
  capability: PlaygroundCapabilityId,
  values: Record<string, unknown>,
): { label: string; variants: Array<Record<string, unknown>> } | null {
  if (capability !== "image.pano_view") return null;
  const base = completeParameters(capability, values);
  return {
    label: "四个方向依次裁切",
    variants: PANO_YAW_PRESETS.map(({ yaw }) => ({ ...base, yaw_deg: yaw })),
  };
}
