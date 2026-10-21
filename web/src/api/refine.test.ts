import { expect, it } from "vitest";
import { editableScenePayload, refineGeneration } from "./refine";
import type { Scene } from "./types";

const SHOT_A = "1".repeat(32);
const SHOT_B = "2".repeat(32);
const SEGMENT_A = "3".repeat(32);
const SEGMENT_B = "4".repeat(32);

function existingScene(): Scene {
    return {
        id: "5".repeat(32),
        location_id: null,
        state_id: null,
        driver: "drama",
        title: "站台",
        summary: "小满等待末班车。",
        setting: "傍晚站台。",
        shots: [
            {
                id: SHOT_A,
                visible_character_ids: [],
                composition: "中景。",
                camera_movement: "固定。",
                action: "抬头。",
                audio_direction: "风声。",
                transition_in: null,
            },
            {
                id: SHOT_B,
                visible_character_ids: [],
                composition: "近景。",
                camera_movement: "推近。",
                action: "低头。",
                audio_direction: "",
                transition_in: null,
            },
        ],
        segments: [
            {
                id: SEGMENT_A,
                shot_ids: [SHOT_A, SHOT_B],
                duration_estimate_seconds: 6,
                action: "段内切镜。",
                dialogue_lines: [],
                boundary_from_previous: null,
            },
            {
                id: SEGMENT_B,
                shot_ids: [SHOT_B],
                duration_estimate_seconds: 3,
                action: "延续镜头。",
                dialogue_lines: [],
                boundary_from_previous: {
                    reason: "continuity_anchor",
                    continuity_instruction: "延续低头姿态。",
                },
            },
        ],
        narration_cues: [],
    };
}

it("整卡保存提交 v33 形状：Shot 无 segments，Segment 用 shot_indexes", () => {
    const payload = editableScenePayload(existingScene());
    expect(payload.shots).toHaveLength(2);
    expect(payload.shots.every((shot) => !("segments" in shot))).toBe(true);
    expect(payload.segments.map((segment) => segment.shot_indexes)).toEqual([[0, 1], [1]]);
    expect(payload.segments.map((segment) => segment.id)).toEqual([SEGMENT_A, SEGMENT_B]);
    expect(payload.narration_cues).toEqual([]);
});

it("新 Scene 草稿把临时 ID 归为 null，覆盖用序号保持", () => {
    const scene = existingScene();
    scene.id = "new:scene";
    scene.shots = scene.shots.map((shot) => ({ ...shot, id: `new:${shot.id}` }));
    scene.segments = scene.segments.map((segment) => ({
        ...segment,
        id: `new:${segment.id}`,
        shot_ids: segment.shot_ids.map((shotId) => `new:${shotId}`),
    }));
    const payload = editableScenePayload(scene);
    expect(payload.id).toBeNull();
    expect(payload.shots.map((shot) => shot.id)).toEqual([null, null]);
    expect(payload.segments.map((segment) => segment.id)).toEqual([null, null]);
    expect(payload.segments.map((segment) => segment.shot_indexes)).toEqual([[0, 1], [1]]);
});

it("视频参考图片的 63 位 seed 保持十进制字符串", () => {
    expect(refineGeneration({kind: "video_reference_image", seed: "9007199254740993"})).toBe(true);
    expect(refineGeneration({kind: "video_reference_image", seed: 123})).toBe(false);
});
