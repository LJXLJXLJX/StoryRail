import { expect, it } from "vitest";
import fixture from "../test/mixed_approval_fixture.json";
import {
  isFinalAssemblyPlan,
  parseError,
  parseReferenceLibraryProposal,
  parseStructuredDirectorSnapshot,
} from "./validation";
it("接纳 Core 混合生产审批响应的跨 Scene 硬切计划", () => {
    expect(isFinalAssemblyPlan(fixture.final_assembly)).toBe(true);
    expect(() => parseStructuredDirectorSnapshot(fixture)).not.toThrow();
    expect(parseStructuredDirectorSnapshot(fixture).workflow.semantics.current_stage)
        .toBe("primary_workflow_focus_not_capability_lock");
    expect(fixture.final_assembly.clips.map(clip => clip.transition_from_previous))
        .toEqual([null, null]);
});
it("仍拒绝首段接缝、未知转场与 Segment 级旧计划", () => {
    for (const [index, transition] of [[0, "seam_blend"], [1, "dissolve"]] as const) {
        const invalid = structuredClone(fixture.final_assembly) as unknown as {
            clips: Record<string, unknown>[];
        };
        invalid.clips[index].transition_from_previous = transition;
        expect(isFinalAssemblyPlan(invalid)).toBe(false);
    }
    const missing = structuredClone(fixture.final_assembly) as unknown as {
        clips: Record<string, unknown>[];
    };
    delete missing.clips[1].transition_from_previous;
    expect(isFinalAssemblyPlan(missing)).toBe(false);
    const legacy = structuredClone(fixture.final_assembly) as unknown as {
        clips: Record<string, unknown>[];
    };
    legacy.clips[0].segment_id = legacy.clips[0].scene_id;
    delete legacy.clips[0].scene_id;
    expect(isFinalAssemblyPlan(legacy)).toBe(false);
});
it("拒绝旧式字符串 next action，避免 Web 猜测动作参数", () => {
    const invalid = structuredClone(fixture) as unknown as Record<string, unknown>;
    const workflow = invalid.workflow as Record<string, unknown>;
    workflow.required_next_actions = ["candidate_selection"];
    expect(() => parseStructuredDirectorSnapshot(invalid)).toThrow();
});
it("接纳 Core 扩展错误诊断字段并保留用户可读消息", () => {
    expect(parseError({
        error: {
            code: "invalid_request",
            message: "start_shot_id 不合法。",
            recoverable: false,
            origin: "core_parser",
            state_changed: false,
            retry_policy: "fix_arguments_and_retry",
            automatic_retry_allowed: false,
        },
    })).toEqual({
        error: {
            code: "invalid_request",
            message: "start_shot_id 不合法。",
            recoverable: false,
            origin: "core_parser",
            state_changed: false,
            retry_policy: "fix_arguments_and_retry",
            automatic_retry_allowed: false,
        },
    });
});
it("生成的 proposal 解析器接受声明过的引用库并拒绝多余字段", () => {
    const valid = {
        characters: [{
            name: "甲", visual_description: "外形", voice_description: "声音",
            looks: [{ name: "日常", appearance: "蓝色外套", usage: "全片" }],
        }],
        narrator: null,
    };
    expect(parseReferenceLibraryProposal(valid)).toEqual(valid);
    expect(() => parseReferenceLibraryProposal({ ...valid, extra: true })).toThrow();
});
it("读取 revision 冲突详情，仍拒绝未声明错误字段", () => {
    const conflict = {
        error: {
            code: "revision_conflict", message: "项目已更新。", recoverable: true,
            origin: "core_state", state_changed: false, retry_policy: "refresh_state_and_retry",
            automatic_retry_allowed: false, expected_revision: 7, current_revision: 8,
        },
    };
    expect(parseError(conflict)).toEqual(conflict);
    expect(() => parseError({ error: { ...conflict.error, surprise: true } })).toThrow();
});
