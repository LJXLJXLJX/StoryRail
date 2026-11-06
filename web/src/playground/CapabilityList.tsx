import type { PlaygroundCapabilityId, PlaygroundCapabilityInfo } from "../api";

const CAPABILITY_GROUPS = [
  { id: "image", label: "图像" },
  { id: "speech", label: "语音" },
  { id: "video", label: "视频" },
  { id: "audio", label: "音频" },
] as const;

export const UNAVAILABLE_HINT = "对应模型服务未配置。";

export function CapabilityList({
  capabilities,
  selected,
  onSelect,
}: {
  capabilities: PlaygroundCapabilityInfo[];
  selected: PlaygroundCapabilityId | null;
  onSelect: (id: PlaygroundCapabilityId) => void;
}) {
  return (
    <section className="playground-column" aria-label="能力列表">
      <h2>能力</h2>
      {CAPABILITY_GROUPS.map((group) => {
        const items = capabilities.filter((item) => item.group === group.id);
        return (
          <div className="playground-capability-group" key={group.label}>
            <strong>{group.label}</strong>
            {items.map((capability) => (
              <button
                key={capability.id}
                type="button"
                className={
                  selected === capability.id
                    ? "playground-capability-item is-active"
                    : "playground-capability-item"
                }
                disabled={!capability.available}
                title={capability.available ? undefined : UNAVAILABLE_HINT}
                onClick={() => onSelect(capability.id)}
              >
                {capability.label}
              </button>
            ))}
          </div>
        );
      })}
    </section>
  );
}
