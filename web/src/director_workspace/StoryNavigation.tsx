import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import type { Scene } from "../api";
import type { StoryTarget } from "../api/projection";

export function StoryNavigation({
  scenes,
  title,
  target,
  timingConfirmed,
  onChoose,
  children,
}: {
  scenes: Scene[];
  title: string;
  target: StoryTarget | null;
  timingConfirmed: boolean;
  onChoose: (target: StoryTarget | null) => void;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const scene = scenes.find((item) => item.id === target?.sceneId);
  const shot = scene?.shots.find(
    (item) =>
      item.id === target?.id || item.segments.some((s) => s.id === target?.id),
  );
  const choose = (value: StoryTarget | null) => {
    onChoose(value);
    setOpen(false);
  };
  const duration = (seconds: number | null) => {
    if (!timingConfirmed || seconds === null) return "N/A";
    return `${seconds.toFixed(2).replace(/\.?0+$/, "")} 秒`;
  };
  const totalDuration = (values: number[]) =>
    values.length ? values.reduce((sum, value) => sum + value, 0) : null;
  useEffect(() => {
    setOpen(false);
  }, [target?.id]);
  return (
    <section className="story-reader" aria-label="故事工作台">
      <button
        className="story-navigation-toggle secondary-button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        故事位置
      </button>
      <nav
        className={`story-reader-nav ${open ? "is-mobile-open" : ""}`}
        aria-label="故事层级"
        onKeyDown={(event) => {
          if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
            const buttons = Array.from(
              (
                document.activeElement?.closest(
                  "[data-story-navigation-scope], .story-reader-column",
                ) ??
                event.currentTarget
              ).querySelectorAll<HTMLButtonElement>("button"),
            );
            const i = buttons.indexOf(
              document.activeElement as HTMLButtonElement,
            );
            const next =
              event.key === "Home"
                ? 0
                : event.key === "End"
                  ? buttons.length - 1
                  : Math.max(
                      0,
                      Math.min(
                        buttons.length - 1,
                        i + (event.key === "ArrowDown" ? 1 : -1),
                      ),
                    );
            buttons[next]?.focus();
            event.preventDefault();
          }
        }}
      >
        <p className="eyebrow">{title}</p>
        <button
          className="story-reader-back"
          aria-current={!target ? "page" : undefined}
          onClick={() => choose(null)}
        >
          项目概览
        </button>
        <div className="story-reader-columns is-expanded">
          <section
            className="story-reader-tree is-three-level"
            aria-label="场景、镜头与片段树"
          >
            <div className="story-reader-tree-head">
              <h2>场景</h2>
              <h2>连续镜头</h2>
              <h2>生成片段</h2>
            </div>
            <ol
              className="story-reader-tree-rows"
              data-story-navigation-scope
            >
              {scenes.map((s, sceneIndex) => (
                <li
                  className={`story-reader-scene-branch ${scene?.id === s.id ? "is-current-path" : ""}`}
                  key={s.id}
                >
                  <div className="story-reader-tree-parent story-reader-scene-node">
                    <button
                      aria-current={
                        target?.level === "scene" && scene?.id === s.id
                          ? "page"
                          : undefined
                      }
                      onClick={() =>
                        choose({ level: "scene", sceneId: s.id, id: s.id })
                      }
                    >
                      <small>
                        场景 {sceneIndex + 1} ·{" "}
                        {s.driver === "narration" ? "旁白" : "戏剧"}
                      </small>
                      <span>{s.title}</span>
                      <b aria-hidden="true">›</b>
                      <small className="story-reader-duration">
                        {duration(
                          totalDuration(
                            s.shots.flatMap((item) =>
                              item.segments.map(
                                (segment) => segment.duration_estimate_seconds,
                              ),
                            ),
                          ),
                        )}
                      </small>
                    </button>
                  </div>
                  <ol
                    className="story-reader-shot-branches"
                    aria-label={`场景 ${sceneIndex + 1} 的连续镜头`}
                  >
                    {s.shots.map((sceneShot, shotIndex) => (
                      <li
                        className={`story-reader-shot-branch ${shot?.id === sceneShot.id ? "is-current-path" : ""}`}
                        key={sceneShot.id}
                      >
                        <div className="story-reader-tree-parent story-reader-shot-node">
                          <button
                            aria-current={
                              target?.level === "shot" && shot?.id === sceneShot.id
                                ? "page"
                                : undefined
                            }
                            onClick={() =>
                              choose({
                                level: "shot",
                                sceneId: s.id,
                                id: sceneShot.id,
                              })
                            }
                          >
                            <small>
                              镜头 {shotIndex + 1} · {sceneShot.segments.length} 个片段
                            </small>
                            <span>{sceneShot.action}</span>
                            <b aria-hidden="true">›</b>
                            <small className="story-reader-duration">
                              {duration(
                                totalDuration(
                                  sceneShot.segments.map(
                                    (segment) => segment.duration_estimate_seconds,
                                  ),
                                ),
                              )}
                            </small>
                          </button>
                        </div>
                        <ol
                          className="story-reader-tree-children"
                          aria-label={`场景 ${sceneIndex + 1}－镜头 ${shotIndex + 1} 的生成片段`}
                        >
                          {sceneShot.segments.map((segment, segmentIndex) => (
                            <li key={segment.id}>
                              <button
                                aria-current={
                                  target?.id === segment.id ? "page" : undefined
                                }
                                onClick={() =>
                                  choose({
                                    level: "segment",
                                    sceneId: s.id,
                                    id: segment.id,
                                  })
                                }
                              >
                                <small>片段 {segmentIndex + 1}</small>
                                <span>{segment.action}</span>
                                <small className="story-reader-duration">
                                  {duration(segment.duration_estimate_seconds)}
                                </small>
                              </button>
                            </li>
                          ))}
                          {!sceneShot.segments.length ? (
                            <li className="story-reader-tree-empty">
                              <p>片段尚未规划</p>
                            </li>
                          ) : null}
                        </ol>
                      </li>
                    ))}
                    {!s.shots.length ? (
                      <li className="story-reader-shot-branch story-reader-tree-empty">
                        <p>镜头尚未规划</p>
                        <p>片段尚未规划</p>
                      </li>
                    ) : null}
                  </ol>
                </li>
              ))}
              {!scenes.length ? (
                <li className="story-reader-scene-branch story-reader-tree-empty">
                  <p>场景尚未规划</p>
                  <p>镜头尚未规划</p>
                  <p>片段尚未规划</p>
                </li>
              ) : null}
            </ol>
          </section>
        </div>
      </nav>
      <article className="story-reader-page">{children}</article>
    </section>
  );
}
