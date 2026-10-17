import { videoFixture } from "./test/video_fixture";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App, FloatingErrorNotice, summarizeGenerationProgress } from "./App";
import {
  structuredDirectorApi,
  type ReferenceGeneration,
  type StructuredDirectorSnapshot,
} from "./api";
import { creativePartnerPrompt, directorPlanConvertPrompt } from "./creativePrompts";
const projectId = "0123456789abcdef0123456789abcdef";
const directorPlan = "# 完整导演方案\n\n小满在雨夜等待末班车。";
const project = {
  id: projectId,
  title: "雨夜末班车",
  aspect_ratio: "16:9",
  updated_at: "2026-08-27T12:00:00Z",
  status: "active",
};
const awaitingSnapshot = snapshot("awaiting_reference_proposal", []);
const reviewingSnapshot = snapshot("reviewing_references", [
  "edit_reference_library",
  "import_image_asset",
]);
describe("StoryRail App", () => {
  it.each([
    ["voice.wav", "audio/x-wav", "audio/wav"],
    ["clip.mp4", "", "video/mp4"],
  ])("导入媒体时将 %s 规范为 Core 支持的 MIME", async (name, sourceType, expectedType) => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response(reviewingSnapshot),
    );
    const file = new File(["media"], name, { type: sourceType });
    await structuredDirectorApi.importMediaAsset(projectId, 7, file);
    expect(fetcher).toHaveBeenCalledWith(
      `/api/projects/${projectId}/structured-director/assets/media?expected_revision=7&filename=${name}`,
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": expectedType },
        body: file,
      }),
    );
  });
  it.each(["awaiting_reference_proposal", "reviewing_references", "reviewing_videos", "reviewing_final"])("%s 阶段均在 Logo 旁提供只打开 Agent 的命令", async (status) => {
    const current = status === "reviewing_videos" || status === "reviewing_final"
      ? productionSnapshot({ status }) : snapshot(status, []);
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (String(url) === "/api/projects") return response({ projects: [project] });
      if (String(url) === "/api/local-connection") return response({ cwd: "/StoryRail", command_prefix: "python -m integrations.agent_launcher" });
      return response(current);
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    const trigger = await screen.findByRole("button", { name: "连接 Agent" });
    expect(trigger.closest(".brand-and-agent")).toHaveTextContent("StoryRail");
    const callsBeforeOpening = fetcher.mock.calls.length;
    fireEvent.click(trigger);
    fireEvent.change(screen.getByRole("combobox", { name: "你使用什么 Agent？" }), { target: { value: "pi" } });
    expect(await screen.findByRole("textbox", { name: "启动命令" })).toHaveValue(
      `cd '/StoryRail' && python -m integrations.agent_launcher --agent pi --project '${projectId}'`,
    );
    expect(screen.getByText("你可以询问当前应该做什么。")).toBeInTheDocument();
    expect(fetcher.mock.calls.slice(callsBeforeOpening)).toEqual([["/api/local-connection"]]);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(trigger).toHaveFocus();
    expect(screen.queryByRole("textbox", { name: "启动命令" })).not.toBeInTheDocument();
  });
  it("生产阶段可从全局引用确认审核并刷新同 revision workflow", async () => {
    const current = productionSnapshot() as StructuredDirectorSnapshot;
    current.workflow.current_stage = "reference_library";
    current.workflow.stage_status = "awaiting_human_review";
    current.workflow.required_next_actions = [
      {
        action: "reference.confirm_review",
        tool: null,
        target_ids: [],
        human_only: true,
        requires_explicit_user_request: false,
      },
    ];
    const refreshed = structuredClone(current);
    refreshed.workflow.current_stage = "narration";
    refreshed.workflow.stage_status = "ready";
    refreshed.workflow.required_next_actions = [];
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ projects: [project] }))
      .mockResolvedValueOnce(response(current))
      .mockResolvedValueOnce(response({ receipt: { status: "succeeded" } }))
      .mockResolvedValueOnce(response(refreshed));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    fireEvent.click(await screen.findByRole("button", { name: "引用库" }));
    const dialog = screen.getByRole("dialog", { name: "全局引用" });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "完成审核并继续" }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "全局引用" })).not.toBeInTheDocument(),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `/api/projects/${projectId}/structured-director/commands`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          name: "reference.confirm_review",
          expected_revision: current.revision,
          idempotency_key: `reference-review-${current.revision}`,
          arguments: {},
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      `/api/projects/${projectId}/structured-director`,
      undefined,
    );
  });
  it("旁白时长无法自动校准时只展示 Core 原因，不再提供人工确认时序按钮", async () => {
    const current = productionSnapshot() as StructuredDirectorSnapshot;
    current.workflow.current_stage = "narration";
    current.workflow.stage_status = "needs_attention";
    current.workflow.required_next_actions = [
      {
        action: "script.apply_operations",
        tool: "edit_script",
        target_ids: [],
        human_only: false,
        requires_explicit_user_request: true,
        purpose: "fix_narration_timing_conflict",
        reason: "narration_timing_conflict",
        message: "Drama Scene 的 Shot 时长不足以容纳旁白；请调整 Shot，不能自动重排表演。",
      },
    ];
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ projects: [project] }))
      .mockResolvedValueOnce(response(current));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    expect(
      await screen.findByRole("alert", { name: "旁白时长冲突" }),
    ).toHaveTextContent("Drama Scene 的 Shot 时长不足以容纳旁白");
    expect(
      screen.queryByRole("button", { name: "确认当前旁白与时长" }),
    ).not.toBeInTheDocument();
  });
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    window.sessionStorage.clear();
    Element.prototype.scrollIntoView = vi.fn();
    window.scrollTo = vi.fn();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  it("把操作失败显示为可关闭的固定悬浮提示", () => {
    const onDismiss = vi.fn();
    render(
      <FloatingErrorNotice
        message="该 Segment 已激活的尾帧尚未选择图片。"
        onDismiss={onDismiss}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveClass("floating-error-notice");
    expect(alert).toHaveTextContent("该 Segment 已激活的尾帧尚未选择图片。");
    fireEvent.click(screen.getByRole("button", { name: "关闭错误提示" }));
    expect(onDismiss).toHaveBeenCalledOnce();
  });
  it("生产期对白保存成功后悬浮提醒同步对应 视频提示词", async () => {
    const segmentId = "3".repeat(32);
    const scene = {
      id: "1".repeat(32),
      title: "场景",
      summary: "摘要",
      setting: "室内",
      driver: "drama",
      location_id: null,
      state_id: null,
      narration_cues: [],
      shots: [
        {
          id: "2".repeat(32),
          visible_character_ids: ["b".repeat(32)],
          composition: "中景",
          camera_movement: "固定",
          action: "人物停下",
          audio_direction: "环境声",
          transition_in: null,
          view_id: null,
        }],
      segments: [{ shot_ids: ["2".repeat(32)],
              id: segmentId,
              duration_estimate_seconds: 4,
              action: "人物回答",
              dialogue_lines: [
                {
                  character_id: "b".repeat(32),
                  speaker_label: null,
                  text: "原对白",
                  delivery: "平静",
                },
              ],
              boundary_from_previous: null,
            }],
    };
    const current = {
      ...reviewingSnapshot,
      status: "reviewing_videos",
      revision: 8,
      workspace_layers: {
        ...reviewingSnapshot.workspace_layers,
        narration_unlocked: true,
        keyframes_unlocked: true,
        videos_unlocked: true,
      },
      allowed_actions: ["edit_script"],
      reference_library: {
        ...reviewingSnapshot.reference_library,
        characters: [
          {
            id: "b".repeat(32),
            name: "Comi",
            visual_description: "短发",
            voice_description: "平静",
            voice_reference_asset_id: null,
            looks: [],
          },
        ],
      },
      director_script: {
        revision: 4,
        source_reference_revision: 1,
        production_baseline_revision: 4,
        production_baseline_scenes: [scene],
        scenes: [scene],
      },
      video_plan: {
        source_script_revision: 4,
        segments: [
          videoFixture({segment_id: segmentId,prompt_text: "旧 视频提示词",selected_asset_id: null,upscaled_asset_id: null,active_recipe: "minimax_h3.ref2va", recipes: {["minimax_h3.ref2va"]: {bindings: {additional_images: [],reference_audios: [],reference_videos: []}, params: {}}}}),
        ],
      },
    };
    const updated = structuredClone(current);
    updated.revision += 1;
    updated.director_script.revision += 1;
    updated.director_script.scenes[0].segments[0].dialogue_lines[0].text =
      "新对白";
    updated.video_plan.source_script_revision += 1;
    updated.video_plan.segments[0].prompt_text = "";
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ projects: [project] }))
      .mockResolvedValueOnce(response(current))
      .mockResolvedValueOnce(response(updated));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    fireEvent.click(await screen.findByRole("button", { name: /场景 1 ·/ }));
    const navigation=screen.getByRole("navigation",{name:"故事层级"});
    fireEvent.click(within(within(navigation).getByRole("list",{name:"场景 1 的生成片段"})).getByRole("button",{name:/片段 1/}));
    const h3Prompt = await screen.findByLabelText("当前 视频提示词");
    expect(h3Prompt).toHaveAttribute("readonly");
    fireEvent.click(screen.getByRole("button", { name: "编辑这一段" }));
    fireEvent.change(screen.getByLabelText("对白 *"), {
      target: { value: "新对白" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存脚本修改" }));
    const notice = await screen.findByRole("complementary", { name: "内容修改提醒" });
    expect(notice).toHaveTextContent("可能造成相关上下层内容不一致");
    expect(notice).toHaveTextContent("请同步手动修改或使用“优化视频提示词”");
    expect(notice).toHaveTextContent("scene01-seg01");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    fireEvent.click(screen.getByRole("button", { name: "关闭提醒" }));
    expect(screen.queryByText(/请同步手动修改/)).not.toBeInTheDocument();
  });
  it("按 TTS、图片和视频汇总未隐藏 Generation 进度", () => {
    const progress = summarizeGenerationProgress([
      generation("narration_audio", "succeeded"),
      generation("keyframe_image", "running"),
      generation("location_master_image", "failed"),
      generation("segment_video", "queued"),
      generation("video_upscale", "cancelled"),
      { ...generation("character_look_sheet", "succeeded"), dismissed: true },
    ]);
    expect(progress.tts).toEqual({
      finished: 1,
      total: 1,
      succeeded: 1,
      active: 0,
      failed: 0,
    });
    expect(progress.image).toEqual({
      finished: 1,
      total: 2,
      succeeded: 0,
      active: 1,
      failed: 1,
    });
    expect(progress.video).toEqual({
      finished: 1,
      total: 2,
      succeeded: 0,
      active: 1,
      failed: 1,
    });
  });
  it("自动观察使用项目级批量接口避免 Generation 队头阻塞", async () => {
    const activeSnapshot = {
      ...reviewingSnapshot,
      generations: [
        {
          ...generation("keyframe_image", "running"),
          id: "a".repeat(32),
          duration_seconds: null,
        },
        {
          ...generation("segment_video", "queued"),
          id: "d".repeat(32),
          duration_seconds: 2,
        },
      ],
    };
    const completedSnapshot = {
      ...activeSnapshot,
      revision: activeSnapshot.revision + 2,
      generations: activeSnapshot.generations.map((item, index) => ({
        ...item,
        phase: "succeeded" as const,
        progress: 1,
        output_asset_id: (index === 0 ? "c" : "e").repeat(32),
      })),
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ projects: [project] }))
      .mockResolvedValueOnce(response(activeSnapshot))
      // 轮询 interval 与自动观察 timeout 同在 1250ms：fake timers 下 interval 的
      // promise 链先结算，若它返回"已完成"快照会清掉观察 timeout。让它先拿到
      // 仍进行中的快照（revision 相同、状态不变、timeout 不被清），refresh 才会发起。
      .mockResolvedValueOnce(response(activeSnapshot))
      .mockResolvedValueOnce(response(completedSnapshot));
    vi.useFakeTimers();
    try {
      render(<App />);
      // 初次渲染只依赖 fetch mock 的 promise（microtask），act 冲刷即可。
      await act(async () => {});
      fireEvent.click(screen.getByRole("button", { name: "打开" }));
      await act(async () => {});
      // 自动观察在 1250ms 后触发项目级批量 refresh；fake timers 直接推进。
      await act(async () => { await vi.advanceTimersByTimeAsync(1300); });
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/projects/${projectId}/structured-director/generations/refresh`,
        expect.objectContaining({ method: "POST", body: "{}" }),
      );
    } finally {
      vi.useRealTimers();
    }
  });
  it("采样进度不推进 revision 时也自动更新视频进度卡", async () => {
    const sceneId = "1".repeat(32);
    const segmentId = "3".repeat(32);
    // Core 的采样进度是 UI-only 观察：revision 不变，只有 progress/message 前进。
    const running = {
      ...productionSnapshot(),
      generations: [
        {
          ...generation("segment_video", "running"),
          id: "a".repeat(32),
          target_id: segmentId,
          progress: 0.2,
          message: "H3 REF2VA 扩散采样 2/20 · 本步 5.00 s/iter · 采样预计剩余 90 秒。",
          duration_seconds: 10,
          allowed_actions: ["cancel"],
        },
      ],
    } as unknown as StructuredDirectorSnapshot;
    const advanced = structuredClone(running);
    advanced.generations[0].progress = 0.42;
    advanced.generations[0].message =
      "H3 REF2VA 扩散采样 6/20 · 本步 25.18 s/iter · 采样预计剩余 342 秒。";
    expect(advanced.revision).toBe(running.revision);
    window.sessionStorage.setItem(
      `story-reader:${projectId}`,
      JSON.stringify({ level: "segment", id: segmentId, sceneId }),
    );
    try {
      const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url === "/api/projects") return response({ projects: [project] });
        if (url === "/api/local-connection")
          return response({ cwd: "/StoryRail", command_prefix: "python -m integrations.agent_launcher" });
        if (url.endsWith("/generations/refresh")) return response(advanced);
        return response(running);
      });
      render(<App />);
      fireEvent.click(await screen.findByRole("button", { name: "打开" }));
      expect(await screen.findByText("20%")).toBeInTheDocument();
      // 自动观察间隔 1250ms；同 revision 的采样观察必须直接落到进度卡。
      await waitFor(
        () => expect(screen.getByText("42%")).toBeInTheDocument(),
        { timeout: 4000 },
      );
      expect(screen.getByText(/扩散采样 6\/20/)).toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/projects/${projectId}/structured-director/generations/refresh`,
        expect.objectContaining({ method: "POST", body: "{}" }),
      );
    } finally {
      window.sessionStorage.clear();
    }
  }, 15000);
  it("接受空提示词的地点主图计划，但仍拒绝非文本提示词", async () => {
    const plan = {
      allowed_actions: ["create_location"],
      locations: [
        {
          id: "c".repeat(32),
          name: "项目地点",
          kind: "exterior",
          description: "",
          allowed_actions: ["edit"],
          fixtures: [],
          key_light: null,
          master: {
            prompt_text: "", reference_asset_ids: [], selected_asset_id: null,
            production: {
              status: "blocked", status_label: "被阻止", reason: "请填写主图提示词。",
              generation_step: "master", generate_label: "生成主图", active_generation_id: null,
              candidate_generation_ids: [], selectable_generation_ids: [], allowed_actions: ["edit"],
            },
          },
          calibrated_master_asset_id: null,
          states: [],
          views: [],
        },
      ],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      response({
        ...reviewingSnapshot,
        location_library: plan,
      }),
    );
    const restored = await structuredDirectorApi.get(projectId);
    expect(restored.location_library.locations[0].master.prompt_text).toBe("");
    fetchMock.mockResolvedValueOnce(
      response({
        ...reviewingSnapshot,
        location_library: {
          ...plan,
          locations: [
            {
              ...plan.locations[0],
              master: { ...plan.locations[0].master, prompt_text: null },
            },
          ],
        },
      }),
    );
    await expect(structuredDirectorApi.get(projectId)).rejects.toThrow(
      "地点库格式不合法",
    );
  });
  it("接受 Director 运行中保留的 Keyframe、视频和成片计划", async () => {
    const startId = "1".repeat(32);
    const endId = "2".repeat(32);
    const segmentId = "3".repeat(32);
    const sceneId = "4".repeat(32);
    const shotId = "5".repeat(32);
    const visualSnapshot = {
      ...reviewingSnapshot,
      status: "reviewing_videos",
      workspace_layers: {
        ...reviewingSnapshot.workspace_layers,
        narration_unlocked: true,
        keyframes_unlocked: true,
        videos_unlocked: true,
      },
      director_script: {
        revision: 1,
        source_reference_revision: 1,
        production_baseline_revision: null,
        production_baseline_scenes: null,
        scenes: [
          {
            id: sceneId,
            title: "测试场景",
            summary: "测试摘要。",
            setting: "测试环境。",
            driver: "drama",
      location_id: null,
      state_id: null,
            narration_cues: [],
            shots: [
              {
                id: shotId,
                visible_character_ids: [],
                composition: "中景。",
                camera_movement: "固定。",
                action: "测试动作。",
                audio_direction: "环境声。",
                transition_in: null,
                view_id: null,
              }],
            segments: [{ shot_ids: [shotId],
                    id: segmentId,
                    duration_estimate_seconds: 5,
                    action: "测试动作。",
                    dialogue_lines: [],
                    boundary_from_previous: null,
                  }],
          },
        ],
      },
      keyframe_plan: {
        source_script_revision: 1,
        keyframes: [
          {
            id: startId,
            owner_segment_id: segmentId,
            predecessor_keyframe_id: null,
            prompt_text: "",
            visible_character_ids: [], character_references: [],
            selected_asset_id: null,
            environment_mode: "none",
      environment_view_id: null,
      environment_none_reason: "Shot 未绑定地点视图",
          },
          {
            id: endId,
            owner_segment_id: segmentId,
            predecessor_keyframe_id: startId,
            prompt_text: "",
            visible_character_ids: [], character_references: [],
            selected_asset_id: null,
            environment_mode: "none",
      environment_view_id: null,
      environment_none_reason: "Shot 未绑定地点视图",
          },
        ],
        segments: [
          {
            segment_id: segmentId,
            start_keyframe_id: startId,
            end_keyframe_id: endId,
            start_enabled: true,
            end_enabled: false,
            reference_asset_ids: [],
            start_frame_extraction: { source_segment_id: null, source_video_asset_id: null, state: "unavailable", message: "无上一段。" },
          },
        ],
      },
      video_plan: {
        source_script_revision: 1,
        segments: [
          videoFixture({segment_id: segmentId,prompt_text: "",selected_asset_id: null,upscaled_asset_id: null,active_recipe: "minimax_h3.fl2va", recipes: {["minimax_h3.fl2va"]: {bindings: {additional_images: [],reference_audios: [],reference_videos: []}, params: {}}}}),
        ],
      },
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response(visualSnapshot))
      .mockResolvedValueOnce(
        response({
          ...visualSnapshot,
          active_director_run: {
            id: "a".repeat(32),
            kind: "director",
            status: "running",
            waiting_reason: null,
            created_at: "2026-09-08T10:00:00Z",
            updated_at: "2026-09-08T10:00:00Z",
          },
          allowed_actions: [],
        }),
      )
      .mockResolvedValueOnce(
        response({
          ...visualSnapshot,
          active_director_run: {
            id: "a".repeat(32),
            kind: "director",
            status: "running",
            waiting_reason: null,
            created_at: "2026-09-08T10:00:00Z",
            updated_at: "2026-09-08T10:00:00Z",
          },
          workspace_layers: {
            ...visualSnapshot.workspace_layers,
            final_assembly_unlocked: true,
          },
          allowed_actions: [],
          final_assembly: {
            source_script_revision: 1,
            clips: [
              {
                scene_id: sceneId,
                zh_asset_id: "6".repeat(32),
                en_asset_id: "6".repeat(32),
                transition_from_previous: null,
              },
            ],
            selected_zh_asset_id: null,
            selected_en_asset_id: null,
          },
        }),
      );
    await expect(structuredDirectorApi.get(projectId)).resolves.toMatchObject({
      keyframe_plan: { keyframes: [{ prompt_text: "" }, { prompt_text: "" }] },
      video_plan: { segments: [{prompt_text: "",active_recipe: "minimax_h3.fl2va", recipes: {["minimax_h3.fl2va"]: {bindings: {}, params: {}}}}] },
    });
    await expect(structuredDirectorApi.get(projectId)).resolves.toMatchObject({
      active_director_run: { kind: "director", status: "running" },
      keyframe_plan: { segments: [{ segment_id: segmentId }] },
    });
    await expect(structuredDirectorApi.get(projectId)).resolves.toMatchObject({
      active_director_run: { kind: "director", status: "running" },
      final_assembly: { clips: [{ scene_id: sceneId }] },
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
  it("接受生产期回改后保留解锁状态但清空下游计划", async () => {
    const scene = {
      id: "1".repeat(32),
      title: "场景",
      summary: "摘要",
      setting: "室内",
      driver: "drama",
      location_id: null,
      state_id: null,
      narration_cues: [],
      shots: [
        {
          id: "2".repeat(32),
          visible_character_ids: [],
          composition: "中景",
          camera_movement: "固定",
          action: "人物停下",
          audio_direction: "环境声",
          transition_in: null,
          view_id: null,
        }],
      segments: [{ shot_ids: ["2".repeat(32)],
              id: "3".repeat(32),
              duration_estimate_seconds: 4,
              action: "人物停下",
              dialogue_lines: [],
              boundary_from_previous: null,
            }],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      response({
        ...reviewingSnapshot,
        status: "reviewing_videos",
        workspace_layers: {
          narration_unlocked: true,
          keyframes_unlocked: true,
          videos_unlocked: true,
          final_assembly_unlocked: false,
        },
        director_script: {
          revision: 12,
          source_reference_revision: 1,
          production_baseline_revision: 11,
          production_baseline_scenes: [scene],
          scenes: [scene],
        },
        keyframe_plan: null,
        video_plan: null,
      }),
    );
    await expect(structuredDirectorApi.get(projectId)).resolves.toMatchObject({
      status: "reviewing_videos",
      workspace_layers: { keyframes_unlocked: true, videos_unlocked: true },
      keyframe_plan: null,
      video_plan: null,
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });
  it("接受成片层已解锁但上游回改使装配计划失效的状态", async () => {
    const scene = {
      id: "1".repeat(32),
      title: "场景",
      summary: "摘要",
      setting: "室内",
      driver: "drama",
      location_id: null,
      state_id: null,
      narration_cues: [],
      shots: [
        {
          id: "2".repeat(32),
          visible_character_ids: [],
          composition: "中景",
          camera_movement: "固定",
          action: "人物停下",
          audio_direction: "环境声",
          transition_in: null,
          view_id: null,
        }],
      segments: [{ shot_ids: ["2".repeat(32)],
              id: "3".repeat(32),
              duration_estimate_seconds: 4,
              action: "人物停下",
              dialogue_lines: [],
              boundary_from_previous: null,
            }],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      response({
        ...reviewingSnapshot,
        status: "reviewing_final",
        revision: 13,
        workspace_layers: {
          narration_unlocked: true,
          keyframes_unlocked: true,
          videos_unlocked: true,
          final_assembly_unlocked: true,
        },
        director_script: {
          revision: 12,
          source_reference_revision: 1,
          production_baseline_revision: 11,
          production_baseline_scenes: [scene],
          scenes: [scene],
        },
        keyframe_plan: {
          source_script_revision: 12,
          keyframes: [
            {
              id: "4".repeat(32),
              owner_segment_id: "3".repeat(32),
              predecessor_keyframe_id: null,
              prompt_text: "首帧",
              visible_character_ids: [], character_references: [],
              selected_asset_id: null,
              environment_mode: "none",
      environment_view_id: null,
      environment_none_reason: "Shot 未绑定地点视图",
            },
            {
              id: "5".repeat(32),
              owner_segment_id: "3".repeat(32),
              predecessor_keyframe_id: "4".repeat(32),
              prompt_text: "尾帧",
              visible_character_ids: [], character_references: [],
              selected_asset_id: null,
              environment_mode: "none",
      environment_view_id: null,
      environment_none_reason: "Shot 未绑定地点视图",
            },
          ],
          segments: [
            {
              segment_id: "3".repeat(32),
              start_keyframe_id: "4".repeat(32),
              end_keyframe_id: "5".repeat(32),
              start_enabled: true,
              end_enabled: false,
              reference_asset_ids: [],
              start_frame_extraction: { source_segment_id: null, source_video_asset_id: null, state: "unavailable", message: "无上一段。" },
            },
          ],
        },
        video_plan: null,
        final_assembly: null,
      }),
    );
    await expect(structuredDirectorApi.get(projectId)).resolves.toMatchObject({
      status: "reviewing_final",
      workspace_layers: { final_assembly_unlocked: true },
      final_assembly: null,
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });
  it("解锁视觉生产遇到瞬时 revision 冲突时读取最新状态并重试", async () => {
    const latest = {
      ...reviewingSnapshot,
      allowed_actions: ["unlock_visual_production"],
      revision: 2,
    };
    const unlocked = {
      ...reviewingSnapshot,
      allowed_actions: [],
      revision: 3,
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        response(
          {
            error: {
              code: "revision_conflict",
              message: "项目已被更新，请重新读取后再解锁视觉生产。",
              recoverable: true,
              origin: "core_revision",
              state_changed: false,
              retry_policy: "reread_then_reissue_if_still_intended",
              automatic_retry_allowed: false,
            },
          },
          409,
        ),
      )
      .mockResolvedValueOnce(response(latest))
      .mockResolvedValueOnce(response(unlocked));
    await expect(
      structuredDirectorApi.unlockVisualProduction(projectId, 1),
    ).resolves.toEqual(unlocked);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `/api/projects/${projectId}/structured-director`,
      undefined,
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `/api/projects/${projectId}/structured-director/visual-production/unlock`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ expected_revision: 2 }),
      }),
    );
  });
  it("关键帧激活请求携带完整语义前置条件", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(response(reviewingSnapshot));
    const startKeyframeId = "1".repeat(32);
    const endKeyframeId = "2".repeat(32);
    await structuredDirectorApi.saveSegmentKeyframeActivation(
      projectId,
      7,
      "3".repeat(32),
      true,
      false,
      {
        startKeyframeId,
        endKeyframeId,
        startEnabled: true,
        endEnabled: true,
        startSelectedAssetId: "4".repeat(32),
        endSelectedAssetId: null,
      },
    );
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/projects/${projectId}/structured-director/segments/${"3".repeat(32)}` +
        "/keyframe-activation",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          expected_revision: 7,
          start_enabled: true,
          end_enabled: false,
          expected_start_keyframe_id: startKeyframeId,
          expected_end_keyframe_id: endKeyframeId,
          expected_start_enabled: true,
          expected_end_enabled: true,
          expected_start_selected_asset_id: "4".repeat(32),
          expected_end_selected_asset_id: null,
        }),
      }),
    );
  });
  it("复制完整创作搭档提示词，保留用户输入且不提交项目", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(response({ projects: [] }));
    render(<App />);
    fireEvent.change(await screen.findByLabelText("项目名称"), {
      target: { value: "雨夜末班车" },
    });
    fireEvent.change(screen.getByLabelText("完整导演方案"), {
      target: { value: directorPlan },
    });
    expect(screen.queryByLabelText("创作搭档提示词（手动复制）")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "复制创作搭档提示词" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("已复制。"));
    expect(writeText).toHaveBeenCalledExactlyOnceWith(creativePartnerPrompt);
    expect(screen.getByLabelText("项目名称")).toHaveValue("雨夜末班车");
    expect(screen.getByLabelText("完整导演方案")).toHaveValue(directorPlan);
    expect(screen.getByRole("button", { name: /创建项目/ })).toBeDisabled();
    fireEvent.click(screen.getByLabelText("中文旁白"));
    expect(screen.getByRole("button", { name: /创建项目/ })).toBeEnabled();
    expect(fetchMock).toHaveBeenCalledOnce();
  });
  it("两份提示词共用同一份最终交付格式，不留占位符", () => {
    for (const prompt of [creativePartnerPrompt, directorPlanConvertPrompt]) {
      expect(prompt).not.toContain("{{");
      expect(prompt).toContain("## 最终交付给 StoryRail 的 Markdown");
      expect(prompt).toContain("段落意图");
    }
    expect(creativePartnerPrompt).toContain("现在先开始聊天");
    expect(directorPlanConvertPrompt).toContain("只整理，不重新创作");
  });
  it("复制方案整理提示词，失败时手动复制的是整理提示词", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const browserNavigator: { clipboard?: { writeText: typeof writeText } } = {
      clipboard: { writeText },
    };
    vi.stubGlobal("navigator", browserNavigator);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ projects: [] }));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "复制方案整理提示词" }));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("连同原方案一起发给 AI"),
    );
    expect(writeText).toHaveBeenCalledExactlyOnceWith(directorPlanConvertPrompt);

    browserNavigator.clipboard = undefined;
    fireEvent.click(screen.getByRole("button", { name: "复制方案整理提示词" }));
    const fallback = await screen.findByLabelText<HTMLTextAreaElement>("方案整理提示词（手动复制）");
    expect(fallback).toHaveValue(directorPlanConvertPrompt);
    expect(screen.queryByLabelText("创作搭档提示词（手动复制）")).not.toBeInTheDocument();
  });
  it.each(["不可用", "拒绝授权"])("剪贴板%s时提供可全选的完整文本，允许重试", async (failure) => {
    const writeText = vi.fn().mockRejectedValue(new Error("Clipboard unavailable"));
    const browserNavigator = {
      clipboard: failure === "不可用" ? undefined : { writeText },
    };
    vi.stubGlobal("navigator", browserNavigator);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ projects: [] }));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "复制创作搭档提示词" }));
    const fallback = await screen.findByLabelText<HTMLTextAreaElement>("创作搭档提示词（手动复制）");
    expect(screen.getByRole("status")).toHaveTextContent("未能自动复制");
    expect(fallback).toHaveValue(creativePartnerPrompt);
    expect(fallback).toHaveAttribute("readonly");
    fireEvent.focus(fallback);
    expect(fallback.selectionStart).toBe(0);
    expect(fallback.selectionEnd).toBe(creativePartnerPrompt.length);
    expect(screen.getByLabelText("完整导演方案")).toHaveValue("");
    expect(screen.getByRole("button", { name: /创建项目/ })).toBeDisabled();

    browserNavigator.clipboard = { writeText: writeText.mockResolvedValue(undefined) };
    fireEvent.click(screen.getByRole("button", { name: "复制创作搭档提示词" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("已复制。"));
    expect(screen.queryByLabelText("创作搭档提示词（手动复制）")).not.toBeInTheDocument();
  });
  it.each([["zh"], ["en"], ["zh", "en"]] as const)("所选旁白语言 %j：创建后等待外部 Agent", async (...languages) => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ projects: [] }))
      .mockResolvedValueOnce(
        response(
          {
            project: { ...project, aspect_ratio: "9:16" },
            structured_director: { ...awaitingSnapshot, aspect_ratio: "9:16", narration_languages: languages },
          },
          201,
        ),
      )
      .mockResolvedValueOnce(
        response({ ...reviewingSnapshot, aspect_ratio: "9:16" }),
      );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("项目名称"), {
      target: { value: "雨夜末班车" },
    });
    fireEvent.change(screen.getByPlaceholderText(/粘贴已经讨论完成/), {
      target: { value: directorPlan },
    });
    fireEvent.change(screen.getByLabelText("画面比例"), {
      target: { value: "9:16" },
    });
    expect(screen.getByRole("button", { name: /创建项目/ })).toBeDisabled();
    for (const language of languages) fireEvent.click(screen.getByLabelText(language === "zh" ? "中文旁白" : "英文旁白"));
    fireEvent.click(screen.getByRole("button", { name: /创建项目/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/projects",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          title: "雨夜末班车",
          aspect_ratio: "9:16",
          director_plan_markdown: directorPlan,
  narration_languages: languages,
        }),
      }),
    );
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/reference-proposal"))).toBe(false);
  });
  it("已有项目直接打开结构化导演台", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ projects: [project] }))
      .mockResolvedValueOnce(response(reviewingSnapshot));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    const planButton = await screen.findByRole("button", {
      name: "原始导演方案",
    });
    const toolbar = planButton.parentElement;
    expect(toolbar).toContainElement(planButton);
    expect(toolbar).toContainElement(
      screen.getByRole("button", { name: "资产中心" }),
    );
    fireEvent.click(planButton);
    expect(
      screen.getByRole("dialog", { name: "原始导演方案" }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/projects/${projectId}/structured-director`,
      undefined,
    );
    expect(new URL(window.location.href).searchParams.get("project")).toBe(
      projectId,
    );
  });
  it("从项目 URL 重新载入时恢复结构化导演台", async () => {
    window.history.replaceState(null, "", `/?project=${projectId}`);
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ projects: [project] }))
      .mockResolvedValueOnce(response(reviewingSnapshot));
    render(<App />);
    expect(
      await screen.findByRole("button", { name: "原始导演方案" }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `/api/projects/${projectId}/structured-director`,
      undefined,
    );
  });
  it("删除需要二次确认并调用项目作用域接口", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ projects: [project] }))
      .mockResolvedValueOnce(response({ deleted_project_id: projectId }));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "删除" }));
    fireEvent.click(screen.getByRole("button", { name: "确定删除" }));
    await waitFor(() =>
      expect(screen.queryByText(project.title)).not.toBeInTheDocument(),
    );
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/projects/${projectId}`,
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
function snapshot(status: string, allowedActions: string[]) {
  return {
    status,
    revision: 1,
    aspect_ratio: "16:9",
    director_plan_markdown: directorPlan,
  narration_languages: ["zh", "en"],
    workspace_layers: {
      narration_unlocked: false,
      keyframes_unlocked: false,
      videos_unlocked: false,
      final_assembly_unlocked: false,
    },
    allowed_actions: allowedActions,
    workflow: {
      current_stage: "fixture",
      stage_status: "fixture",
      semantics: {
        current_stage: "primary_workflow_focus_not_capability_lock",
        active_task: "primary_workflow_task_only_parallel_activity_uses_task_discovery",
        required_next_actions: "primary_workflow_actions_only",
      },
      required_next_actions: [],
      recommended_next_actions: [],
      blocking_prerequisites: [],
      blocked_actions: {},
      workspace_capabilities: {
        semantics: "cumulative_unlocked_layers_not_primary_workflow",
        unlocked: [],
      },
      activity_summary: {
        active_generation_count: 0,
        has_active_generations: false,
        task_discovery_tool: "read_workflow",
        semantics: "parallel_project_activity_not_primary_workflow",
      },
      requires_explicit_user_request: true,
      active_task: null,
    },
    provider_recipes: [],
    dialogue_timing_warnings: [],
    provider_availability: {
      image_generation: false,
      voice_design: false,
      speech_synthesis: false,
      video_generation: false,
      video_upscale: false,
      final_assembly: false,
      scene_animatic: false,
      audio_separation: false,
      audio_remix: false,
    },
    assets: [],
    generations: [],
    reference_library: { characters: [], narrator: null },
    director_script: null,
    production_availability: {"narration": {"unlocked": false, "reason": "请到项目概览完成前置步骤。", "next_location": "project", "action": null}, "keyframes": {"unlocked": false, "reason": "请到项目概览完成前置步骤。", "next_location": "project", "action": null}, "videos": {"unlocked": false, "reason": "请到项目概览完成前置步骤。", "next_location": "project", "action": null}, "final": {"unlocked": false, "reason": "请到项目概览完成前置步骤。", "next_location": "project", "action": null}},
    location_library: {locations: [], allowed_actions: ["create_location"]},
    keyframe_plan: null,
    video_plan: null,
    final_assembly: null,
    final_approval: null,
    capability_gap_alerts: [],
    active_director_run: null,
  };
}
function productionSnapshot(overrides: Record<string, unknown> = {}) {
  const sceneId = "1".repeat(32);
  const shotId = "2".repeat(32);
  const segmentId = "3".repeat(32);
  const startId = "4".repeat(32);
  const endId = "5".repeat(32);
  const scene = {
    id: sceneId,
    title: "场景",
    summary: "摘要",
    setting: "室内",
    driver: "drama",
      location_id: null,
      state_id: null,
    narration_cues: [],
    shots: [
      {
        id: shotId,
        visible_character_ids: [],
        composition: "中景",
        camera_movement: "固定",
        action: "人物停下",
        audio_direction: "环境声",
        transition_in: null,
        view_id: null,
      }],
    segments: [{ shot_ids: [shotId],
            id: segmentId,
            duration_estimate_seconds: 4,
            action: "人物停下",
            dialogue_lines: [],
            boundary_from_previous: null,
          }],
  };
  return {
    ...snapshot("reviewing_videos", ["edit_script"]),
    workspace_layers: {
      narration_unlocked: true,
      keyframes_unlocked: true,
      videos_unlocked: true,
      final_assembly_unlocked: false,
    },
    director_script: {
      revision: 1,
      source_reference_revision: 1,
      production_baseline_revision: 1,
      production_baseline_scenes: [scene],
      scenes: [scene],
    },
    keyframe_plan: {
      source_script_revision: 1,
      keyframes: [
        {
          id: startId,
          owner_segment_id: segmentId,
          predecessor_keyframe_id: null,
          prompt_text: "首帧",
          visible_character_ids: [], character_references: [],
          selected_asset_id: null,
          environment_mode: "none",
      environment_view_id: null,
      environment_none_reason: "Shot 未绑定地点视图",
        },
        {
          id: endId,
          owner_segment_id: segmentId,
          predecessor_keyframe_id: startId,
          prompt_text: "尾帧",
          visible_character_ids: [], character_references: [],
          selected_asset_id: null,
          environment_mode: "none",
      environment_view_id: null,
      environment_none_reason: "Shot 未绑定地点视图",
        },
      ],
      segments: [
        {
          segment_id: segmentId,
          start_keyframe_id: startId,
          end_keyframe_id: endId,
          start_enabled: true,
          end_enabled: false,
          reference_asset_ids: [],
          start_frame_extraction: { source_segment_id: null, source_video_asset_id: null, state: "unavailable", message: "无上一段。" },
        },
      ],
    },
    video_plan: {
      source_script_revision: 1,
      segments: [
        videoFixture({segment_id: segmentId,prompt_text: "",selected_asset_id: null,upscaled_asset_id: null,active_recipe: "minimax_h3.fl2va", recipes: {["minimax_h3.fl2va"]: {bindings: {additional_images: [],reference_audios: [],reference_videos: []}, params: {}}}}),
      ],
    },
    ...overrides,
  };
}
function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function generation(
  kind: ReferenceGeneration["kind"],
  phase: ReferenceGeneration["phase"],
): ReferenceGeneration {
  return {
    id: "a".repeat(32),
    kind,
    operation:
      kind === "narration_audio"
        ? "synthesize"
        : kind === "video_upscale"
          ? "upscale"
          : kind === "segment_video"
            ? "render"
            : "generate",
    target_id: "b".repeat(32),
    phase,
    progress: phase === "succeeded" ? 1 : 0,
    message: "测试任务",
    prompt_text: "测试",
    input_asset_ids: [],
    sample_text: null,
    seed: null,
    output_asset_id: phase === "succeeded" ? "c".repeat(32) : null,
    error_code: phase === "failed" ? "test_failure" : null,
    cancellation_requested: false,
    retry_of: null,
    dismissed: false,
    provider: null,
    language: kind === "narration_audio" || kind === "final_video" || kind === "scene_final_video"
      ? "zh"
      : null,
    allowed_actions: [],
  };
}

describe("Playground 路由", () => {
  const playgroundSnapshot = {
    schema_version: 2,
    revision: 1,
    capabilities: [
      {
        id: "image.generate",
        label: "生图",
        execution: "async", group: "audio",
        available: true,
        notes: "", recipe: null,
      },
      { id: "audio.trim", label: "音频截取", execution: "sync", group: "audio", available: true, notes: "" },
    ],
    runs: [],
    assets: [],
  };
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    Element.prototype.scrollIntoView = vi.fn();
    window.scrollTo = vi.fn();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  it("?playground=1 时渲染 Playground，而不是项目列表", async () => {
    window.history.replaceState(null, "", "/?playground=1");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/api/projects") return response({ projects: [project] });
      return response(playgroundSnapshot);
    });
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Playground" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("已有项目")).not.toBeInTheDocument();
  });
  it("playground=1 优先于 project 参数，不打开项目工作台", async () => {
    window.history.replaceState(
      null,
      "",
      `/?playground=1&project=${projectId}`,
    );
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = String(input);
        if (url === "/api/projects") return response({ projects: [project] });
        if (url.startsWith(`/api/projects/${projectId}`)) {
          return response(reviewingSnapshot);
        }
        return response(playgroundSnapshot);
      });
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Playground" }),
    ).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some((call) =>
        String(call[0]).startsWith(`/api/projects/${projectId}/structured-director`),
      ),
    ).toBe(false);
  });
  it("首页 Playground 按钮进入，← 项目列表 退出并同步 URL", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/api/projects") return response({ projects: [project] });
      return response(playgroundSnapshot);
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Playground" }));
    expect(
      await screen.findByRole("heading", { name: "Playground" }),
    ).toBeInTheDocument();
    expect(new URL(window.location.href).searchParams.get("playground")).toBe(
      "1",
    );
    fireEvent.click(screen.getByRole("button", { name: "项目列表" }));
    expect(await screen.findByText("已有项目")).toBeInTheDocument();
    expect(
      new URL(window.location.href).searchParams.get("playground"),
    ).toBeNull();
  });
});
