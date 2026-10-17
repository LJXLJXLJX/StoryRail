import type { Scene } from "../api";
export function newSceneDraft(): Scene {
  const token = () => `new:${crypto.randomUUID()}`;
  return {
    id: token(),
    title: "新场景",
    driver: "drama",
    location_id: null,
    state_id: null,
    summary: "请补充这个场景发生的关键事件。",
    setting: "请补充本 Scene 的时间、空间和环境条件。",
    narration_cues: [],
    shots: [
      {
        id: token(),
        visible_character_ids: [],
        composition: "请补充画面构图。",
        camera_movement: "固定机位。",
        action: "请补充镜头内发生的动作。",
        audio_direction: "",
        transition_in: null,
        view_id: null,
        segments: [
          {
            id: token(),
            duration_estimate_seconds: 3,
            action: "请补充这一段的连续动作。",
            dialogue_lines: [],
            boundary_from_previous: null,
          },
        ],
      },
    ],
  };
}
