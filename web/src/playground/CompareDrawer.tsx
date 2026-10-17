import { useRef } from "react";
import { ZoomableImage } from "../ImagePreview";

import type { PlaygroundAsset, PlaygroundRun } from "../api";
import { assetById, formatParameterValue } from "./RunCard";

function differingKeys(runs: PlaygroundRun[]): string[] {
  const keys = new Set<string>();
  for (const run of runs) {
    for (const key of Object.keys(run.parameters)) keys.add(key);
  }
  return [...keys]
    .filter((key) => {
      const values = new Set(
        runs.map((run) => JSON.stringify(run.parameters[key] ?? null)),
      );
      return values.size > 1;
    })
    .sort();
}

export function CompareDrawer({
  runs,
  assets,
  onClose,
}: {
  runs: PlaygroundRun[];
  assets: PlaygroundAsset[];
  onClose: () => void;
}) {
  const panel = useRef<HTMLElement>(null);
  const keys = differingKeys(runs);
  return (
    <div className="playground-compare-drawer" role="presentation">
      <section
        className="playground-compare-panel"
        role="dialog"
        aria-label="对比所选实验"
        ref={panel}
      >
        <header className="playground-run-head">
          <h2>对比所选（{runs.length}）</h2>
          <span />
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              panel.current?.querySelectorAll("video").forEach((video) => {
                video.currentTime = 0;
                if (typeof video.play === "function") void video.play();
              });
            }}
          >
            同步播放
          </button>
          <button type="button" className="secondary-button" onClick={onClose}>
            关闭
          </button>
        </header>
        <div
          className="playground-compare-grid"
          style={{ gridTemplateColumns: `repeat(${runs.length}, minmax(0, 1fr))` }}
        >
          {runs.map((run) => {
            const output = assetById(assets, run.output_asset_id);
            return (
              <article key={run.id}>
                <strong>{run.capability_label}</strong>
                <p className="playground-wire-key">{run.id.slice(0, 8)}</p>
                {output === null ? (
                  <p className="playground-hint">
                    {run.output_asset_id === null
                      ? "没有产物。"
                      : "产物已从 Playground 资产库删除。"}
                  </p>
                ) : output.media_type.startsWith("image/") ? (
                  <ZoomableImage src={output.content_url} alt={`${run.capability_label}产物`} />
                ) : output.media_type === "audio/wav" ? (
                  <audio controls preload="none" src={output.content_url} />
                ) : (
                  <video controls preload="none" src={output.content_url} />
                )}
              </article>
            );
          })}
        </div>
        {keys.length === 0 ? (
          <p className="playground-hint">所选实验的参数取值完全相同。</p>
        ) : (
          <table className="playground-diff-table">
            <thead>
              <tr>
                <th scope="col">参数</th>
                {runs.map((run) => (
                  <th scope="col" key={run.id}>
                    {run.capability_label} · {run.id.slice(0, 8)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {keys.map((key) => {
                const rendered = runs.map((run) =>
                  formatParameterValue(run.parameters[key], assets),
                );
                return (
                  <tr key={key}>
                    <th scope="row">{key}</th>
                    {rendered.map((value, index) => (
                      <td
                        key={runs[index].id}
                        className={
                          new Set(rendered).size > 1 ? "is-different" : undefined
                        }
                      >
                        {value}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
