import { useEffect, useState } from "react";

import type { VideoFrameInfo } from "../../director_workspace/shared";
import { playgroundApi } from "../api";
import {
  AssetSlot,
  Field,
  asAssetId,
  asNumber,
  numberOrZero,
  type CapabilityFormProps,
} from "./common";

export function VideoExtractFrameForm({
  values,
  onChange,
  disabled,
}: CapabilityFormProps) {
  const videoAssetId = asAssetId(values.video_asset_id);
  const [info, setInfo] = useState<VideoFrameInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (videoAssetId === null) {
      setInfo(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setInfo(null);
    setError(null);
    void playgroundApi.videoFrameInfo(videoAssetId).then(
      (loaded) => {
        if (cancelled) return;
        setInfo(loaded);
        // 默认最后一帧；范围是 0..N-1（01 §12.3）。
        onChange({ ...values, frame_index: loaded.frame_count - 1 });
      },
      (reason: unknown) => {
        if (!cancelled) {
          setError(
            reason instanceof Error ? reason.message : "无法读取视频帧数。",
          );
        }
      },
    );
    return () => {
      cancelled = true;
    };
    // 只在视频变化时读取一次帧数。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoAssetId]);
  const last = info === null ? null : info.frame_count - 1;
  return (
    <div className="playground-form">
      <AssetSlot
        label="视频"
        wireKey="video_asset_id"
        assetId={videoAssetId}
        kind="video"
        disabled={disabled}
        onChange={(video_asset_id) => onChange({ ...values, video_asset_id })}
      />
      <Field
        label="帧号"
        wireKey="frame_index"
        hint={info === null ? undefined : `共 ${info.frame_count} 帧`}
      >
        <input
          type="number"
          aria-label="帧号"
          min={0}
          max={last ?? undefined}
          value={String(asNumber(values.frame_index, 0))}
          disabled={disabled || info === null}
          onChange={(event) =>
            onChange({ ...values, frame_index: numberOrZero(event.target.value) })
          }
        />
      </Field>
      {error === null ? null : (
        <p className="playground-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
