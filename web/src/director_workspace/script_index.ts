import type { Scene, Shot, ShotSegment } from "../api";

/** 覆盖该 Shot 的 Segment（按顺序）；一个 Shot 可跨多个相邻 Segment。 */
export function shotSegments(scene: Scene, shotId: string): ShotSegment[] {
  return scene.segments.filter((segment) => segment.shot_ids.includes(shotId));
}

/** Segment 覆盖的 Shot（按顺序）；一个 Segment 可在段内切多个 Shot。 */
export function segmentShots(scene: Scene, segment: ShotSegment): Shot[] {
  return segment.shot_ids.flatMap((id) => scene.shots.filter((shot) => shot.id === id));
}

/** 导航与标题用的覆盖标签：“镜头 1–2”，与上一段共享边界 Shot 时附“（续）”。 */
export function segmentShotLabel(scene: Scene, segment: ShotSegment): string {
  const numbers = segment.shot_ids.map((id) => shotNumber(scene, id));
  const range =
    numbers.length > 1 ? `${numbers[0]}–${numbers[numbers.length - 1]}` : `${numbers[0]}`;
  return `镜头 ${range}${segmentContinuesFromPrevious(scene, segment) ? "（续）" : ""}`;
}

export function shotNumber(scene: Scene, shotId: string): number {
  return scene.shots.findIndex((shot) => shot.id === shotId) + 1;
}

export function shotLabel(scene: Scene, shotId: string): string {
  return `镜头 ${shotNumber(scene, shotId)}`;
}

/** D5：相邻 Segment 共享边界 Shot（前一段最后一个 = 后一段第一个）即延续同一镜头。 */
export function segmentContinuesFromPrevious(
  scene: Scene,
  segment: ShotSegment,
): boolean {
  const index = scene.segments.indexOf(segment);
  const previous = index > 0 ? scene.segments[index - 1] : undefined;
  return previous?.shot_ids.at(-1) === segment.shot_ids[0];
}

export function findSegmentScene(
  scenes: Scene[],
  segmentId: string,
): Scene | undefined {
  return scenes.find((scene) => scene.segments.some((segment) => segment.id === segmentId));
}
