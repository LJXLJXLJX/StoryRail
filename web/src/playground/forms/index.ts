import type { ComponentType } from "react";

import type { PlaygroundCapabilityId } from "../../api";
import { AudioEffectForm } from "./AudioEffectForm";
import { AudioRemixForm } from "./AudioRemixForm";
import { AudioTrimForm } from "./AudioTrimForm";
import { PanoViewForm } from "./PanoViewForm";
import { VideoExtractFrameForm } from "./VideoExtractFrameForm";
import type { CapabilityFormProps } from "./common";

export const CAPABILITY_FORMS: Partial<
  Record<PlaygroundCapabilityId, ComponentType<CapabilityFormProps> | null>
> = {
  "video.extract_frame": VideoExtractFrameForm,
  "image.pano_view": PanoViewForm,
  "audio.remix": AudioRemixForm,
  "audio.effect": AudioEffectForm,
  "audio.trim": AudioTrimForm,
};
