import { videoFixture, videoState, videoRecipeViews } from "./test/video_fixture";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StructuredDirectorWorkspace } from "./StructuredDirectorWorkspace";
import type { WorkspaceActions } from "./director_workspace/contracts";
import readerFixture from "./test/story_reader_fixture.json";
import mixedApprovalFixture from "./test/mixed_approval_fixture.json";
import { parseStructuredDirectorSnapshot } from "./api/validation";
import { structuredDirectorApi } from "./api";
import type {
  KeyframeCharacterReference,
  ProjectSummary,
  Scene,
  ShotSegment,
  StructuredDirectorSnapshot,
} from "./api";
const project: ProjectSummary = {
  id: "1".repeat(32),
  title: "角色测试",
  aspect_ratio: "16:9",
  updated_at: "2026-08-29T00:00:00Z",
  status: "active",
};
it("shows saved input instead of pretending an unconfigured assistant is running", async () => {
  renderWorkspace(
    {},
    {
      ...snapshot,
      status: "awaiting_reference_proposal",
      allowed_actions: [],
    },
  );
  expect(screen.getByText("角色与声音引用库尚未建立")).toBeInTheDocument();
  expect(screen.queryByText("正在整理角色")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "继续整理" }),
  ).not.toBeInTheDocument();
});
// 基准 snapshot 来自生成 fixture（tests/test_architecture_acceptance.py __main__），
// 经唯一解析器 parseStructuredDirectorSnapshot 落型（不另写手工快照）；
// 引用库审查态所需的少量合成字段仍显式覆盖。
const approvedFixture = parseStructuredDirectorSnapshot(mixedApprovalFixture);
const snapshot: StructuredDirectorSnapshot = {
  ...approvedFixture,
  status: "reviewing_references",
  revision: 7,
  director_plan_markdown: "# 导演方案\n\n测试方案。",
  narration_languages: ["zh", "en"],
  active_director_run: null,
  capability_gap_alerts: [],
  workspace_layers: {
    narration_unlocked: false,
    keyframes_unlocked: false,
    videos_unlocked: false,
    final_assembly_unlocked: false,
  },
  allowed_actions: [
    "edit_reference_library",
    "import_image_asset",
    "import_media_asset",
    "attach_reference_image",
    "upload_reference_voice",
  ],
  workflow: {
    current_stage: "reference_library",
    stage_status: "awaiting_human_review",
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
  provider_availability: {
    image_generation: true,
    voice_design: true,
    speech_synthesis: true,
  },
  assets: [
    {
      id: "a".repeat(32),
      display_name: "海岸参考.png",
      media_type: "image/png",
      image_category: null,
      byte_count: 16,
      duration_seconds: null,
      content_url: "/asset.png",
      is_in_use: false,
      usage_reasons: [],
      retains_derived_assets_on_delete: false,
      allowed_actions: ["delete"],
    },
  ],
  generations: [],
  reference_library: {
    narrator: null,
    characters: [
      {
        id: "b".repeat(32),
        name: "小满",
        visual_description: "短发，蓝色外套",
        looks: [],
        voice_description: "年轻、温和、语速偏慢",
        voice_reference_asset_id: null,
      },
    ],
  },
  director_script: null,
  video_plan: null,
  location_library: { locations: [] },
  keyframe_plan: null,
  final_assembly: null,
  final_approval: null,
};
afterEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
describe("StructuredDirectorWorkspace", () => {
  it("唯一工作台在当前片段展示正文和生产，刷新恢复位置且没有额外全局读取", async () => {
    sessionStorage.clear();
    const load=vi.spyOn(structuredDirectorApi,"getProjection");
    const fixture=readerFixture.continuity;
    renderWorkspace({},fixture.production_snapshot as unknown as StructuredDirectorSnapshot,false);
    expect(screen.getByLabelText("故事工作台")).toBeVisible();
    const nav=screen.getByRole("navigation",{name:"故事层级"});
    fireEvent.click(within(nav).getByRole("button",{name:/场景 2.*戏剧/}));
    const sceneTwoSegments=within(nav).getByRole("list",{name:"场景 2 的生成片段"});
    fireEvent.click(within(sceneTwoSegments).getByRole("button",{name:/片段 2 · 镜头 2.*连续推进/}));
    expect(screen.getByRole("heading",{name:/片段 2 · 连续推进/})).toBeVisible();
    expect(screen.getByLabelText("当前 视频提示词")).toBeInTheDocument();
    expect(screen.getAllByRole("navigation",{name:"故事层级"})).toHaveLength(1);
    expect(screen.queryByLabelText("Agent 消息输入")).not.toBeInTheDocument();
    expect(load).not.toHaveBeenCalled();load.mockRestore();sessionStorage.clear();
  });
  it("以非阻塞报警展示已经执行的能力缺口 repair", async () => {
    renderWorkspace(
      {},
      {
        ...snapshot,
        capability_gap_alerts: [
          {
            gap_id: "f".repeat(32),
            run_id: "run-gap",
            missing_command: "script.update_shot_fields",
            raw_user_request_summary: "把第一个镜头改成近景。",
            target_ids: ["d".repeat(32)],
            scope_scene_ids: ["c".repeat(32)],
            operation_summary: "shot:dddd set composition",
            old_revision: 7,
            new_revision: 8,
            result: "succeeded",
            first_occurred_at: "2026-09-08T10:00:00Z",
            last_occurred_at: "2026-09-08T10:00:00Z",
            occurrence_count: 1,
            closed_revision: null,
            closed_by_command: null,
            status: "open",
          },
        ],
      },
    );
    const alert = screen.getByLabelText("能力缺口报警");
    expect(alert).toHaveTextContent("受控 repair 已完成，项目可继续工作");
    fireEvent.click(within(alert).getByText("查看修复记录"));
    expect(alert).toHaveTextContent("script.update_shot_fields");
    expect(alert).toHaveTextContent("把第一个镜头改成近景");
  });
  it("生产期脚本默认只读，显式编辑可查看范围、放弃或保存", async () => {
    const current: StructuredDirectorSnapshot = {
      ...snapshot,
      status: "reviewing_narration",
      workspace_layers: {
        ...snapshot.workspace_layers,
        narration_unlocked: true,
      },
      allowed_actions: ["edit_script"],
      director_script: {
        revision: 1,
        source_reference_revision: 7,
        production_baseline_revision: null,
        production_baseline_scenes: null,
        scenes: [
          {
            id: "c".repeat(32),
            title: "场景",
            summary: "初始摘要",
            setting: "站台",
            driver: "drama",
      location_id: null,
      state_id: null,
            narration_cues: [],
            shots: [
              {
                id: "d".repeat(32),
                visible_character_ids: [],
                composition: "远景",
                camera_movement: "固定",
                action: "等待",
                audio_direction: "风声",
                transition_in: null,
              }],
            segments: [{ shot_ids: ["d".repeat(32)],
                    id: "f".repeat(32),
                    duration_estimate_seconds: 3,
                    action: "Comi 回答。",
                    dialogue_lines: [
                      {
                        id: "d".repeat(32),
                        character_id: "b".repeat(32),
                        speaker_label: null,
                        voice_description: null,
                        text: "她猜的。",
                        delivery: "平静",
                      },
                    ],
                    boundary_from_previous: null,
                  }],
          },
        ],
      },
    };
    const onSaveScript = vi.fn();
    current.director_script!.scenes[0].shots.push({
      ...structuredClone(current.director_script!.scenes[0].shots[0]),
      id: "e".repeat(32),
    });
    const view = renderWorkspace({ onSaveScript }, current);
    expect(screen.queryByLabelText("场景摘要 *")).not.toBeInTheDocument();
    expect(onSaveScript).not.toHaveBeenCalled();
    const refreshed=structuredClone(current);refreshed.revision+=1;refreshed.director_script!.scenes[0].summary="服务端更新";
    view.rerenderSnapshot(refreshed);
    expect(screen.getByText("服务端更新")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button",{name:"编辑这一段"}));
    fireEvent.change(screen.getByLabelText("场景摘要 *"),{target:{value:"手动修改"}});
    vi.spyOn(window,"confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button",{name:"取消编辑"}));
    expect(onSaveScript).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button",{name:"编辑这一段"}));
    fireEvent.change(screen.getByLabelText("场景摘要 *"),{target:{value:"手动修改"}});
    fireEvent.click(screen.getByRole("button",{name:"保存脚本修改"}));
    expect(onSaveScript).toHaveBeenCalledExactlyOnceWith(expect.any(Array),refreshed.revision);
    expect(onSaveScript.mock.calls[0][0][0].shots).toEqual(refreshed.director_script!.scenes[0].shots);
    view.rerenderSnapshot(refreshed,true);view.rerenderSnapshot(structuredClone(refreshed));
    expect(screen.getByLabelText("场景摘要 *")).toHaveValue("手动修改");
    const concurrent=structuredClone(refreshed);concurrent.revision+=1;concurrent.director_script!.scenes[0].summary="并发修改";
    view.rerenderSnapshot(concurrent);
    expect(screen.getByLabelText("场景摘要 *")).toHaveValue("手动修改");
    expect(screen.getByRole("button",{name:"保存脚本修改"})).toBeDisabled();
    expect(screen.getByText(/草稿已保留/)).toBeInTheDocument();
  });

  it("通过顶栏入口打开全局引用弹窗，不再渲染悬浮卡片", async () => {
    const onClose = vi.fn();
    renderWorkspace({
      globalReferencesOpen: true,
      onCloseGlobalReferences: onClose,
    });
    const dialog = screen.getByRole("dialog", { name: "全局引用" });
    expect(within(dialog).getByText("小满")).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Global references 悬浮窗口"),
    ).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
  it("生产阶段引用变更待审核时可在全局引用弹窗完成确认", async () => {
    const onConfirmReferences = vi.fn();
    const current = structuredClone(
      readerFixture.continuity.production_snapshot,
    ) as unknown as StructuredDirectorSnapshot;
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
    renderWorkspace(
      {
        globalReferencesOpen: true,
        onConfirmReferences,
      },
      current,
    );
    const dialog = screen.getByRole("dialog", { name: "全局引用" });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "完成审核并继续" }),
    );
    expect(onConfirmReferences).toHaveBeenCalledOnce();
  });
  it("只读展示创建时固化的原始导演方案", async () => {
    renderWorkspace();
    fireEvent.click(screen.getByRole("button", { name: "原始导演方案" }));
    const dialog = screen.getByRole("dialog", { name: "原始导演方案" });
    expect(within(dialog).getByText("测试方案。")).toBeInTheDocument();
    expect(within(dialog).queryByRole("textbox")).not.toBeInTheDocument();
  });
  it("图片候选可以查看 Core 保存的完整提示词和输入参考图", async () => {
    const outputAssetId = "c".repeat(32);
    renderWorkspace(
      {},
      {
        ...snapshot,
        reference_library: {
          ...snapshot.reference_library,
          characters: [{
            ...snapshot.reference_library.characters[0],
            looks: [{
              id: "9".repeat(32), name: "日常", appearance: "蓝色外套", usage: "全片",
              selected_asset_id: null,
            }],
          }],
        },
        assets: [
          ...snapshot.assets,
          {
            id: outputAssetId,
            media_type: "image/png",
            image_category: null,
            byte_count: 32,
            duration_seconds: null,
            content_url: "/candidate.png",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
        ],
        generations: [
          {
            id: "d".repeat(32),
            kind: "character_look_sheet",
            language: null,
            operation: "generate",
            target_id: "9".repeat(32),
            phase: "succeeded",
            progress: 1,
            message: "图片生成完成。",
            prompt_text: "布偶猫哥哥站在窗边，午后自然光，保持蓝眼睛和白手套。",
            input_asset_ids: ["a".repeat(32)],
            sample_text: null,
            seed: null,
            output_asset_id: outputAssetId,
            error_code: null,
            cancellation_requested: false,
            retry_of: null,
            dismissed: false,
            allowed_actions: ["select_look_sheet", "dismiss_history"],
          },
        ],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "设置造型图" }));
    // 候选缩略图本身点击即放大；完整提示词走独立按钮。
    fireEvent.click(screen.getByRole("button", { name: "查看全图：生成的图片候选" }));
    const fullImage = screen.getByRole("dialog", { name: "生成的图片候选全图" });
    fireEvent.click(within(fullImage).getByRole("button", { name: "关闭全图" }));
    fireEvent.click(screen.getByRole("button", { name: "查看完整提示词" }));
    const promptDialog = screen.getByRole("dialog", { name: "完整提示词" });
    expect(promptDialog).toBeInTheDocument();
    expect(
      screen.getByText("布偶猫哥哥站在窗边，午后自然光，保持蓝眼睛和白手套。"),
    ).toBeInTheDocument();
    expect(within(promptDialog).getByText("@aaaaaa")).toBeInTheDocument();
    expect(screen.getByAltText("生成图片候选大图")).toHaveAttribute(
      "src",
      "/candidate.png",
    );
  });
  it("造型：编辑文字随整卡保存，设定图生成与选择是独立动作", async () => {
    const onUpdateCharacter = vi.fn();
    const onGenerateLookSheet = vi.fn();
    const onSelectLookSheet = vi.fn();
    const cardId = "b".repeat(32);
    const lookId = "e".repeat(32);
    const sheetGeneration = "f".repeat(32);
    renderWorkspace(
      { onUpdateCharacter, onGenerateLookSheet, onSelectLookSheet },
      {
        ...snapshot,
        reference_library: {
          ...snapshot.reference_library,
          characters: [{
            ...snapshot.reference_library.characters[0],
            looks: [{
              id: lookId, name: "日常", appearance: "蓝色外套", usage: "全片",
              selected_asset_id: "a".repeat(32),
            }],
          }],
        },
        generations: [{
          id: sheetGeneration, kind: "character_look_sheet", language: null,
          operation: "generate", target_id: lookId, phase: "succeeded", progress: 1,
          message: "完成。", prompt_text: "设定图", input_asset_ids: [], sample_text: null,
          seed: null, output_asset_id: "a".repeat(32), error_code: null,
          cancellation_requested: false, retry_of: null, dismissed: false,
          allowed_actions: ["select_look_sheet", "dismiss_history"],
        }],
      },
    );
    expect(screen.getByAltText("造型「日常」造型图")).toHaveAttribute("src", "/asset.png");
    fireEvent.click(screen.getByRole("button", { name: "更换造型图" }));
    const dialog = screen.getByRole("dialog", { name: "造型图：日常" });
    const promptBox = within(dialog).getByLabelText(/完整提示词/);
    await waitFor(() => expect(promptBox).toHaveValue("Core 编译的提示词"));
    fireEvent.click(within(dialog).getByRole("button", { name: /^可作身份参考的角色图/ }));
    // 未编辑时提交 null，由 Core 按当前造型与身份参考编译。
    fireEvent.click(within(dialog).getByRole("button", { name: "生成设定图候选" }));
    expect(onGenerateLookSheet).toHaveBeenLastCalledWith(cardId, lookId, ["a".repeat(32)], null);
    fireEvent.change(promptBox, { target: { value: "我改过的提示词" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "生成设定图候选" }));
    expect(onGenerateLookSheet).toHaveBeenLastCalledWith(
      cardId, lookId, ["a".repeat(32)], "我改过的提示词",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "恢复 Core 编译的提示词" }));
    expect(promptBox).toHaveValue("Core 编译的提示词");
    fireEvent.click(within(dialog).getByRole("button", { name: "设为本造型图" }));
    expect(onSelectLookSheet).toHaveBeenCalledWith(cardId, lookId, sheetGeneration);
    fireEvent.click(within(dialog).getByRole("button", { name: "关闭造型图" }));

    fireEvent.click(screen.getByRole("button", { name: "+ 新增造型" }));
    const fresh = screen.getByRole("article", { name: "造型 2" });
    expect(within(fresh).getByRole("button", { name: "设置造型图" })).toBeDisabled();
    fireEvent.change(within(fresh).getByLabelText(/造型名称/), { target: { value: "受伤" } });
    fireEvent.change(within(fresh).getByLabelText(/外观/), { target: { value: "破损战斗服" } });
    fireEvent.change(within(fresh).getByLabelText(/使用场合/), { target: { value: "第三幕" } });
    fireEvent.click(within(screen.getByRole("article", { name: "造型 日常" }))
      .getByRole("button", { name: "删除造型" }));
    fireEvent.click(screen.getByRole("button", { name: "保存卡片" }));
    expect(onUpdateCharacter).toHaveBeenCalledWith(expect.objectContaining({
      looks: [{ id: null, name: "受伤", appearance: "破损战斗服", usage: "第三幕" }],
    }));
  });
  it("先导入本地图片到资产库，再把资产设为造型图", async () => {
    const onImportImage = vi.fn();
    const onSelectLookAsset = vi.fn();
    const lookId = "e".repeat(32);
    renderWorkspace(
      { onImportImage, onSelectLookAsset },
      {
        ...snapshot,
        reference_library: {
          ...snapshot.reference_library,
          characters: [{
            ...snapshot.reference_library.characters[0],
            looks: [{
              id: lookId, name: "日常", appearance: "蓝色外套", usage: "全片",
              selected_asset_id: null,
            }],
          }],
        },
      },
    );
    const file = new File(["png-bytes"], "character.png", { type: "image/png" });
    fireEvent.click(screen.getByRole("button", { name: "设置造型图" }));
    fireEvent.click(screen.getByRole("tab", { name: "从资产库选择" }));
    expect(screen.getByAltText("角色图片资产预览")).toHaveAttribute("src", "/asset.png");
    fireEvent.change(screen.getByLabelText("选择要加入资产库的本地图片"), {
      target: { files: [file] },
    });
    expect(onImportImage).toHaveBeenCalledWith(file, "character_reference");
    // 选择卡片角落的放大按钮只放大，不改变选择。
    fireEvent.click(screen.getByRole("button", { name: "查看全图：@aaaaaa" }));
    const fullImage = screen.getByRole("dialog", { name: "@aaaaaa全图" });
    expect(within(fullImage).getByRole("img")).toHaveAttribute("src", "/asset.png");
    expect(onSelectLookAsset).not.toHaveBeenCalled();
    fireEvent.click(within(fullImage).getByRole("button", { name: "关闭全图" }));
    fireEvent.click(screen.getByRole("button", { name: "设为造型图 @aaaaaa" }));
    expect(onSelectLookAsset).toHaveBeenCalledWith("b".repeat(32), lookId, "a".repeat(32));
  });
  it("资产中心展示全部媒体，并只允许删除 Core 标记为未引用的 Asset", async () => {
    const onDeleteAsset = vi.fn();
    const referencedId = "c".repeat(32);
    const audioId = "d".repeat(32);
    renderWorkspace(
      { onDeleteAsset },
      {
        ...snapshot,
        allowed_actions: [
          ...snapshot.allowed_actions,
          "apply_audio_effect",
          "delete_asset",
        ],
        assets: [
          ...snapshot.assets,
          {
            id: referencedId,
            display_name: "角色参考.jpg",
            media_type: "image/jpeg",
            image_category: null,
            byte_count: 2048,
            duration_seconds: null,
            content_url: "/referenced.jpg",
            is_in_use: true,
            usage_reasons: [{ code: "character_reference_image", label: "角色参考图" }],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
          {
            id: audioId,
            display_name: "旁白音色.wav",
            media_type: "audio/wav",
            image_category: null,
            byte_count: 4096,
            duration_seconds: 2.4,
            content_url: "/voice.wav",
            is_in_use: true,
            usage_reasons: [{ code: "narrator_voice_reference", label: "旁白参考音色" }],
            retains_derived_assets_on_delete: false,
            allowed_actions: ["audio_effect"],
          },
        ],
        reference_library: {
          ...snapshot.reference_library,
          narrator: {
            id: "e".repeat(32),
            name: "旁白",
            zh: { voice_description: "温和", voice_reference_asset_id: audioId, voice_reference_transcript: null },
            en: { voice_description: "Warm", voice_reference_asset_id: null, voice_reference_transcript: null },
          },
          characters: [
            {
              ...snapshot.reference_library.characters[0],
              looks: [{
                id: "9".repeat(32), name: "日常", appearance: "外观", usage: "全片",
                selected_asset_id: referencedId,
              }],
            },
          ],
        },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    const dialog = await screen.findByRole("dialog", { name: "资产中心" });
    expect(within(dialog).getByAltText("海岸参考.png")).toBeInTheDocument();
    expect(within(dialog).getByAltText("角色参考.jpg")).toBeInTheDocument();
    expect(within(dialog).getByText("正在使用：角色参考图")).toBeInTheDocument();
    expect(within(dialog).getByText("正在使用：旁白参考音色")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("tab", { name: "音频" }));
    expect(within(dialog).getByText("audio/wav · 4.0 KB")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "音频后处理" }),
    ).toBeEnabled();
    expect(
      within(dialog).queryByAltText("海岸参考.png"),
    ).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("tab", { name: "全部" }));
    fireEvent.click(
      within(dialog).getByRole("button", { name: "永久删除废弃 Asset" }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "确认删除" }));
    expect(onDeleteAsset).toHaveBeenCalledWith("a".repeat(32));
  });
  it("资产中心按帧号抽帧，PNG 归入抽帧图，并在图片页显示抽取进行中", async () => {
    const onExtractVideoFrame = vi.fn();
    const videoId = "c".repeat(32);
    const extractedFrameId = "d".repeat(32);
    const view = renderWorkspace(
      { onExtractVideoFrame },
      {
        ...snapshot,
        assets: [
          ...snapshot.assets,
          {
            id: videoId,
            display_name: "片段.mp4",
            media_type: "video/mp4",
            image_category: null,
            byte_count: 4096,
            duration_seconds: 5.2,
            content_url: "/clip.mp4",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: ["video_frame"],
          },
          {
            id: extractedFrameId,
            display_name: "片段-尾帧.png",
            media_type: "image/png",
            image_category: "video_frame",
            byte_count: 2048,
            duration_seconds: null,
            content_url: "/clip-tail.png",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
        ],
        generations: [],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    const dialog = await screen.findByRole("dialog", { name: "资产中心" });
    expect(within(dialog).getByAltText("片段-尾帧.png")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("tab", { name: "图片" }));
    expect(within(dialog).getByAltText("片段-尾帧.png")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("tab", { name: "抽帧图" }));
    const frameArticle = within(dialog).getByAltText("片段-尾帧.png").closest("article");
    expect(frameArticle).not.toBeNull();
    expect(within(frameArticle as HTMLElement).getByText("抽帧图")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("tab", { name: "视频" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "抽帧" }));
    const picker = await screen.findByRole("dialog", { name: "从 片段.mp4 抽帧" });
    expect(await within(picker).findByText(/可选范围 0-119（共 120 帧）/)).toBeInTheDocument();
    expect(within(picker).getByLabelText("抽帧帧号")).toHaveValue(119);
    fireEvent.change(within(picker).getByLabelText("抽帧帧号"), { target: { value: "120" } });
    expect(within(picker).getByRole("button", { name: "抽取第 ? 帧" })).toBeDisabled();
    fireEvent.change(within(picker).getByLabelText("抽帧帧号"), { target: { value: "42" } });
    fireEvent.click(within(picker).getByRole("button", { name: "抽取第 42 帧" }));
    expect(onExtractVideoFrame).toHaveBeenCalledWith(videoId, 42);

    view.rerenderSnapshot({
      ...snapshot,
      assets: [
        ...snapshot.assets,
        {
          id: videoId,
          display_name: "片段.mp4",
          media_type: "video/mp4",
          image_category: null,
          byte_count: 4096,
          duration_seconds: 5.2,
          content_url: "/clip.mp4",
          is_in_use: false,
          usage_reasons: [],
          retains_derived_assets_on_delete: false,
          allowed_actions: ["video_frame"],
        },
        {
          id: extractedFrameId,
          display_name: "片段-尾帧.png",
          media_type: "image/png",
          image_category: "video_frame",
          byte_count: 2048,
          duration_seconds: null,
          content_url: "/clip-tail.png",
          is_in_use: false,
          usage_reasons: [],
          retains_derived_assets_on_delete: false,
          allowed_actions: [],
        },
      ],
      generations: [{
          id: "e".repeat(32),
          kind: "video_frame",
          language: null,
          operation: "process",
          target_id: videoId,
          phase: "running",
          progress: 0.4,
          message: "正在读取视频尾帧",
          prompt_text: "从资产中心提取视频实际尾帧。",
          input_asset_ids: [videoId],
          sample_text: null,
          seed: null,
          duration_seconds: null,
          output_asset_id: null,
          error_code: null,
          cancellation_requested: false,
          retry_of: null,
          dismissed: false,
          allowed_actions: [],
      }],
    });
    expect(within(dialog).getByRole("button", { name: "正在抽帧…" })).toBeDisabled();
    expect(within(dialog).getByText("正在读取视频尾帧")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "抽帧" })).not.toBeInTheDocument();
  });
  it("抽帧图有独立页签，且不作为本地图片导入分类", async () => {
    const frameId = "d".repeat(32);
    renderWorkspace(
      {},
      {
        ...snapshot,
        assets: [
          ...snapshot.assets,
          {
            id: frameId,
            display_name: "片段-尾帧.png",
            media_type: "image/png",
            image_category: "video_frame",
            byte_count: 2048,
            duration_seconds: null,
            content_url: "/clip-tail.png",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: ["delete"],
          },
        ],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    const dialog = await screen.findByRole("dialog", { name: "资产中心" });
    const tabs = within(dialog).getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabs).toContain("抽帧图");
    fireEvent.click(within(dialog).getByRole("tab", { name: "抽帧图" }));
    expect(within(dialog).getByAltText("片段-尾帧.png")).toBeInTheDocument();
    expect(within(dialog).queryByAltText("海岸参考.png")).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("tab", { name: "角色参考图" }));
    expect(within(dialog).queryByAltText("片段-尾帧.png")).not.toBeInTheDocument();
    const importCategory = within(dialog).getByLabelText("本地图片分类");
    expect(
      within(importCategory).queryByRole("option", { name: "抽帧图" }),
    ).not.toBeInTheDocument();
    expect(
      within(importCategory).getByRole("option", { name: "Keyframe 图" }),
    ).toBeInTheDocument();
  });
  it("资产中心不把抽帧 Generation 的输出关系当成项目使用，未绑定尾帧 PNG 可删除", async () => {
    const onDeleteAsset = vi.fn();
    const videoId = "c".repeat(32);
    const extractedFrameId = "d".repeat(32);
    renderWorkspace(
      { onDeleteAsset },
      {
        ...snapshot,
        allowed_actions: [...snapshot.allowed_actions, "delete_asset"],
        assets: [
          ...snapshot.assets,
          {
            id: videoId,
            display_name: "片段.mp4",
            media_type: "video/mp4",
            image_category: null,
            byte_count: 4096,
            duration_seconds: 5.2,
            content_url: "/clip.mp4",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: true,
            allowed_actions: ["video_frame", "delete"],
          },
          {
            id: extractedFrameId,
            display_name: "片段-尾帧.png",
            media_type: "image/png",
            image_category: "video_frame",
            byte_count: 2048,
            duration_seconds: null,
            content_url: "/clip-tail.png",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: ["delete"],
          },
        ],
        // Core 只把该 Generation 记为血缘：源 MP4 是输入，PNG 是输出，二者都不是项目使用关系。
        generations: [{
          id: "e".repeat(32),
          kind: "video_frame",
          language: null,
          operation: "process",
          target_id: videoId,
          phase: "succeeded",
          progress: 1,
          message: "视频尾帧提取完成。",
          prompt_text: "从资产中心提取视频实际尾帧。",
          input_asset_ids: [videoId],
          sample_text: null,
          seed: null,
          duration_seconds: null,
          output_asset_id: extractedFrameId,
          error_code: null,
          cancellation_requested: false,
          retry_of: null,
          dismissed: false,
          allowed_actions: [],
        }],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    const dialog = await screen.findByRole("dialog", { name: "资产中心" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "图片" }));
    const frameItem = within(dialog).getByAltText("片段-尾帧.png").closest("article");
    expect(frameItem).not.toBeNull();
    expect(within(frameItem as HTMLElement).queryByText(/正在使用/)).not.toBeInTheDocument();
    fireEvent.click(
      within(frameItem as HTMLElement).getByRole("button", { name: "永久删除废弃 Asset" }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "确认删除" }));
    expect(onDeleteAsset).toHaveBeenCalledWith(extractedFrameId);
  });
  it("被选为首帧的抽帧 PNG 展示 Core 使用原因且不能删除", async () => {
    const onDeleteAsset = vi.fn();
    const boundFrameId = "d".repeat(32);
    renderWorkspace(
      { onDeleteAsset },
      {
        ...snapshot,
        allowed_actions: [...snapshot.allowed_actions, "delete_asset"],
        assets: [
          ...snapshot.assets,
          {
            id: boundFrameId,
            display_name: "片段-尾帧.png",
            media_type: "image/png",
            image_category: "video_frame",
            byte_count: 2048,
            duration_seconds: null,
            content_url: "/clip-tail.png",
            is_in_use: true,
            usage_reasons: [{ code: "keyframe_selected_asset", label: "Keyframe 已选图片" }],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
        ],
        generations: [],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    const dialog = await screen.findByRole("dialog", { name: "资产中心" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "图片" }));
    const frameItem = within(dialog).getByAltText("片段-尾帧.png").closest("article");
    expect(frameItem).not.toBeNull();
    expect(
      within(frameItem as HTMLElement).getByText("正在使用：Keyframe 已选图片"),
    ).toBeInTheDocument();
    expect(
      within(frameItem as HTMLElement).queryByRole("button", { name: "永久删除废弃 Asset" }),
    ).not.toBeInTheDocument();
  });
  it("删除仍有派生结果的源 Asset 前提示派生文件保留但无法重新处理", async () => {
    const onDeleteAsset = vi.fn();
    const sourceId = "d".repeat(32);
    const derivedId = "e".repeat(32);
    renderWorkspace(
      { onDeleteAsset },
      {
        ...snapshot,
        allowed_actions: [...snapshot.allowed_actions, "delete_asset"],
        assets: [
          ...snapshot.assets,
          {
            id: sourceId,
            display_name: "原始视频.mp4",
            media_type: "video/mp4",
            image_category: null,
            byte_count: 4096,
            duration_seconds: 6.5,
            content_url: "/source.mp4",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: true,
            allowed_actions: ["delete"],
          },
          {
            id: derivedId,
            display_name: "音轨混音.mp4",
            media_type: "video/mp4",
            image_category: null,
            byte_count: 4096,
            duration_seconds: 6.5,
            content_url: "/derived.mp4",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
        ],
        generations: [{
          id: "f".repeat(32),
          kind: "video_audio_remix",
          language: null,
          operation: "remix",
          target_id: sourceId,
          phase: "succeeded",
          progress: 1,
          message: "完成",
          prompt_text: "混音",
          input_asset_ids: [sourceId],
          sample_text: null,
          seed: null,
          duration_seconds: 6.5,
          output_asset_id: derivedId,
          error_code: null,
          cancellation_requested: false,
          retry_of: null,
          dismissed: false,
          allowed_actions: ["dismiss_history"],
        }],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    const dialog = await screen.findByRole("dialog", { name: "资产中心" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "视频" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "永久删除废弃 Asset" }));
    expect(within(dialog).getByText(
      "派生 Asset 将保留并可继续使用，但无法再从这个源素材重新处理；相关 Generation 记录将一并清理。确定永久删除？",
    )).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "确认删除" }));
    expect(onDeleteAsset).toHaveBeenCalledWith(sourceId);
  });
  it("一键清理只提交当前资产页签内可删除的废弃 Asset", async () => {
    const onDeleteAssets = vi.fn();
    const deletableVideoId = "1".repeat(32);
    const referencedVideoId = "2".repeat(32);
    const deletableAudioId = "3".repeat(32);
    renderWorkspace(
      { onDeleteAssets },
      {
        ...snapshot,
        allowed_actions: [...snapshot.allowed_actions, "delete_asset"],
        assets: [
          ...snapshot.assets,
          {
            id: deletableVideoId,
            display_name: "废弃视频.mp4",
            media_type: "video/mp4",
            image_category: null,
            byte_count: 4096,
            duration_seconds: 4,
            content_url: "/unused.mp4",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: ["delete"],
          },
          {
            id: referencedVideoId,
            display_name: "使用中的视频.mp4",
            media_type: "video/mp4",
            image_category: null,
            byte_count: 4096,
            duration_seconds: 4,
            content_url: "/used.mp4",
            is_in_use: true,
            usage_reasons: [{ code: "segment_video_selected", label: "Segment 已选视频" }],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
          {
            id: deletableAudioId,
            display_name: "废弃音频.wav",
            media_type: "audio/wav",
            image_category: null,
            byte_count: 2048,
            duration_seconds: 2,
            content_url: "/unused.wav",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: ["delete"],
          },
        ],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    const dialog = await screen.findByRole("dialog", { name: "资产中心" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "视频" }));
    fireEvent.click(within(dialog).getByRole("button", {
      name: "清理当前页废弃 Asset（1）",
    }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("“视频”页中 1 个");
    fireEvent.click(within(dialog).getByRole("button", { name: "确认清理" }));
    expect(onDeleteAssets).toHaveBeenCalledWith([deletableVideoId]);

    fireEvent.click(within(dialog).getByRole("tab", { name: "全部" }));
    fireEvent.click(within(dialog).getByRole("button", {
      name: "清理当前页废弃 Asset（3）",
    }));
    fireEvent.click(within(dialog).getByRole("button", { name: "确认清理" }));
    expect(onDeleteAssets).toHaveBeenLastCalledWith([
      "a".repeat(32),
      deletableVideoId,
      deletableAudioId,
    ]);
  });
  it("资产中心可按时间范围截取 WAV，并在成功后关闭弹窗", async () => {
    const onTrimAudio = vi.fn().mockResolvedValue(true);
    const audioId = "c".repeat(32);
    renderWorkspace(
      { onTrimAudio },
      {
        ...snapshot,
        allowed_actions: [...snapshot.allowed_actions, "trim_audio"],
        assets: [{
          id: audioId,
          display_name: "完整录音.wav",
          media_type: "audio/wav",
          image_category: null,
          byte_count: 4096,
          duration_seconds: 8.25,
          content_url: "/recording.wav",
          is_in_use: false,
          usage_reasons: [],
          retains_derived_assets_on_delete: false,
          allowed_actions: ["audio_trim"],
        }],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    fireEvent.click(screen.getByRole("button", { name: "截取" }));
    const trimDialog = screen.getByRole("dialog", { name: "截取音频" });
    expect(within(trimDialog).getByText("源文件：完整录音.wav")).toBeInTheDocument();
    fireEvent.change(within(trimDialog).getByLabelText("截取开始时间"), {
      target: { value: "1.25" },
    });
    fireEvent.change(within(trimDialog).getByLabelText("截取结束时间"), {
      target: { value: "5.5" },
    });
    fireEvent.click(within(trimDialog).getByRole("button", { name: "创建截取副本" }));
    await waitFor(() => expect(onTrimAudio).toHaveBeenCalledWith(audioId, {
      start_seconds: 1.25,
      end_seconds: 5.5,
    }));
    await waitFor(() => expect(screen.queryByRole(
      "dialog", { name: "截取音频" },
    )).not.toBeInTheDocument());
  });
  it("资产中心用 Breeze TTS 2 设计或克隆音频", async () => {
    const onGenerateAudio = vi.fn().mockResolvedValue(true);
    const voiceId = "9".repeat(32);
    const voiceAsset = {
      id: voiceId,
      display_name: "参考声音.wav",
      media_type: "audio/wav" as const,
      image_category: null,
      byte_count: 4096,
      duration_seconds: 3,
      content_url: "/reference.wav",
      is_in_use: false,
      usage_reasons: [],
      retains_derived_assets_on_delete: false,
      allowed_actions: [],
    };
    const audioSnapshot: StructuredDirectorSnapshot = {
      ...snapshot,
      provider_recipes: parseStructuredDirectorSnapshot(readerFixture.continuity.production_snapshot).provider_recipes,
      allowed_actions: [...snapshot.allowed_actions, "generate_audio"],
      reference_library: {
        ...snapshot.reference_library,
        characters: [{
          ...snapshot.reference_library.characters[0],
          voice_reference_asset_id: voiceId,
          voice_reference_transcript: "参考音频完整文字稿。",
        }],
      },
    };
    const view = renderWorkspace(
      { onGenerateAudio },
      {
        ...audioSnapshot,
        assets: [voiceAsset],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    await screen.findByRole("tab", { name: "音频" });
    fireEvent.click(screen.getByRole("tab", { name: "音频" }));
    fireEvent.click(screen.getByRole("button", { name: "创建音频" }));
    let dialog = screen.getByRole("dialog", { name: "创建音频" });
    fireEvent.change(within(dialog).getByLabelText("音频生成文本"), {
      target: { value: "这里是远程观测站。" },
    });
    fireEvent.change(within(dialog).getByLabelText("音色描述"), {
      target: { value: "低沉、克制的中年男声" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "提交生成" }));
    await waitFor(() => expect(onGenerateAudio).toHaveBeenLastCalledWith({
      operation: "voice_design",
      text: "这里是远程观测站。",
      voice_description: "低沉、克制的中年男声",
      seed: 42,
    }));
    expect(screen.getByRole("dialog", { name: "创建音频" })).toBeInTheDocument();

    const generationId = "7".repeat(32);
    const outputId = "8".repeat(32);
    const runningGeneration = {
      id: generationId,
      kind: "generated_audio" as const,
      language: null,
      operation: "voice_design" as const,
      target_id: generationId,
      phase: "running" as const,
      progress: 0.4,
      message: "正在生成音频",
      prompt_text: "低沉、克制的中年男声",
      input_asset_ids: [],
      sample_text: "这里是远程观测站。",
      seed: 42,
      output_asset_id: null,
      error_code: null,
      cancellation_requested: false,
      retry_of: null,
      dismissed: false,
      allowed_actions: [],
    };
    view.rerenderSnapshot({
      ...audioSnapshot,
      assets: [voiceAsset],
      generations: [runningGeneration],
    });
    dialog = screen.getByRole("dialog", { name: "创建音频" });
    expect(within(dialog).getByText("生成中 · 40%")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("音频生成进度")).toHaveValue(0.4);
    expect(
      within(within(dialog).getByLabelText("本次生成进度")).getByText("Breeze TTS 2"),
    ).toBeInTheDocument();

    view.rerenderSnapshot({
      ...audioSnapshot,
      assets: [voiceAsset, {
        ...voiceAsset,
        id: outputId,
        display_name: "观测站.wav",
        content_url: "/generated.wav",
        is_in_use: false,
        usage_reasons: [],
        retains_derived_assets_on_delete: false,
      }],
      generations: [{
        ...runningGeneration,
        phase: "succeeded",
        progress: 1,
        message: "生成完成",
        output_asset_id: outputId,
        allowed_actions: ["dismiss_history"],
      }],
    });
    dialog = screen.getByRole("dialog", { name: "创建音频" });
    expect(within(dialog).getByText("生成完成 · 100%")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("试听生成音频"))
      .toHaveAttribute("src", "/generated.wav");

    fireEvent.change(within(dialog).getByLabelText("音频生成用途"), {
      target: { value: "synthesize" },
    });
    const referencePlayer = within(dialog).getByLabelText("播放当前参考音频");
    expect(referencePlayer).toHaveAttribute("src", "/reference.wav");
    fireEvent.change(within(dialog).getByLabelText("音频生成文本"), {
      target: { value: "信号正常，请继续。" },
    });
    fireEvent.change(within(dialog).getByLabelText("表演指示"), {
      target: { value: "冷静、清晰" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "提交生成" }));
    await waitFor(() => expect(onGenerateAudio).toHaveBeenLastCalledWith({
      operation: "synthesize",
      text: "信号正常，请继续。",
      voice_asset_id: voiceId,
      reference_transcript: "参考音频完整文字稿。",
      recipe_params: { "breeze_tts2.clone": { performance_instruction: "冷静、清晰" } },
      seed: 42,
    }));
    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }));
    expect(screen.queryByRole("dialog", { name: "创建音频" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "创建音频" }));
    dialog = screen.getByRole("dialog", { name: "创建音频" });
    expect(within(dialog).getByLabelText("音频生成文本")).toHaveValue("");
    expect(within(dialog).queryByLabelText("本次生成进度")).not.toBeInTheDocument();
  });
  it("Breeze 可用本机 ASR 自动填充参考音频完整文字稿", async () => {
    const voiceId = "9".repeat(32);
    const onTranscribeAudio = vi.fn().mockResolvedValue("参考音频的中 English 文本。 ");
    renderWorkspace(
      { onTranscribeAudio },
      {
        ...snapshot,
        provider_availability: {
          ...snapshot.provider_availability,
          speech_recognition: true,
        },
        allowed_actions: [...snapshot.allowed_actions, "generate_audio"],
        reference_library: {
          ...snapshot.reference_library,
          characters: [{
            ...snapshot.reference_library.characters[0],
            voice_reference_asset_id: voiceId,
            voice_reference_transcript: null,
          }],
        },
        assets: [{
          id: voiceId,
          display_name: "Breeze 参考声音.wav",
          media_type: "audio/wav",
          image_category: null,
          byte_count: 4096,
          duration_seconds: 3,
          content_url: "/reference.wav",
          is_in_use: false,
          usage_reasons: [],
          retains_derived_assets_on_delete: false,
          allowed_actions: [],
        }],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "自动提取音频文字" }));
    await waitFor(() => expect(onTranscribeAudio).toHaveBeenCalledWith(voiceId));
    await waitFor(() => expect(screen.getByLabelText("参考音频完整文字稿（声音克隆必填）"))
      .toHaveValue("参考音频的中 English 文本。"));
  });
  it("资产中心可为任意 WAV 创建无线电后处理副本", async () => {
    const onApplyAudioEffect = vi.fn();
    const audioId = "d".repeat(32);
    renderWorkspace(
      { onApplyAudioEffect },
      {
        ...snapshot,
        allowed_actions: [...snapshot.allowed_actions, "apply_audio_effect"],
        assets: [
          {
            id: audioId,
            display_name: "原始通讯.wav",
            media_type: "audio/wav",
            image_category: null,
            byte_count: 4096,
            duration_seconds: 2.4,
            content_url: "/voice.wav",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: ["audio_effect"],
          },
        ],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    fireEvent.click(screen.getByRole("button", { name: "音频后处理" }));
    const effectDialog = screen.getByRole("dialog", { name: "音频后处理" });
    expect(within(effectDialog).getByText("源文件：原始通讯.wav")).toBeInTheDocument();
    fireEvent.change(within(effectDialog).getByLabelText("音频后处理预设"), {
      target: { value: "dying_transmission" },
    });
    fireEvent.change(within(effectDialog).getByLabelText("音频后处理强度"), {
      target: { value: "0.85" },
    });
    fireEvent.change(within(effectDialog).getByLabelText("音频后处理 Seed"), {
      target: { value: "99" },
    });
    fireEvent.change(within(effectDialog).getByLabelText("后处理开始时间"), {
      target: { value: "0.4" },
    });
    fireEvent.change(within(effectDialog).getByLabelText("后处理结束时间"), {
      target: { value: "1.8" },
    });
    fireEvent.click(within(effectDialog).getByRole("button", {
      name: "创建处理后副本",
    }));
    expect(onApplyAudioEffect).toHaveBeenCalledWith(audioId, {
      effect: "radio",
      preset: "dying_transmission",
      strength: 0.85,
      seed: 99,
      start_seconds: 0.4,
      end_seconds: 1.8,
    });
  });
  it("视频音轨编辑器实时试听区间音量、打开完整后处理并提交混音", async () => {
    const previewGain = {
      cancelScheduledValues: vi.fn(),
      setValueAtTime: vi.fn(),
      linearRampToValueAtTime: vi.fn(),
    };
    class PreviewAudioContext {
      currentTime = 10;
      destination = {};
      createMediaElementSource() {
        return {connect: vi.fn(), disconnect: vi.fn()};
      }
      createGain() {
        return {gain: previewGain, connect: vi.fn(), disconnect: vi.fn()};
      }
      resume() { return Promise.resolve(); }
      close() { return Promise.resolve(); }
    }
    vi.stubGlobal("AudioContext", PreviewAudioContext);
    const videoId = "7".repeat(32);
    const voiceId = "8".repeat(32);
    const backgroundId = "9".repeat(32);
    const onApplyAudioEffect = vi.fn();
    const onRemixVideoAudio = vi.fn()
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(true);
    const generation = (
      id: string,
      kind: "video_audio_voice" | "video_audio_background",
      outputAssetId: string,
    ) => ({
      id,
      kind,
      language: null,
      operation: "separate" as const,
      target_id: videoId,
      phase: "succeeded" as const,
      progress: 1,
      message: "分离完成",
      prompt_text: JSON.stringify({ batch_id: "a".repeat(32) }),
      input_asset_ids: [videoId],
      sample_text: null,
      seed: null,
      output_asset_id: outputAssetId,
      error_code: null,
      cancellation_requested: false,
      retry_of: null,
      dismissed: false,
      allowed_actions: ["dismiss_history" as const],
    });
    renderWorkspace(
      { onApplyAudioEffect, onRemixVideoAudio },
      {
        ...snapshot,
        provider_availability: {
          ...snapshot.provider_availability,
          audio_separation: true,
          audio_remix: true,
        },
        assets: [
          { id: videoId, display_name: "混合视频.mp4", media_type: "video/mp4",
            image_category: null, byte_count: 100, duration_seconds: 3,
            content_url: "/mix.mp4",is_in_use: false, usage_reasons: [], retains_derived_assets_on_delete: false, allowed_actions: ["audio_editor"] },
          { id: voiceId, display_name: "人声.wav", media_type: "audio/wav",
            image_category: null, byte_count: 100, duration_seconds: 3,
            content_url: "/voice.wav",is_in_use: false, usage_reasons: [], retains_derived_assets_on_delete: false, allowed_actions: ["audio_effect"] },
          { id: backgroundId, display_name: "背景.wav", media_type: "audio/wav",
            image_category: null, byte_count: 100, duration_seconds: 3,
            content_url: "/background.wav",is_in_use: false, usage_reasons: [], retains_derived_assets_on_delete: false, allowed_actions: ["audio_effect"] },
        ],
        generations: [
          generation("b".repeat(32), "video_audio_voice", voiceId),
          generation("c".repeat(32), "video_audio_background", backgroundId),
        ],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    fireEvent.click(screen.getByRole("button", { name: "处理音轨" }));
    const editor = screen.getByRole("dialog", { name: "视频音轨编辑器" });
    expect(within(editor).getByRole("tab", { name: "音轨" })).toHaveAttribute(
      "aria-selected", "true",
    );
    expect(editor.querySelectorAll("audio")).toHaveLength(2);
    expect(within(editor).getAllByText("试听和导出使用的版本")).toHaveLength(2);
    expect(within(editor).getAllByText("原始音轨（未后处理）")).toHaveLength(2);
    fireEvent.change(within(editor).getByLabelText("人声 / 对白音量"), {
      target: { value: "-2.5" },
    });
    fireEvent.change(within(editor).getByLabelText("背景声（音乐、环境与音效）音量"), {
      target: { value: "-6" },
    });
    const remixButton = within(editor).getByRole("button", {
      name: "重新应用到视频并创建副本",
    });
    fireEvent.change(within(editor).getByLabelText("人声 / 对白音量开始时间"), {
      target: { value: "0.5" },
    });
    fireEvent.change(within(editor).getByLabelText("人声 / 对白音量结束时间"), {
      target: { value: "0.5" },
    });
    expect(remixButton).toBeDisabled();
    fireEvent.change(within(editor).getByLabelText("人声 / 对白音量结束时间"), {
      target: { value: "1.5" },
    });
    const voicePreview = editor.querySelectorAll("audio")[0];
    Object.defineProperty(voicePreview, "currentTime", {configurable: true, value: 1});
    fireEvent.play(voicePreview);
    await waitFor(() => expect(previewGain.setValueAtTime).toHaveBeenCalledWith(
      10 ** (-2.5 / 20), 10,
    ));
    expect(previewGain.linearRampToValueAtTime).toHaveBeenCalledWith(1, 10.5);
    fireEvent.change(within(editor).getByLabelText(
      "背景声（音乐、环境与音效）音量开始时间",
    ), { target: { value: "1" } });
    fireEvent.change(within(editor).getByLabelText(
      "背景声（音乐、环境与音效）音量结束时间",
    ), { target: { value: "2.5" } });
    expect(within(editor).queryAllByRole("checkbox")).toHaveLength(0);
    fireEvent.click(within(editor).getAllByRole("button", { name: "完整后处理…" })[0]);
    const effectDialog = screen.getByRole("dialog", { name: "音频后处理" });
    expect(effectDialog.parentElement).toHaveClass("is-nested");
    fireEvent.change(within(effectDialog).getByLabelText("音频后处理预设"), {
      target: { value: "bad_signal" },
    });
    fireEvent.change(within(effectDialog).getByLabelText("音频后处理强度"), {
      target: { value: "0.65" },
    });
    fireEvent.change(within(effectDialog).getByLabelText("后处理开始时间"), {
      target: { value: "0.75" },
    });
    fireEvent.change(within(effectDialog).getByLabelText("后处理结束时间"), {
      target: { value: "2.5" },
    });
    fireEvent.click(within(effectDialog).getByRole("button", {name: "取消"}));
    fireEvent.click(remixButton);
    await waitFor(() => expect(onRemixVideoAudio).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("dialog", { name: "视频音轨编辑器" })).toBeInTheDocument();
    fireEvent.click(remixButton);
    await waitFor(() => expect(screen.queryByRole(
      "dialog", { name: "视频音轨编辑器" },
    )).not.toBeInTheDocument());
    expect(onRemixVideoAudio).toHaveBeenLastCalledWith(
      videoId, voiceId, backgroundId,
      { gain_db: -2.5, start_seconds: 0.5, end_seconds: 1.5 },
      { gain_db: -6, start_seconds: 1, end_seconds: 2.5 },
    );
  });
  it("资产中心要求先选择明确图片分类再导入，并按分类过滤", async () => {
    const onImportImage = vi.fn();
    const characterAsset = {
      ...snapshot.assets[0],
      image_category: "character_reference" as const,
      display_name: "角色图.png",
    };
    const sceneAsset = {
      ...snapshot.assets[0],
      id: "f".repeat(32),
      image_category: "location_image" as const,
      display_name: "场景图.png",
    };
    renderWorkspace(
      { onImportImage },
      { ...snapshot, assets: [characterAsset, sceneAsset] },
    );
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    const dialog = await screen.findByRole("dialog", { name: "资产中心" });
    const importButton = within(dialog).getByRole("button", {
      name: "加入本地图片",
    });
    expect(importButton).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("本地图片分类"), {
      target: { value: "keyframe" },
    });
    expect(importButton).toBeEnabled();
    const file = new File(["png"], "关键帧.png", { type: "image/png" });
    const fileInput =
      within(dialog).getByLabelText("选择要加入资产中心的本地图片");
    expect(fileInput).toHaveAttribute("hidden");
    fireEvent.change(fileInput, {
      target: { files: [file] },
    });
    expect(onImportImage).toHaveBeenCalledWith(file, "keyframe");
    fireEvent.click(within(dialog).getByRole("tab", { name: "角色参考图" }));
    expect(within(dialog).getByAltText("角色图.png")).toBeInTheDocument();
    expect(within(dialog).queryByAltText("场景图.png")).not.toBeInTheDocument();
  });
  it("资产中心选择分类后可以直接粘贴剪贴板图片", async () => {
    const onImportImage = vi.fn();
    renderWorkspace({ onImportImage });
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    const dialog = await screen.findByRole("dialog", { name: "资产中心" });
    const clipboardFile = new File(["png"], "", { type: "image/png" });
    const clipboardData = {
      items: [
        {
          kind: "file",
          type: "image/png",
          getAsFile: () => clipboardFile,
        },
      ],
      files: [clipboardFile],
    };
    fireEvent.paste(dialog, { clipboardData });
    expect(onImportImage).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "请先选择图片分类，再导入图片。",
    );
    fireEvent.change(within(dialog).getByLabelText("本地图片分类"), {
      target: { value: "location_image" },
    });
    fireEvent.paste(dialog, { clipboardData });
    expect(onImportImage).toHaveBeenCalledTimes(1);
    const [file, category] = onImportImage.mock.calls[0];
    expect(file).toBeInstanceOf(File);
    expect(file.name).toBe("剪贴板图片.png");
    expect(file.type).toBe("image/png");
    expect(category).toBe("location_image");
    expect(
      within(dialog).getByText("或按 ⌘V / Ctrl+V 粘贴图片"),
    ).toBeInTheDocument();
  });
  it("资产中心可分别导入 WAV 音频和 MP4 视频", async () => {
    const onImportMedia = vi.fn();
    renderWorkspace({ onImportMedia });
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    const dialog = await screen.findByRole("dialog", { name: "资产中心" });

    fireEvent.click(within(dialog).getByRole("tab", { name: "音频" }));
    expect(within(dialog).getByText("仅支持 WAV")).toBeInTheDocument();
    const wav = new File(["wav"], "现场录音.wav", { type: "audio/wav" });
    fireEvent.change(within(dialog).getByLabelText("选择要导入的本地音频"), {
      target: { files: [wav] },
    });
    expect(onImportMedia).toHaveBeenCalledWith(wav);

    fireEvent.click(within(dialog).getByRole("tab", { name: "视频" }));
    expect(within(dialog).getByText("仅支持 MP4")).toBeInTheDocument();
    const mp4 = new File(["mp4"], "现场素材.mp4", { type: "video/mp4" });
    fireEvent.change(within(dialog).getByLabelText("选择要导入的本地视频"), {
      target: { files: [mp4] },
    });
    expect(onImportMedia).toHaveBeenLastCalledWith(mp4);
  });
  it("音色描述只在 AI 设计入口出现并用于 Breeze 音色设计", async () => {
    const onDesignVoice = vi.fn<DesignVoiceHandler>();
    renderWorkspace({ onDesignVoice });
    expect(screen.queryByLabelText(/^音色描述/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "+ 创建参考音色" }));
    expect(screen.queryByLabelText(/^音色描述/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /AI 设计音色/ }));
    expect(screen.getByLabelText(/^音色描述/)).toHaveValue(
      "年轻、温和、语速偏慢",
    );
    fireEvent.click(screen.getByRole("button", { name: "生成试听候选" }));
    expect(onDesignVoice).toHaveBeenCalledWith(
      "b".repeat(32),
      "年轻、温和、语速偏慢",
      "你好，很高兴认识你。我们从这里开始讲这个故事。",
      42,
    );
  });
  it("可以从资产库选择 WAV 并明确设为参考音色", async () => {
    const onUpdateCharacter = vi.fn();
    const voiceAssetId = "c".repeat(32);
    renderWorkspace(
      { onUpdateCharacter },
      {
        ...snapshot,
        assets: [{
          id: voiceAssetId,
          display_name: "完整参考音频.wav",
          media_type: "audio/wav",
          image_category: null,
          byte_count: 4096,
          duration_seconds: 4.2,
          content_url: "/reference.wav",
          is_in_use: false,
          usage_reasons: [],
          retains_derived_assets_on_delete: false,
          allowed_actions: [],
        }],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "+ 创建参考音色" }));
    fireEvent.click(screen.getByRole("button", { name: /从资产库选择/ }));
    expect(screen.queryByLabelText(/^音色描述/)).not.toBeInTheDocument();
    expect(screen.getByText("完整参考音频.wav")).toBeInTheDocument();
    expect(screen.getByLabelText("播放 完整参考音频.wav")).toHaveAttribute(
      "src",
      "/reference.wav",
    );
    fireEvent.click(screen.getByRole("button", { name: "设为参考音色" }));
    expect(onUpdateCharacter).toHaveBeenCalledWith(expect.objectContaining({
      voice_reference_asset_id: voiceAssetId,
      voice_reference_transcript: null,
    }));
  });
  it("失败历史明确显示问题环节，并允许二次确认后删除卡片", async () => {
    const onDismissGeneration = vi.fn();
    renderWorkspace(
      { onDismissGeneration },
      {
        ...snapshot,
        generations: [
          {
            id: "d".repeat(32),
            kind: "character_voice",
            language: null,
            operation: "generate",
            target_id: "b".repeat(32),
            phase: "submission_uncertain",
            progress: 0,
            message: "问题出在提交响应校验：外部服务返回格式不符合约定。",
            prompt_text: "年轻、温和、语速偏慢",
            input_asset_ids: [],
            sample_text: "测试声音。",
            seed: 42,
            output_asset_id: null,
            error_code: "invalid_response",
            cancellation_requested: false,
            retry_of: null,
            dismissed: false,
            allowed_actions: ["dismiss_history"],
          },
        ],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "+ 创建参考音色" }));
    fireEvent.click(screen.getByRole("button", { name: /AI 设计音色/ }));
    expect(
      screen.getByText("问题出在提交响应校验：外部服务返回格式不符合约定。"),
    ).toBeInTheDocument();
    expect(screen.getByText("提交阶段 · 外部响应协议校验")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "隐藏历史卡片" }));
    fireEvent.click(screen.getByRole("button", { name: "确认隐藏" }));
    expect(onDismissGeneration).toHaveBeenCalledWith("d".repeat(32));
  });
  it("删除成功历史卡片需要确认并调用 Core 给出的允许动作", async () => {
    const onDismissGeneration = vi.fn();
    const generationId = "e".repeat(32);
    const audioAssetId = "f".repeat(32);
    renderWorkspace(
      { onDismissGeneration },
      {
        ...snapshot,
        assets: [
          ...snapshot.assets,
          {
            id: audioAssetId,
            media_type: "audio/wav",
            image_category: null,
            byte_count: 128,
            duration_seconds: 2.5,
            content_url: "/voice.wav",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
        ],
        generations: [
          {
            id: generationId,
            kind: "character_voice",
            language: null,
            operation: "voice_design",
            target_id: "b".repeat(32),
            phase: "succeeded",
            progress: 1,
            message: "模型调用完成。",
            prompt_text: "年轻、温和、语速偏慢",
            input_asset_ids: [],
            sample_text: "测试声音。",
            seed: 42,
            output_asset_id: audioAssetId,
            error_code: null,
            cancellation_requested: false,
            retry_of: null,
            dismissed: false,
            allowed_actions: ["attach_output", "dismiss_history"],
          },
        ],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "+ 创建参考音色" }));
    fireEvent.click(screen.getByRole("button", { name: /AI 设计音色/ }));
    // 候选卡片外壳由列表提供；内容不能再套一层同名卡片，否则会被挤进外层第一列。
    const candidate = screen.getByText("模型调用完成。").closest("article")!;
    expect(candidate).toHaveClass("generation-candidate");
    expect(candidate.querySelector(".generation-candidate")).toBeNull();
    expect(candidate.querySelector(".generation-candidate-body audio")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "隐藏历史卡片" }));
    expect(
      screen.getByText("隐藏后不再显示；废弃产物可随后在资产中心永久清理。"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认隐藏" }));
    expect(onDismissGeneration).toHaveBeenCalledWith(generationId);
  });
  it("旁白身份分别管理中英参考音色，英文设计只提交英文并只列英文候选", async () => {
    const onDesignNarratorVoice = vi.fn<WorkspaceActions["onDesignNarratorVoice"]>();
    const onUpdateNarrator = vi.fn<WorkspaceActions["onUpdateNarrator"]>();
    const narratorId = "6".repeat(32);
    const zhAudioId = "7".repeat(32);
    const voiceGeneration = (id: string, language: "zh" | "en", message: string) => ({
      id,
      kind: "narrator_voice" as const,
      language,
      operation: "voice_design" as const,
      target_id: narratorId,
      phase: "failed" as const,
      progress: 0,
      message,
      prompt_text: "描述",
      input_asset_ids: [],
      sample_text: "试听",
      seed: 42,
      output_asset_id: null,
      error_code: "provider_error",
      cancellation_requested: false,
      retry_of: null,
      dismissed: false,
      allowed_actions: ["dismiss_history" as const],
    });
    renderWorkspace(
      { onDesignNarratorVoice, onUpdateNarrator },
      {
        ...snapshot,
        reference_library: {
          ...snapshot.reference_library,
          narrator: {
            id: narratorId,
            name: "历史旁白",
            zh: { voice_description: "深沉浑厚的中文叙述", voice_reference_asset_id: zhAudioId, voice_reference_transcript: "中文文字稿" },
            en: { voice_description: "British RP, low and measured", voice_reference_asset_id: null, voice_reference_transcript: null },
          },
        },
        assets: [
          ...snapshot.assets,
          {
            id: zhAudioId,
            display_name: "中文旁白.wav",
            media_type: "audio/wav",
            image_category: null,
            byte_count: 128,
            duration_seconds: 2,
            content_url: "/zh.wav",
            is_in_use: true,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
        ],
        generations: [
          voiceGeneration("8".repeat(32), "zh", "中文音色候选失败"),
          voiceGeneration("9".repeat(32), "en", "英文音色候选失败"),
        ],
      },
    );
    const zhSection = screen.getByRole("region", { name: "中文旁白音色" });
    const enSection = screen.getByRole("region", { name: "英文旁白音色" });
    expect(within(zhSection).getByPlaceholderText("请逐字填写参考音频中实际说出的全部内容。")).toHaveValue("中文文字稿");
    expect(within(enSection).getByText("尚未选择英文参考音色。")).toBeInTheDocument();

    fireEvent.change(within(enSection).getByLabelText(/^英文旁白音色方向/), {
      target: { value: "General American, warm" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存旁白音色信息" }));
    expect(onUpdateNarrator).toHaveBeenCalledWith(expect.objectContaining({
      zh: expect.objectContaining({ voice_reference_asset_id: zhAudioId }),
      en: expect.objectContaining({ voice_description: "General American, warm" }),
    }));

    fireEvent.click(within(enSection).getByRole("button", { name: "+ 创建英文参考音色" }));
    const dialog = screen.getByRole("dialog", { name: "创建英文参考音色" });
    fireEvent.click(within(dialog).getByRole("button", { name: /AI 设计音色/ }));
    expect(within(dialog).getByText("英文音色候选失败")).toBeInTheDocument();
    expect(within(dialog).queryByText("中文音色候选失败")).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "生成试听候选" }));
    expect(onDesignNarratorVoice).toHaveBeenCalledWith(
      narratorId,
      "en",
      "General American, warm",
      "Hello, it's good to meet you. Let us begin the story here.",
      42,
    );
  });
  it("编辑结构化导演脚本并由用户明确进入旁白审核", async () => {
    const onSaveScript = vi.fn();
    const onConfirmScript = vi.fn();
    const scriptSnapshot: StructuredDirectorSnapshot = {
      ...snapshot,
      status: "reviewing_script",
      allowed_actions: [
        "edit_reference_library",
        "edit_script",
        "confirm_script",
      ],
      director_script: {
        revision: 1,
        source_reference_revision: 7,
        production_baseline_revision: null,
        production_baseline_scenes: null,
        scenes: [
          {
            id: "c".repeat(32),
            title: "末班车",
            summary: "小满在站台等待。",
            setting: "傍晚，空旷站台。",
            driver: "drama",
      location_id: null,
      state_id: null,
            narration_cues: [],
            shots: [
              {
                id: "d".repeat(32),
                visible_character_ids: ["b".repeat(32)],
                composition: "中远景。",
                camera_movement: "缓慢推近。",
                action: "小满抬头看站牌。",
                audio_direction: "风声。",
                transition_in: null,
              }],
            segments: [{ shot_ids: ["d".repeat(32)],
                    id: "e".repeat(32),
                    duration_estimate_seconds: 6,
                    action: "小满抬头。",
                    dialogue_lines: [
                      {
                        id: "d".repeat(32),
                        character_id: "b".repeat(32),
                        speaker_label: null,
                        voice_description: null,
                        text: "还会来吗？",
                        delivery: "轻声",
                      },
                    ],
                    boundary_from_previous: null,
                  }],
          },
        ],
      },
    };
    renderWorkspace({ onSaveScript, onConfirmScript }, scriptSnapshot);
    expect(screen.queryByLabelText("场景摘要 *")).not.toBeInTheDocument();
    const nav=screen.getByRole("navigation",{name:"故事层级"});
    fireEvent.click(within(nav).getByRole("button",{name:/片段 1/}));
    expect(screen.getAllByText("还会来吗？").length).toBeGreaterThan(0);
    const writeText=vi.fn().mockResolvedValue(undefined);vi.stubGlobal("navigator",{clipboard:{writeText}});
    fireEvent.click(screen.getByRole("button",{name:"复制定位"}));
    await waitFor(()=>expect(writeText).toHaveBeenCalledWith(
      "场景 1－片段 1",
    ));
    fireEvent.click(within(nav).getByRole("button",{name:/场景 1 ·/}));
    fireEvent.click(screen.getByRole("button",{name:"编辑这一段"}));
    fireEvent.change(screen.getByLabelText("场景摘要 *"),{target:{value:"小满决定不再等待。"}});
    fireEvent.click(screen.getByRole("button",{name:"保存脚本修改"}));
    expect(onSaveScript).toHaveBeenCalledWith([expect.objectContaining({summary:"小满决定不再等待。"})],scriptSnapshot.revision);
    vi.spyOn(window,"confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button",{name:"取消编辑"}));
    fireEvent.click(screen.getByText("场景结构操作"));
    fireEvent.click(screen.getByRole("button",{name:"在此后插入 Scene"}));
    const inserted=onSaveScript.mock.calls.at(-1)![0];
    expect(inserted).toHaveLength(2);expect(inserted[1].title).toBe("新场景");
    expect(inserted[1].id).toMatch(/^new:/);
    fireEvent.click(screen.getByRole("button",{name:"项目概览"}));
    fireEvent.click(screen.getByRole("button",{name:"确认脚本，进入旁白审核"}));
    expect(onConfirmScript).toHaveBeenCalledOnce();
  });

  it("在原结构化导演层级中按 Segment 展示首尾关键帧与独立辅助参考", async () => {
    const sceneId = "c".repeat(32);
    const sceneAssetId = "f".repeat(32);
    const onSaveKeyframe = vi.fn();
    const onSaveSegmentKeyframeActivation = vi.fn();
    const onSaveSegmentKeyframeBoundary = vi.fn();
    const makeSegment = (
      id: string,
      boundary: ShotSegment["boundary_from_previous"] = null,
    ) => ({
      id,
      duration_estimate_seconds: 4,
      action: `动作 ${id.slice(0, 2)}`,
      dialogue_lines: [],
      boundary_from_previous: boundary,
    });
    const scene: Scene = {
      driver: "drama",
      location_id: null,
      state_id: null,
      id: sceneId,
      title: "连续客厅",
      summary: "一个连续动作跨越多个 Segment 和 Shot。",
      setting: "固定客厅空间。",
      narration_cues: [],
      shots: [
        {
          id: "d".repeat(32),
          visible_character_ids: ["b".repeat(32)],
          composition: "中景。",
          camera_movement: "跟随。",
          action: "角色穿过客厅。",
          audio_direction: "室内声。",
          transition_in: null,
        },
        {
          id: "8".repeat(32),
          visible_character_ids: ["b".repeat(32)],
          composition: "近景。",
          camera_movement: "固定。",
          action: "动作延续到下一个 Shot。",
          audio_direction: "室内声连续。",
          transition_in: null,
        }],
      segments: [{ ...makeSegment("e".repeat(32)), shot_ids: ["d".repeat(32)] }, { ...makeSegment("7".repeat(32), {
              reason: "continuity_anchor",
              continuity_instruction: "承接上一段动作。",
            }), shot_ids: ["d".repeat(32)] }, { ...makeSegment("9".repeat(32)), shot_ids: ["8".repeat(32)] }],
    };
    renderWorkspace(
      { onSaveKeyframe, onSaveSegmentKeyframeActivation, onSaveSegmentKeyframeBoundary },
      {
        ...snapshot,
        status: "reviewing_keyframes",
        workspace_layers: {
          narration_unlocked: true,
          keyframes_unlocked: true,
          videos_unlocked: false,
          final_assembly_unlocked: false,
        },
        allowed_actions: [
          "edit_keyframe_references",
          "generate_keyframe",
          "generate_keyframe_batch",
          "select_keyframe",
        ],
        assets: [
          ...snapshot.assets,
          {
            id: sceneAssetId,
            media_type: "image/png",
            image_category: null,
            byte_count: 32,
            duration_seconds: null,
            content_url: "/scene.png",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
        ],
        director_script: {
          revision: 3,
          source_reference_revision: 7,
          production_baseline_revision: 3,
          production_baseline_scenes: [scene],
          scenes: [scene],
        },
        location_library: { locations: [
            {
              id: "6".repeat(32),
              name: "合成地点",
              description: "固定客厅空间。",
              fixtures: [],
              key_light: null,
              states: [],
              images: [
                {
                  id: "0".repeat(32),
                  name: "客厅正面",
                  kind: "image",
                  description: "客厅正面中景背景。",
                  prompt_text: "固定客厅空间。",
                  reference_asset_ids: [],
                  selected_asset_id: sceneAssetId,
                  source: null,
                },
              ],
            },
          ],
        },
        keyframe_plan: {
          source_script_revision: 3,
          keyframes: [
            {
              id: "1".repeat(32),
              owner_segment_id: "e".repeat(32),
              predecessor_keyframe_id: null,
              prompt_text: "角色尚未迈步。",
              visible_character_ids: [], character_references: [],
              selected_asset_id: sceneAssetId,
            },
            {
              id: "2".repeat(32),
              owner_segment_id: "e".repeat(32),
              predecessor_keyframe_id: "1".repeat(32),
              prompt_text: "角色走到客厅中央。",
              visible_character_ids: [], character_references: [],
              selected_asset_id: null,
            },
            {
              id: "3".repeat(32),
              owner_segment_id: "7".repeat(32),
              predecessor_keyframe_id: "2".repeat(32),
              prompt_text: "角色走到门边。",
              visible_character_ids: [], character_references: [],
              selected_asset_id: null,
            },
            {
              id: "4".repeat(32),
              owner_segment_id: "9".repeat(32),
              predecessor_keyframe_id: "3".repeat(32),
              prompt_text: "角色停在门边。",
              visible_character_ids: [], character_references: [],
              selected_asset_id: null,
            },
          ],
          segments: [
            {
              segment_id: "e".repeat(32),
              start_keyframe_id: "1".repeat(32),
              end_keyframe_id: "2".repeat(32),
              start_enabled: true,
              end_enabled: false,
              reference_asset_ids: [sceneAssetId],
              start_frame_extraction: { source_segment_id: null, source_video_asset_id: null, state: "unavailable", message: "无上一段。" },
            },
            {
              segment_id: "7".repeat(32),
              start_keyframe_id: "2".repeat(32),
              end_keyframe_id: "3".repeat(32),
              start_enabled: true,
              end_enabled: true,
              reference_asset_ids: [],
              start_frame_extraction: { source_segment_id: "e".repeat(32), source_video_asset_id: null, state: "shared_boundary", message: "该首帧与上一段尾帧共享，不能从上一段视频抽取；请先拆开边界。" },
            },
            {
              segment_id: "9".repeat(32),
              start_keyframe_id: "3".repeat(32),
              end_keyframe_id: "4".repeat(32),
              start_enabled: true,
              end_enabled: true,
              reference_asset_ids: [],
              start_frame_extraction: { source_segment_id: "7".repeat(32), source_video_asset_id: null, state: "shared_boundary", message: "该首帧与上一段尾帧共享，不能从上一段视频抽取；请先拆开边界。" },
            },
          ],
        },
      },
    );
    await waitFor(() => expect(screen.getAllByText("首帧")).toHaveLength(1));
    expect(screen.getAllByText("尾帧")).toHaveLength(1);
    const manualPlanButtons = screen.getAllByRole("button", {
      name: "手动修改关键帧计划",
    });
    expect(manualPlanButtons).toHaveLength(2);
    fireEvent.click(manualPlanButtons[0]);
    const manualPlan = screen.getByRole("dialog", {
      name: "手动修改首帧关键帧计划",
    });
    expect(within(manualPlan).getByText("手工图片引用")).toBeInTheDocument();
    expect(
      within(manualPlan).getByText("调整已选的 1 张图片"),
    ).toBeInTheDocument();
    expect(within(manualPlan).getByAltText(/手工引用图1/)).toHaveAttribute(
      "src",
      "/scene.png",
    );
    expect(within(manualPlan).queryByLabelText("地点视图使用方式")).toBeNull();
    fireEvent.change(
      within(manualPlan).getByLabelText("静态画面提示词（自由编写）"),
      { target: { value: "角色尚未迈步，海风掠过。" } },
    );
    fireEvent.click(
      within(manualPlan).getByRole("button", { name: "保存关键帧计划" }),
    );
    expect(onSaveKeyframe).toHaveBeenCalledWith(
      "1".repeat(32),
      "e".repeat(32),
      "角色尚未迈步，海风掠过。",
      [],
      [],
      [sceneAssetId],
    );
    fireEvent.click(within(manualPlan).getByRole("button", { name: "关闭" }));
    fireEvent.click(
      screen.getByRole("button", { name: "查看全图：首帧 @ffffff" }),
    );
    expect(
      screen.getByRole("dialog", { name: "首帧 @ffffff全图" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭全图" }));
    expect(
      screen.queryByRole("dialog", { name: "首帧 @ffffff全图" }),
    ).not.toBeInTheDocument();
    const inactiveEnd = screen.getByRole("button", { name: "激活尾帧" });
    expect(inactiveEnd).toHaveAttribute("aria-pressed", "false");
    expect(inactiveEnd.closest("article")).toHaveClass("is-disabled");
    expect(
      within(inactiveEnd.closest("article")!).getByRole("button", {
        name: "生成关键帧",
      }),
    ).toBeDisabled();
    const onlyActiveStart = screen.getAllByRole("button", {
      name: "停用首帧",
    })[0];
    expect(onlyActiveStart).toBeEnabled();
    fireEvent.click(onlyActiveStart);
    expect(onSaveSegmentKeyframeActivation).toHaveBeenCalledWith(
      "e".repeat(32),
      false,
      false,
    );
    fireEvent.click(inactiveEnd);
    expect(onSaveSegmentKeyframeActivation).toHaveBeenCalledWith(
      "e".repeat(32),
      true,
      true,
    );
    expect(screen.getByText(/与下一 Segment 首帧共享/)).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("navigation",{name:"故事层级"})).getByRole("button",{name:/片段 2/}));
    expect(screen.getByText(/与上一 Segment 尾帧共享/)).toBeInTheDocument();
    const shareToggle = screen.getByRole("checkbox", { name: "与上一段尾帧共享" });
    expect(shareToggle).toBeChecked();
    expect(screen.queryByRole("button", { name: "从上一 seg 抽取" })).not.toBeInTheDocument();
    fireEvent.click(shareToggle);
    expect(onSaveSegmentKeyframeBoundary).toHaveBeenCalledWith("7".repeat(32), false);
    fireEvent.click(within(within(screen.getByRole("navigation",{name:"故事层级"})).getByRole("list",{name:"场景 1 的生成片段"})).getByRole("button",{name:/片段 3 · 镜头 2/}));
    expect(
      screen.getAllByText(/与上一 Segment 尾帧共享/).length,
    ).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/首帧与上一段尾帧是同一 Keyframe/)).toBeInTheDocument();
    fireEvent.click(within(within(screen.getByRole("navigation",{name:"故事层级"})).getByRole("list",{name:"场景 1 的生成片段"})).getByRole("button",{name:/片段 1/}));
    const frameSummary = screen.getByLabelText(
      "Scene 1 Segment 1 画面输入",
    );
    const frameDetails = frameSummary.closest("details");
    expect(frameDetails).toHaveAttribute("open");
    fireEvent.click(frameSummary);
    expect(frameDetails).not.toHaveAttribute("open");
    expect(screen.queryByText("先说清楚，再开始生成")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("旁白 Agent 指令")).not.toBeInTheDocument();
    expect(screen.queryByText("让旁白 Agent 调整参数")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("旁白 Agent 指令")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("脚本 Agent 指令")).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("navigation",{name:"故事层级"})).getByRole("button",{name:/场景 1 ·/}));
    expect(screen.getAllByText(/预计 4 秒/)).toHaveLength(3);
  });
  it("旁白审核展示实际参数和 WAV 时长，并要求明确选择候选", async () => {
    const sceneId = "c".repeat(32);
    const shotId = "d".repeat(32);
    const cueId = "7".repeat(32);
    const audioId = "8".repeat(32);
    const generationId = "9".repeat(32);
    const onSelectNarrationAudio = vi.fn();
    const onClearNarrationAudioSelection = vi.fn();
    const narrationSnapshot: StructuredDirectorSnapshot = {
      ...snapshot,
      status: "reviewing_narration",
      workspace_layers: {
        ...snapshot.workspace_layers,
        narration_unlocked: true,
      },
      allowed_actions: [
        "edit_narration",
        "generate_narration",
        "generate_narration_batch",
        "select_narration_audio",
      ],
      reference_library: {
        ...snapshot.reference_library,
        narrator: {
          id: "6".repeat(32),
          name: "解说员",
          zh: { voice_description: "克制而轻松", voice_reference_asset_id: null, voice_reference_transcript: null },
          en: { voice_description: "Restrained and easy", voice_reference_asset_id: null, voice_reference_transcript: null },
        },
      },
      assets: [
        ...snapshot.assets,
        {
          id: audioId,
          media_type: "audio/wav",
          image_category: null,
          byte_count: 128,
          duration_seconds: 3.553,
          content_url: "/narration.wav",
          is_in_use: false,
          usage_reasons: [],
          retains_derived_assets_on_delete: false,
          allowed_actions: [],
        },
      ],
      generations: [
        {
          id: generationId,
          kind: "narration_audio",
          language: "zh",
          operation: "synthesize",
          target_id: cueId,
          phase: "succeeded",
          progress: 1,
          message: "旁白生成完成。",
          prompt_text: "搜索范围正在远离答案。",
          input_asset_ids: [],
          sample_text: "参考音频完整文字稿。",
          seed: 42,
          output_asset_id: audioId,
          error_code: null,
          cancellation_requested: false,
          retry_of: null,
          dismissed: false,
          allowed_actions: ["select_narration_audio", "dismiss_history"],
        },
      ],
      director_script: {
        revision: 1,
        source_reference_revision: 7,
        production_baseline_revision: null,
        production_baseline_scenes: null,
        scenes: [
          {
            id: sceneId,
            title: "客厅搜索",
            summary: "哥哥寻找零食。",
            setting: "午后的客厅。",
            driver: "narration",
      location_id: null,
      state_id: null,
            narration_cues: [
              {
                id: cueId,
                zh: {
                  text: "搜索范围正在远离答案。",
                  seed: 42,
                  selected_audio_asset_id: null,
                  recipe_params: {},
                  selected_duration_seconds: null,
                },
                en: {
                  text: "The search is drifting away from the answer.",
                  seed: 42,
                  selected_audio_asset_id: null,
                  recipe_params: {},
                  selected_duration_seconds: null,
                },
                timing_language: null,
                timing_seconds: null,
              },
            ],
            shots: [
              {
                id: shotId,
                visible_character_ids: ["b".repeat(32)],
                composition: "中景。",
                camera_movement: "固定。",
                action: "哥哥寻找零食。",
                audio_direction: "室内底声。",
                transition_in: null,
              }],
            segments: [{ shot_ids: [shotId],
                    id: "e".repeat(32),
                    duration_estimate_seconds: 2,
                    action: "哥哥低头翻找。",
                    dialogue_lines: [],
                    boundary_from_previous: null,
                  }],
          },
        ],
      },
    };
    const view = renderWorkspace(
      { onSelectNarrationAudio, onClearNarrationAudioSelection },
      narrationSnapshot,
    );
    fireEvent.click(screen.getByRole("button",{name:"项目概览"}));
    expect(screen.getByLabelText("旁白选择进度")).toHaveTextContent(
      "0/1 旁白已选齐中英文音频",
    );
    expect(
      screen.queryByRole("button", { name: "确认当前旁白与时长" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/请先为全部旁白选择中文与英文音频/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button",{name:/场景 1 ·/}));
    fireEvent.click(screen.getByText("旁白编辑、生成与候选"));
    expect(screen.getByText(/3.553/)).toBeInTheDocument();
    expect(screen.getByText("seed 42")).toBeInTheDocument();
    const narrationCard = document.querySelector("details.narration-cue-card");
    const narrationSummary = narrationCard?.querySelector("summary");
    expect(narrationCard).toHaveAttribute("open");
    fireEvent.click(narrationSummary!);
    expect(narrationCard).not.toHaveAttribute("open");
    fireEvent.click(narrationSummary!);
    // 候选卡片外壳由列表提供；内容不能再套一层同名卡片。
    const narrationCandidate = screen.getByText("seed 42").closest("article")!;
    expect(narrationCandidate).toHaveClass("narration-candidate");
    expect(narrationCandidate.querySelector(".narration-candidate")).toBeNull();
    expect(narrationCandidate.querySelector(".narration-candidate-body")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "选择这条" }));
    expect(onSelectNarrationAudio).toHaveBeenCalledWith(
      sceneId,
      cueId,
      generationId,
    );
    // 中英文各有一组参数；第一组是中文。
    expect(screen.getAllByLabelText("Seed")[0]).toHaveValue(42);
    const retried = structuredClone(narrationSnapshot);
    retried.generations.push({
      ...retried.generations[0],
      id: "a".repeat(32),
      seed: 43,
    });
    view.rerenderSnapshot(retried);
    expect(screen.getAllByLabelText("Seed")[0]).toHaveValue(43);
    expect(screen.getByRole("button", { name: "保存参数" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "生成中文候选" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "生成英文候选" })).toBeEnabled();
    expect(screen.queryByText("保存这次上游脚本修改")).not.toBeInTheDocument();
    expect(document.querySelector("details.narration-cue-card")).toBe(
      narrationCard,
    );
    const selected = structuredClone(retried);
    selected.director_script!.scenes[0].narration_cues[0].zh!.selected_audio_asset_id =
      audioId;
    selected.director_script!.scenes[0].narration_cues[0].en!.selected_audio_asset_id =
      audioId;
    selected.workflow.current_stage = "visual_production";
    selected.workflow.stage_status = "awaiting_unlock";
    selected.workflow.required_next_actions = [];
    view.rerenderSnapshot(selected);
    const englishPanel = screen.getByRole("region", { name: "英文旁白" });
    fireEvent.click(within(englishPanel).getByRole("button", { name: "取消选用" }));
    expect(within(englishPanel).getByText(/相关时序与装配失效/)).toBeInTheDocument();
    fireEvent.click(within(englishPanel).getByRole("button", { name: "保留当前音频" }));
    expect(onClearNarrationAudioSelection).not.toHaveBeenCalled();
    fireEvent.click(within(englishPanel).getByRole("button", { name: "取消选用" }));
    fireEvent.click(within(englishPanel).getByRole("button", { name: "确认取消选用" }));
    expect(onClearNarrationAudioSelection).toHaveBeenCalledWith(sceneId, cueId, "en");
    fireEvent.click(screen.getByRole("button",{name:"项目概览"}));
    expect(screen.getByLabelText("旁白选择进度")).toHaveTextContent(
      "1/1 旁白已选齐中英文音频",
    );
    expect(
      screen.queryByText(/请先为全部旁白选择中文与英文音频/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("alert", { name: "旁白时长冲突" }),
    ).not.toBeInTheDocument();
    const awaitingShotPlan = structuredClone(selected);
    awaitingShotPlan.director_script!.scenes[0].shots = [];
    awaitingShotPlan.workflow.stage_status = "awaiting_plan";
    awaitingShotPlan.workflow.required_next_actions = [
      {
        action: "script.apply_operations",
        tool: "edit_script",
        target_ids: [sceneId],
        human_only: false,
        requires_explicit_user_request: true,
        purpose: "plan_shots_from_selected_narration_timing",
        reason: "narration_shot_plan_required",
      },
    ];
    view.rerenderSnapshot(awaitingShotPlan);
    expect(
      screen.getByText(/请先让 Agent 按 Core 提供的目标画面时长规划每个/),
    ).toBeInTheDocument();
    const laterStage = {
      ...selected,
      status: "reviewing_videos" as const,
      workspace_layers: { ...selected.workspace_layers, videos_unlocked: true },
    };
    view.rerenderSnapshot(laterStage);
    fireEvent.click(screen.getByRole("button",{name:"项目概览"}));
    expect(screen.getByLabelText("旁白选择进度")).toHaveTextContent(
      "1/1 旁白已选齐中英文音频",
    );
    view.rerenderSnapshot({
      ...narrationSnapshot,
      workspace_layers: {
        ...narrationSnapshot.workspace_layers,
        narration_unlocked: false,
      },
    });
    expect(screen.queryByLabelText("旁白选择进度")).not.toBeInTheDocument();
  });
  it("最终候选选择后仍需用户单独批准", async () => {
    const onApproveFinalVideo = vi.fn();
    const segmentId = "e".repeat(32);
    const videoAssetId = "f".repeat(32);
    const generationId = "9".repeat(32);
    const scene: Scene = {
      driver: "drama",
      location_id: null,
      state_id: null,
      id: "c".repeat(32),
      title: "终场",
      summary: "角色离开画面。",
      setting: "傍晚站台。",
      narration_cues: [],
      shots: [
        {
          id: "d".repeat(32),
          visible_character_ids: ["b".repeat(32)],
          composition: "远景。",
          camera_movement: "固定。",
          action: "角色离开。",
          audio_direction: "环境声。",
          transition_in: null,
        }],
      segments: [{ shot_ids: ["d".repeat(32)],
              id: segmentId,
              duration_estimate_seconds: 3,
              action: "角色走出画面。",
              dialogue_lines: [],
              boundary_from_previous: null,
            }],
    };
    renderWorkspace(
      { onApproveFinalVideo },
      {
        ...snapshot,
        status: "reviewing_final",
        workspace_layers: {
          narration_unlocked: true,
          keyframes_unlocked: true,
          videos_unlocked: true,
          final_assembly_unlocked: true,
        },
        allowed_actions: [
          "generate_final_video",
          "select_final_video",
          "approve_final_video",
        ],
        assets: [
          ...snapshot.assets,
          {
            id: videoAssetId,
            media_type: "video/mp4",
            image_category: null,
            byte_count: 64,
            duration_seconds: 3,
            content_url: "/final.mp4",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
        ],
        generations: [
          {
            id: generationId,
            kind: "final_video",
            language: "zh",
            operation: "assemble",
            target_id: "1".repeat(32),
            phase: "succeeded",
            progress: 1,
            message: "成片装配完成。",
            prompt_text: "确定性装配",
            input_asset_ids: [],
            sample_text: null,
            seed: null,
            output_asset_id: videoAssetId,
            error_code: null,
            cancellation_requested: false,
            retry_of: null,
            dismissed: false,
            allowed_actions: ["select_final_video", "dismiss_history"],
          },
        ],
        director_script: {
          revision: 4,
          source_reference_revision: 7,
          production_baseline_revision: 4,
          production_baseline_scenes: [scene],
          scenes: [scene],
        },
        location_library: { locations: [] },
        keyframe_plan: {
          source_script_revision: 4,
          keyframes: [],
          segments: [],
        },
        video_plan: {
          source_script_revision: 4,
          segments: [
            videoFixture({segment_id: segmentId,prompt_text: "离场。",selected_asset_id: videoAssetId,upscaled_asset_id: null,active_recipe: "minimax_h3.fl2va", recipes: {["minimax_h3.fl2va"]: {bindings: {additional_images: [],reference_audios: [],reference_videos: []}, params: {}}}}, videoState("minimax_h3.fl2va")),
          ],
        },
        final_assembly: {
          source_script_revision: 4,
          clips: [
            {
              scene_id: scene.id,
              zh_asset_id: videoAssetId,
              en_asset_id: videoAssetId,
              transition_from_previous: null,
            },
          ],
          selected_zh_asset_id: videoAssetId,
          selected_en_asset_id: videoAssetId,
        },
        final_approval: null,
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "批准中英成片" }));
    expect(onApproveFinalVideo).toHaveBeenCalledOnce();
    expect(document.querySelector(`video[src="/final.mp4"]`)).toBeInTheDocument();
  });
  it("视频层解锁后显示完整可编辑 Segment 视频卡", async () => {
    const segmentId = "e".repeat(32);
    const startId = "2".repeat(32);
    const endId = "3".repeat(32);
    const startAssetId = "4".repeat(32);
    const endAssetId = "5".repeat(32);
    const voiceAssetId = "6".repeat(32);
    const onSaveSegmentVideoInputs = vi.fn();
    const onSaveSegmentVideoRecipe = vi.fn();
    const onGenerateSegmentVideo = vi.fn();
    const onAttachSegmentVideoCandidate = vi.fn();
    const onGenerateSceneFinal = vi.fn();
    const onSelectKeyframe = vi.fn();
    const onSaveKeyframe = vi.fn();
    const onSaveSegmentKeyframeReferences = vi.fn();
    const previewKeyframe = vi
      .spyOn(structuredDirectorApi, "previewKeyframe")
      .mockResolvedValue({
        reference_prompt: "图片引用：\n第 1 张输入图「海岸参考.png」。",
        instruction: "完整关键帧提示词",
        ready: true,
        operation: "edit",
        attachments: [
          {
            asset_id: "a".repeat(32),
            display_name: "海岸参考.png",
            content_url: "/asset.png",
            role: "source_image",
            input_roles: ["辅助参考"],
            purpose: "用户为本 Segment 选择的辅助参考；只约束对应局部细节。",
          },
        ],
      });
    const scene: Scene = {
      driver: "drama",
      location_id: null,
      state_id: null,
      id: "c".repeat(32),
      title: "走廊",
      summary: "角色走过走廊。",
      setting: "夜间走廊。",
      narration_cues: [],
      scene_final: {
        provider_available: true, reason: "已就绪。",
        ready: true,
        zh: { active_generation_id: null, latest_succeeded_generation_id: null, current_asset_id: null, outdated: false },
        en: { active_generation_id: null, latest_succeeded_generation_id: null, current_asset_id: null, outdated: false },
      },
      shots: [
        {
          id: "d".repeat(32),
          visible_character_ids: ["b".repeat(32)],
          composition: "中景。",
          camera_movement: "跟随。",
          action: "角色前进。",
          audio_direction: "脚步声。",
          transition_in: null,
        }],
      segments: [{ shot_ids: ["d".repeat(32)],
              id: segmentId,
              duration_estimate_seconds: 4,
              action: "角色走到门边。",
              dialogue_lines: [
                {
                  id: "d".repeat(32),
                  character_id: "b".repeat(32),
                  speaker_label: null,
                  voice_description: null,
                  text: "到了。",
                  delivery: "低声",
                },
              ],
              boundary_from_previous: null,
            }],
    };
    renderWorkspace(
      {
        onSaveSegmentVideoInputs,
        onSaveSegmentVideoRecipe,
        onGenerateSegmentVideo,
        onAttachSegmentVideoCandidate,
        onSelectKeyframe,
        onSaveKeyframe,
        onSaveSegmentKeyframeReferences,
        onGenerateSceneFinal,
        pendingSegmentVideoId: segmentId,
      },
      {
        ...snapshot,
        status: "reviewing_videos",
        active_director_run: {
          id: "f".repeat(32),
          kind: "director",
          status: "waiting_jobs",
          waiting_reason: "等待当前步骤的 Generation。",
          created_at: "2026-09-09T12:00:00Z",
          updated_at: "2026-09-09T12:01:00Z",
        },
        workspace_layers: {
          narration_unlocked: true,
          keyframes_unlocked: true,
          videos_unlocked: true,
          final_assembly_unlocked: false,
        },
        allowed_actions: [
          "edit_keyframe_references",
          "select_keyframe",
          "edit_segment_video_plan",
          "generate_segment_video",
          "attach_segment_video_candidate",
          "generate_scene_final",
        ],
        provider_availability: {
          ...snapshot.provider_availability,
          video_generation: true,
          final_assembly: true,
        },
        reference_library: {
          ...snapshot.reference_library,
          characters: snapshot.reference_library.characters.map(
            (character) => ({
              ...character,
              voice_reference_asset_id: voiceAssetId,
            }),
          ),
        },
        assets: [
          ...snapshot.assets,
          {
            id: startAssetId,
            media_type: "image/png",
            image_category: null,
            byte_count: 20,
            duration_seconds: null,
            content_url: "/start.png",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
          {
            id: endAssetId,
            media_type: "image/png",
            image_category: null,
            byte_count: 20,
            duration_seconds: null,
            content_url: "/end.png",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
          {
            id: voiceAssetId,
            media_type: "audio/wav",
            image_category: null,
            byte_count: 20,
            duration_seconds: 2,
            content_url: "/voice.wav",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
          {
            id: "7".repeat(32),
            media_type: "video/mp4",
            image_category: null,
            byte_count: 64,
            duration_seconds: 4,
            content_url: "/candidate.mp4",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
          {
            id: "0".repeat(32),
            media_type: "video/mp4",
            image_category: null,
            byte_count: 72,
            duration_seconds: 5,
            display_name: "海雾备选.mp4",
            content_url: "/library-candidate.mp4",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
          {
            id: "12".repeat(16),
            media_type: "video/mp4",
            image_category: null,
            byte_count: 2048,
            duration_seconds: 12.5,
            display_name: "前作长片段.mp4",
            content_url: "/long-library-candidate.mp4",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
        ],
        generations: [
          {
            id: "8".repeat(32),
            kind: "segment_video",
            language: null,
            operation: "render",
            target_id: segmentId,
            phase: "succeeded",
            progress: 1,
            message:
              "生成总用时 65.2 秒（含模型准备、采样及产物处理，不含排队）。",
            prompt_text: "角色平稳走到门边。",
            input_asset_ids: [startAssetId],
            sample_text: null,
            seed: "9007199254740993",
            output_asset_id: "7".repeat(32),
            error_code: null,
            cancellation_requested: false,
            retry_of: null,
            dismissed: false,
            allowed_actions: ["select_segment_video", "dismiss_history"],
          },
          {
            id: "9".repeat(32),
            kind: "segment_video",
            language: null,
            operation: "render",
            target_id: segmentId,
            phase: "submission_uncertain",
            progress: 0,
            message: "问题出在提交传输：Core 无法确认请求是否到达 H3 服务。",
            prompt_text: "角色平稳走到门边。",
            input_asset_ids: [startAssetId],
            sample_text: null,
            seed: "8898",
            output_asset_id: null,
            error_code: "transport_error",
            cancellation_requested: false,
            retry_of: null,
            dismissed: false,
            allowed_actions: ["dismiss_history"],
          },
        ],
        director_script: {
          revision: 4,
          source_reference_revision: 7,
          production_baseline_revision: 4,
          production_baseline_scenes: [scene],
          scenes: [scene],
        },
        keyframe_plan: {
          source_script_revision: 4,
          keyframes: [
            {
              id: startId,
              owner_segment_id: segmentId,
              predecessor_keyframe_id: null,
              prompt_text: "起点",
              visible_character_ids: [], character_references: [],
              selected_asset_id: startAssetId,
            },
            {
              id: endId,
              owner_segment_id: segmentId,
              predecessor_keyframe_id: startId,
              prompt_text: "终点",
              visible_character_ids: [], character_references: [],
              selected_asset_id: null,
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
          source_script_revision: 4,
          segments: [
            videoFixture({segment_id: segmentId,prompt_text: "角色平稳走到门边。",selected_asset_id: null,upscaled_asset_id: null,active_recipe: "minimax_h3.fl2va", recipes: {["minimax_h3.fl2va"]: {bindings: {additional_images: [],reference_audios: [],reference_videos: []}, params: {}}}}, { ...videoState("minimax_h3.fl2va"), duration_seconds: 4 }),
          ],
        },
      },
    );
    expect(screen.getByRole("heading", { name: "FL2VA" })).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("navigation",{name:"故事层级"})).getByRole("button",{name:/场景 1 ·/}));
    fireEvent.change(screen.getByRole("slider", { name: "视频自带音频音量" }), {
      target: { value: "0.5" },
    });
    fireEvent.change(screen.getByRole("slider", { name: "旁白音频音量" }), {
      target: { value: "0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成中英 Scene 成片" }));
    expect(onGenerateSceneFinal).toHaveBeenCalledWith(scene.id, 0.5, 0);
    fireEvent.click(within(screen.getByRole("navigation",{name:"故事层级"})).getByRole("button",{name:/片段 1/}));
    fireEvent.click(screen.getByText("查看或编辑 视频提示词"));
    expect(screen.getByText(/生成总用时 65.2 秒/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("未能连接视频生成服务");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "本次没有生成视频 · Seed 8898",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "将此 Seed 填回输入框" }),
    );
    expect(
      screen.getByRole("textbox", { name: "本次 Seed（留空自动递增）" }),
    ).toHaveValue("8898");
    fireEvent.change(
      screen.getByRole("textbox", { name: "本次 Seed（留空自动递增）" }),
      {
        target: { value: "" },
      },
    );
    expect(screen.getByText("正在准备 Generation")).toBeInTheDocument();
    expect(
      screen.getByText(/使用已保存的当前视频 提示词提交视频任务/),
    ).toBeInTheDocument();
    const generationMode = screen.getByLabelText(
      `Segment @${segmentId.slice(0, 6)} 生成模式`,
    );
    expect(generationMode).toHaveValue("minimax_h3.fl2va");
    expect(
      within(generationMode).getByRole("option", { name: "Ref2VA" }),
    ).toBeEnabled();
    fireEvent.change(generationMode, { target: { value: "minimax_h3.ref2va" } });
    expect(onSaveSegmentVideoRecipe).toHaveBeenCalledWith(segmentId, "minimax_h3.ref2va");
    const videoSummary = screen.getByLabelText(
      `Segment @${segmentId.slice(0, 6)} 视频`,
    );
    const videoDetails = videoSummary.closest("details");
    expect(videoDetails).toHaveAttribute("open");
    fireEvent.click(videoSummary);
    expect(videoDetails).not.toHaveAttribute("open");
    fireEvent.click(videoSummary);
    expect(screen.getAllByRole("navigation", {name:"故事层级"})).toHaveLength(1);
    expect(
      within(videoDetails as HTMLElement).queryAllByRole("img"),
    ).toHaveLength(1);
    expect(
      within(videoDetails as HTMLElement).getByText("仅首帧"),
    ).toBeInTheDocument();
    const startSlot = document.querySelector<HTMLElement>(
      ".keyframe-slot.is-start",
    )!;
    fireEvent.click(
      within(startSlot).getByRole("button", { name: "手动修改关键帧计划" }),
    );
    const manualDialog = screen.getByRole("dialog", {
      name: "手动修改首帧关键帧计划",
    });
    fireEvent.click(
      within(manualDialog).getByRole("button", { name: "从资产库选择图片" }),
    );
    const referencePicker = screen.getByRole("dialog", {
      name: "从资产库选择关键帧参考图片",
    });
    fireEvent.click(
      within(referencePicker).getByRole("button", {
        name: "选择 海岸参考.png",
      }),
    );
    expect(
      within(referencePicker).getByRole("button", {
        name: "取消选择 海岸参考.png",
      }),
    ).toHaveClass("is-selected");
    expect(
      within(referencePicker).getByRole("button", {
        name: "取消选择 海岸参考.png",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(
      within(referencePicker).getByRole("button", { name: "完成" }),
    );
    fireEvent.click(
      within(manualDialog).getByRole("button", { name: "保存图片引用" }),
    );
    expect(onSaveSegmentKeyframeReferences).toHaveBeenCalledWith(segmentId, [
      "a".repeat(32),
    ]);
    const visibleCharacter = within(manualDialog).getByRole("checkbox", {
      name: "小满",
    });
    expect(visibleCharacter).toBeEnabled();
    fireEvent.click(visibleCharacter);
    fireEvent.change(within(manualDialog).getByDisplayValue("起点"), {target:{value:"小满站在冷光海岸边。"}});
    fireEvent.click(
      within(manualDialog).getByRole("button", { name: "保存关键帧计划" }),
    );
    expect(onSaveKeyframe).toHaveBeenCalledWith(
      startId,
      segmentId,
      "小满站在冷光海岸边。",
      ["b".repeat(32)],
      [],
      ["a".repeat(32)],
    );
    await waitFor(() =>
      expect(previewKeyframe).toHaveBeenCalledWith(
        project.id,
        snapshot.revision,
        startId,
        segmentId,
        "小满站在冷光海岸边。",
        ["b".repeat(32)],
        [],
        ["a".repeat(32)],
      ),
    );
    expect(
      within(manualDialog).getByText("当前实际图片输入"),
    ).toBeInTheDocument();
    expect(
      within(manualDialog).getByAltText(`实际输入图1 海岸参考.png`),
    ).toHaveAttribute("src", "/asset.png");
    fireEvent.click(
      screen.getAllByRole("button", { name: "从资产库选择关键帧" })[0],
    );
    const keyframePicker = screen.getByRole("dialog", {
      name: "从资产库选择首帧",
    });
    fireEvent.click(
      within(keyframePicker).getByRole("button", { name: "选择 海岸参考.png" }),
    );
    expect(onSelectKeyframe).toHaveBeenCalledWith(startId, "a".repeat(32));
    expect(
      screen.queryByRole("dialog", { name: "从资产库选择首帧" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "生成一个视频候选" }),
    ).toBeEnabled();
    fireEvent.click(
      screen.getByRole("button", { name: "从资产库增加候选" }),
    );
    const videoAssetPicker = screen.getByRole("dialog", {
      name: "从资产库增加视频候选",
    });
    expect(
      within(videoAssetPicker).getByRole("button", {
        name: "已是候选 项目视频",
      }),
    ).toBeDisabled();
    // 超过推荐预算的项目视频不再被隐藏或标注，直接可挂接。
    const longCandidate = within(videoAssetPicker).getByRole("button", {
      name: "增加 前作长片段.mp4",
    });
    expect(longCandidate).toBeEnabled();
    fireEvent.click(longCandidate);
    expect(onAttachSegmentVideoCandidate).toHaveBeenCalledWith(
      segmentId,
      "12".repeat(16),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "从资产库增加候选" }),
    );
    fireEvent.click(
      within(
        screen.getByRole("dialog", { name: "从资产库增加视频候选" }),
      ).getByRole("button", {
        name: "增加 海雾备选.mp4",
      }),
    );
    expect(onAttachSegmentVideoCandidate).toHaveBeenCalledWith(
      segmentId,
      "0".repeat(32),
    );
    expect(
      screen.queryByRole("dialog", { name: "从资产库增加视频候选" }),
    ).not.toBeInTheDocument();
    const seedInput = screen.getByRole("textbox", {
      name: "本次 Seed（留空自动递增）",
    });
    fireEvent.click(screen.getByRole("button", { name: "生成一个视频候选" }));
    expect(onGenerateSegmentVideo).toHaveBeenLastCalledWith(
      segmentId,
      undefined,
    );
    fireEvent.change(seedInput, { target: { value: "9007199254740993" } });
    fireEvent.click(screen.getByRole("button", { name: "生成一个视频候选" }));
    expect(onGenerateSegmentVideo).toHaveBeenLastCalledWith(
      segmentId,
      "9007199254740993",
    );
    for (const invalidSeed of ["-1", "1.5", "9223372036854775808"]) {
      fireEvent.change(seedInput, { target: { value: invalidSeed } });
      expect(seedInput).toHaveAttribute("aria-invalid", "true");
      expect(
        screen.getByRole("button", { name: "生成一个视频候选" }),
      ).toBeDisabled();
    }
    fireEvent.change(seedInput, { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "生成一个视频候选" }));
    expect(onGenerateSegmentVideo).toHaveBeenLastCalledWith(segmentId, "0");
    fireEvent.change(seedInput, { target: { value: "" } });
    expect(
      screen.getByRole("textbox", { name: "当前 视频提示词" }),
    ).not.toHaveAttribute("readonly");
    expect(
      screen.getByRole("textbox", { name: "当前 视频提示词" }),
    ).not.toHaveAttribute("readonly");
    fireEvent.change(
      screen.getByRole("textbox", {
        name: "当前 视频提示词",
      }),
      {
        target: { value: "" },
      },
    );
    expect(screen.getByRole("button", {name:"生成一个视频候选"})).toBeDisabled();
    fireEvent.change(
      screen.getByRole("textbox", {
        name: "当前 视频提示词",
      }),
      {
        target: { value: "角色平稳走到门边。" },
      },
    );
    expect(
      screen.getByRole("button", { name: "生成一个视频候选" }),
    ).toBeEnabled();
    fireEvent.change(
      screen.getByRole("textbox", {
        name: "当前 视频提示词",
      }),
      { target: { value: "还没有保存的新正文" } },
    );
    expect(
      screen.getByRole("button", { name: "生成一个视频候选" }),
    ).toBeDisabled();
    expect(screen.getByText(/当前提示词有未保存修改/)).toBeInTheDocument();
    fireEvent.change(
      screen.getByRole("textbox", {
        name: "当前 视频提示词",
      }),
      { target: { value: "角色平稳走到门边。" } },
    );
    expect(screen.getByText("4.0 秒 · 16:9")).toBeInTheDocument();
    for (const video of videoDetails?.querySelectorAll("video") ?? []) {
      expect(video).toHaveAttribute("preload", "metadata");
      expect(video).toHaveAttribute("playsinline");
      expect(video).not.toHaveAttribute("muted");
    }

    expect(screen.queryByLabelText("Director Agent 固定侧边栏")).not.toBeInTheDocument();

    const prompt = screen.getByRole("textbox", { name: "当前 视频提示词" });
    fireEvent.change(prompt, { target: { value: "角色停在门边并回头。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存视频计划" }));
    expect(onSaveSegmentVideoInputs).toHaveBeenCalledWith(
      segmentId,
      "角色停在门边并回头。",
      {bindings: {additional_images: [], reference_audios: [], reference_videos: []}, params: {}},
    );
    expect(screen.queryByRole("button", {name:"一键生成成片"})).not.toBeInTheDocument();
    expect(screen.getByRole("heading", {name:/片段 1/})).toBeInTheDocument();
  });

  it("Ref2VA 使用与角色卡解耦的有序通用参考音频", async () => {
    const sceneId = "c".repeat(32);
    const shotId = "d".repeat(32);
    const segmentId = "e".repeat(32);
    const startId = "1".repeat(32);
    const endId = "2".repeat(32);
    const endAssetId = "3".repeat(32);
    const firstVoiceId = "4".repeat(32);
    const secondVoiceId = "5".repeat(32);
    const firstCharacterId = "6".repeat(32);
    const secondCharacterId = "7".repeat(32);
    const onGenerate = vi.fn();
    const scene: Scene = {
      driver: "drama",
      location_id: null,
      state_id: null,
      id: sceneId,
      title: "尾巴上的证据",
      summary: "两只猫当面对质。",
      setting: "客厅。",
      narration_cues: [],
      scene_final: {
        provider_available: true, reason: "已就绪。",
        ready: false,
        zh: { active_generation_id: null, latest_succeeded_generation_id: null, current_asset_id: null, outdated: false },
        en: { active_generation_id: null, latest_succeeded_generation_id: null, current_asset_id: null, outdated: false },
      },
      shots: [
        {
          id: shotId,
          visible_character_ids: [firstCharacterId, secondCharacterId],
          composition: "双猫中近景。",
          camera_movement: "固定。",
          action: "两只猫对话。",
          audio_direction: "安静室内。",
          transition_in: null,
        }],
      segments: [{ shot_ids: [shotId],
              id: segmentId,
              duration_estimate_seconds: 5,
              action: "Comi 回应，锦鲤追问。",
              dialogue_lines: [
                {
                  id: "d".repeat(32),
                  character_id: firstCharacterId,
                  speaker_label: null,
                  voice_description: null,
                  text: "嗯？",
                  delivery: "懒散",
                },
                {
                  id: "e".repeat(32),
                  character_id: secondCharacterId,
                  speaker_label: null,
                  voice_description: null,
                  text: "为什么？",
                  delivery: "严肃",
                },
              ],
              boundary_from_previous: null,
            }],
    };
    renderWorkspace(
      {
        onGenerateSegmentVideo: onGenerate,
      },
      {
        ...snapshot,
        status: "reviewing_videos",
        workspace_layers: {
          narration_unlocked: true,
          keyframes_unlocked: true,
          videos_unlocked: true,
          final_assembly_unlocked: false,
        },
        allowed_actions: [
          "edit_segment_video_plan",
          "generate_segment_video",
        ],
        provider_availability: {
          ...snapshot.provider_availability,
          video_generation: true,
        },
        reference_library: {
          ...snapshot.reference_library,
          characters: [
            {
              ...snapshot.reference_library.characters[0],
              id: firstCharacterId,
              name: "Comi",
              voice_reference_asset_id: null,
            },
            {
              ...snapshot.reference_library.characters[0],
              id: secondCharacterId,
              name: "锦鲤",
              voice_reference_asset_id: null,
            },
          ],
        },
        assets: [
          {
            id: endAssetId,
            media_type: "image/png",
            image_category: null,
            byte_count: 20,
            duration_seconds: null,
            content_url: "/end.png",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
          {
            id: firstVoiceId,
            media_type: "audio/wav",
            image_category: null,
            byte_count: 20,
            duration_seconds: 2,
            content_url: "/comi.wav",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
          {
            id: secondVoiceId,
            media_type: "audio/wav",
            image_category: null,
            byte_count: 20,
            duration_seconds: 2,
            content_url: "/jinli.wav",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
        ],
        director_script: {
          revision: 4,
          source_reference_revision: 7,
          production_baseline_revision: 4,
          production_baseline_scenes: [scene],
          scenes: [scene],
        },
        keyframe_plan: {
          source_script_revision: 4,
          keyframes: [
            {
              id: startId,
              owner_segment_id: segmentId,
              predecessor_keyframe_id: null,
              prompt_text: "起点",
              visible_character_ids: [], character_references: [],
              selected_asset_id: null,
            },
            {
              id: endId,
              owner_segment_id: segmentId,
              predecessor_keyframe_id: startId,
              prompt_text: "终点",
              visible_character_ids: [], character_references: [],
              selected_asset_id: endAssetId,
            },
          ],
          segments: [
            {
              segment_id: segmentId,
              start_keyframe_id: startId,
              end_keyframe_id: endId,
              start_enabled: false,
              end_enabled: true,
              reference_asset_ids: [],
              start_frame_extraction: { source_segment_id: null, source_video_asset_id: null, state: "unavailable", message: "无上一段。" },
            },
          ],
        },
        video_plan: {
          source_script_revision: 4,
          segments: [
            videoFixture({segment_id: segmentId,prompt_text: "双角色对白提示词。",selected_asset_id: null,upscaled_asset_id: null,active_recipe: "minimax_h3.ref2va", recipes: {["minimax_h3.ref2va"]: {bindings: {additional_images: [],reference_audios: [
                {
                  asset_id: firstVoiceId,
                  description: "Comi 的音色参考。",
                },
                {
                  asset_id: secondVoiceId,
                  description: "原样使用这段回应。",
                },
              ],reference_videos: []}, params: {}}}}, videoState("blocked")),
          ],
        },
      },
    );
    expect(
      screen.getByRole("heading", {name: "Ref2VA"}),
    ).toBeInTheDocument();
    expect(screen.getByText("<Audio 1>")).toBeInTheDocument();
    expect(screen.getByText("<Audio 2>")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "参考音频 1 描述" })).toHaveValue(
      "Comi 的音色参考。",
    );
    expect(screen.getByRole("textbox", { name: "参考音频 2 描述" })).toHaveValue(
      "原样使用这段回应。",
    );
    const mode = screen.getByLabelText(
      `Segment @${segmentId.slice(0, 6)} 生成模式`,
    );
    expect(within(mode).getByRole("option", { name: "FL2VA" })).toBeDisabled();
    expect(within(mode).getByRole("option", { name: "Ref2VA" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "生成一个视频候选" }));
    expect(onGenerate).toHaveBeenCalledWith(segmentId, undefined);
  });
  it("全部 Segment 视频齐备后由 Core 解锁一键成片", async () => {
    const onGenerateFinalVideo = vi.fn();
    const segmentId = "e".repeat(32);
    const videoAssetId = "f".repeat(32);
    const startId = "2".repeat(32);
    const endId = "3".repeat(32);
    const scene: Scene = {
      driver: "drama",
      location_id: null,
      state_id: null,
      id: "c".repeat(32),
      title: "终场",
      summary: "画面停下。",
      setting: "室内。",
      narration_cues: [],
      shots: [
        {
          id: "d".repeat(32),
          visible_character_ids: [],
          composition: "全景。",
          camera_movement: "固定。",
          action: "画面停下。",
          audio_direction: "环境声。",
          transition_in: null,
        }],
      segments: [{ shot_ids: ["d".repeat(32)],
              id: segmentId,
              duration_estimate_seconds: 3,
              action: "画面停下。",
              dialogue_lines: [],
              boundary_from_previous: null,
            }],
    };
    renderWorkspace(
      { onGenerateFinalVideo },
      {
        ...snapshot,
        status: "reviewing_videos",
        workspace_layers: {
          narration_unlocked: true,
          keyframes_unlocked: true,
          videos_unlocked: true,
          final_assembly_unlocked: false,
        },
        allowed_actions: ["generate_final_video"],
        provider_availability: {...snapshot.provider_availability, final_assembly: true},
        assets: [
          ...snapshot.assets,
          {
            id: videoAssetId,
            media_type: "video/mp4",
            image_category: null,
            byte_count: 64,
            duration_seconds: 3,
            content_url: "/segment.mp4",
            is_in_use: false,
            usage_reasons: [],
            retains_derived_assets_on_delete: false,
            allowed_actions: [],
          },
        ],
        director_script: {
          revision: 4,
          source_reference_revision: 7,
          production_baseline_revision: 4,
          production_baseline_scenes: [scene],
          scenes: [scene],
        },
        keyframe_plan: {
          source_script_revision: 4,
          keyframes: [
            {
              id: startId,
              owner_segment_id: segmentId,
              predecessor_keyframe_id: null,
              prompt_text: "起点",
              visible_character_ids: [], character_references: [],
              selected_asset_id: null,
            },
            {
              id: endId,
              owner_segment_id: segmentId,
              predecessor_keyframe_id: startId,
              prompt_text: "终点",
              visible_character_ids: [], character_references: [],
              selected_asset_id: null,
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
          source_script_revision: 4,
          segments: [
            videoFixture({segment_id: segmentId,prompt_text: "画面停下。",selected_asset_id: videoAssetId,upscaled_asset_id: null,active_recipe: "minimax_h3.fl2va", recipes: {["minimax_h3.fl2va"]: {bindings: {additional_images: [],reference_audios: [],reference_videos: []}, params: {}}}}, videoState("minimax_h3.fl2va")),
          ],
        },
      },
    );
    fireEvent.click(screen.getByRole("button",{name:"项目概览"}));
    expect(screen.getByLabelText("视频选择进度")).toHaveTextContent("1/1 Segment");
    fireEvent.click(screen.getByRole("button", { name: "一键生成成片" }));
    expect(onGenerateFinalVideo).toHaveBeenCalledOnce();
  });
  it("脚本返工使视频计划失效后仍保留每个 Segment 的视频卡", async () => {
    const segmentId = "e".repeat(32);
    const scene: Scene = {
      driver: "drama",
      location_id: null,
      state_id: null,
      id: "c".repeat(32),
      title: "返工场景",
      summary: "动作被修改。",
      setting: "室内。",
      narration_cues: [],
      shots: [
        {
          id: "d".repeat(32),
          visible_character_ids: [],
          composition: "中景。",
          camera_movement: "固定。",
          action: "角色停下。",
          audio_direction: "环境声。",
          transition_in: null,
        }],
      segments: [{ shot_ids: ["d".repeat(32)],
              id: segmentId,
              duration_estimate_seconds: 5,
              action: "角色停下。",
              dialogue_lines: [],
              boundary_from_previous: null,
            }],
    };
    renderWorkspace(
      {},
      {
        ...snapshot,
        status: "reviewing_script",
        workspace_layers: {
          narration_unlocked: true,
          keyframes_unlocked: true,
          videos_unlocked: true,
          final_assembly_unlocked: false,
        },
        director_script: {
          revision: 5,
          source_reference_revision: 7,
          production_baseline_revision: null,
          production_baseline_scenes: null,
          scenes: [scene],
        },
        keyframe_plan: null,
        video_plan: null,
      },
    );
    expect(screen.getByText("计划待重建")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("当前脚本 revision 的视频计划尚未重建。"),
    ).toBeDisabled();
    expect(screen.getByText(/之前的视频层仍然保留显示/)).toBeInTheDocument();
  });
  it("在视频进度卡中显示 s/iter，并为旧 Provider 消息补算速度", async () => {
    const sceneId = "c".repeat(32);
    const shotId = "d".repeat(32);
    const segmentId = "e".repeat(32);
    const keyframeId = "2".repeat(32);
    const endKeyframeId = "3".repeat(32);
    const assetId = "4".repeat(32);
    const generationId = "8".repeat(32);
    const scene: Scene = {
      driver: "drama",
      location_id: null,
      state_id: null,
      id: sceneId,
      title: "走廊",
      summary: "角色穿过走廊。",
      setting: "夜间走廊。",
      narration_cues: [],
      shots: [
        {
          id: shotId,
          visible_character_ids: [],
          composition: "中景。",
          camera_movement: "固定。",
          action: "角色前进。",
          audio_direction: "脚步声。",
          transition_in: null,
        }],
      segments: [{ shot_ids: [shotId],
              id: segmentId,
              duration_estimate_seconds: 4,
              action: "角色走到门边。",
              dialogue_lines: [],
              boundary_from_previous: null,
            }],
    };
    const first: StructuredDirectorSnapshot = {
      ...snapshot,
      status: "reviewing_videos",
      workspace_layers: {
        narration_unlocked: true,
        keyframes_unlocked: true,
        videos_unlocked: true,
        final_assembly_unlocked: false,
      },
      allowed_actions: ["edit_segment_video_plan"],
      provider_availability: {
        ...snapshot.provider_availability,
        video_generation: true,
      },
      assets: [
        ...snapshot.assets,
        {
          id: assetId,
          display_name: "首帧.png",
          media_type: "image/png",
          image_category: null,
          byte_count: 20,
          duration_seconds: null,
          content_url: "/start.png",
          is_in_use: false,
          usage_reasons: [],
          retains_derived_assets_on_delete: false,
          allowed_actions: [],
        },
      ],
      generations: [
        {
          id: generationId,
          kind: "segment_video",
          language: null,
          operation: "render",
          target_id: segmentId,
          phase: "running",
          progress: 0.475,
          message: "H3 扩散采样 10/20。",
          prompt_text: "角色平稳走到门边。",
          input_asset_ids: [assetId],
          sample_text: null,
          seed: "42",
          output_asset_id: null,
          error_code: null,
          cancellation_requested: false,
          retry_of: null,
          dismissed: false,
          allowed_actions: ["cancel"],
        },
      ],
      director_script: {
        revision: 4,
        source_reference_revision: 7,
        production_baseline_revision: 4,
        production_baseline_scenes: [scene],
        scenes: [scene],
      },
      keyframe_plan: {
        source_script_revision: 4,
        keyframes: [
          {
            id: keyframeId,
            owner_segment_id: segmentId,
            predecessor_keyframe_id: null,
            prompt_text: "走廊起点。",
            visible_character_ids: [], character_references: [],
            selected_asset_id: assetId,
          },
          {
            id: endKeyframeId,
            owner_segment_id: segmentId,
            predecessor_keyframe_id: keyframeId,
            prompt_text: "走廊终点。",
            visible_character_ids: [], character_references: [],
            selected_asset_id: null,
          },
        ],
        segments: [
          {
            segment_id: segmentId,
            start_keyframe_id: keyframeId,
            end_keyframe_id: endKeyframeId,
            start_enabled: true,
            end_enabled: false,
            reference_asset_ids: [],
            start_frame_extraction: { source_segment_id: null, source_video_asset_id: null, state: "unavailable", message: "无上一段。" },
          },
        ],
      },
      video_plan: {
        source_script_revision: 4,
        segments: [
          videoFixture({segment_id: segmentId,prompt_text: "角色平稳走到门边。",selected_asset_id: null,upscaled_asset_id: null,active_recipe: "minimax_h3.fl2va", recipes: {["minimax_h3.fl2va"]: {bindings: {additional_images: [],reference_audios: [],reference_videos: []}, params: {}}}}, { ...videoState("minimax_h3.fl2va"), duration_seconds: 4 }),
        ],
      },
    };
    let samplingNow = 1000;
    vi.spyOn(performance, "now").mockImplementation(() => samplingNow);
    const rendered = renderWorkspace({}, first);
    const telemetry = await screen.findByLabelText("视频采样性能");
    expect(within(telemetry).getByText("10/20")).toBeInTheDocument();
    expect(within(telemetry).getAllByText("测速中…")).toHaveLength(2);
    const second = structuredClone(first);
    second.generations[0].progress = 0.5025;
    second.generations[0].message = "H3 扩散采样 11/20。";
    samplingNow = 6000;
    rendered.rerenderSnapshot(second);
    await waitFor(() =>
      expect(within(telemetry).getByText("5.00 s/iter")).toBeInTheDocument(),
    );
    expect(within(telemetry).getByText("45 秒")).toBeInTheDocument();
    const currentProvider = structuredClone(second);
    currentProvider.generations[0].progress = 0.53;
    currentProvider.generations[0].message =
      "H3 扩散采样 12/20 · 本步 4.25 s/iter · 采样预计剩余 34 秒。";
    samplingNow = 11000;
    rendered.rerenderSnapshot(currentProvider);
    await waitFor(() =>
      expect(within(telemetry).getByText("4.25 s/iter")).toBeInTheDocument(),
    );
    expect(within(telemetry).getByText("34 秒")).toBeInTheDocument();
  });
  it("Animatic 失败后持续显示原因和重新生成入口", async () => {
    const sceneId = "c".repeat(32);
    const segmentId = "e".repeat(32);
    const startId = "1".repeat(32);
    const endId = "2".repeat(32);
    const onGenerateSceneAnimatic = vi.fn();
    const scene: Scene = {
      driver: "drama",
      location_id: null,
      state_id: null,
      id: sceneId,
      title: "海岸",
      summary: "人物观察海面。",
      setting: "现代海岸。",
      narration_cues: [],
      animatic: {
        provider_available: true, reason: "已就绪。",
        ready: true,
        active_generation_id: null,
        latest_succeeded_generation_id: null,
      },
      shots: [
        {
          id: "d".repeat(32),
          visible_character_ids: [],
          composition: "远景。",
          camera_movement: "固定。",
          action: "观察海面。",
          audio_direction: "海浪。",
          transition_in: null,
        }],
      segments: [{ shot_ids: ["d".repeat(32)],
              id: segmentId,
              duration_estimate_seconds: 3,
              action: "观察海面。",
              dialogue_lines: [],
              boundary_from_previous: null,
            }],
    };
    renderWorkspace(
      { onGenerateSceneAnimatic },
      {
        ...snapshot,
        status: "reviewing_keyframes",
        workspace_layers: {
          narration_unlocked: true,
          keyframes_unlocked: true,
          videos_unlocked: false,
          final_assembly_unlocked: false,
        },
        allowed_actions: ["generate_scene_animatic"],
        provider_availability: {
          ...snapshot.provider_availability,
          scene_animatic: true,
          audio_separation: true,
          audio_remix: true,
        },
        director_script: {
          revision: 1,
          source_reference_revision: 7,
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
              prompt_text: "海岸。",
              visible_character_ids: [], character_references: [],
              selected_asset_id: null,
            },
            {
              id: endId,
              owner_segment_id: segmentId,
              predecessor_keyframe_id: startId,
              prompt_text: "海面。",
              visible_character_ids: [], character_references: [],
              selected_asset_id: null,
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
        generations: [
          {
            id: "f".repeat(32),
            kind: "scene_animatic",
            language: null,
            operation: "assemble",
            target_id: sceneId,
            phase: "failed",
            progress: 0.55,
            message: "FFmpeg Animatic 预览失败：视频时间基不一致。",
            prompt_text: "合成动态分镜。",
            input_asset_ids: [],
            sample_text: null,
            seed: null,
            output_asset_id: null,
            error_code: "RuntimeError",
            cancellation_requested: false,
            retry_of: null,
            dismissed: false,
            allowed_actions: ["dismiss_history"],
          },
        ],
      },
    );
    fireEvent.click(within(screen.getByRole("navigation",{name:"故事层级"})).getByRole("button",{name:/场景 1 ·/}));
    expect(screen.getByRole("alert")).toHaveTextContent("Animatic 合成失败");
    expect(screen.getByRole("alert")).toHaveTextContent("视频时间基不一致");
    fireEvent.click(screen.getByRole("button", { name: "重新生成 Animatic" }));
    expect(onGenerateSceneAnimatic).toHaveBeenCalledWith(sceneId);
  });
});
function renderWorkspace(
  overrides: {
    onDesignVoice?: DesignVoiceHandler;
    onDesignNarratorVoice?: WorkspaceActions["onDesignNarratorVoice"];
    onUpdateNarrator?: WorkspaceActions["onUpdateNarrator"];
    onImportImage?: (file: File) => void;
    onImportMedia?: (file: File) => void;
    onDeleteAsset?: (assetId: string) => void;
    onDeleteAssets?: (assetIds: string[]) => void;
    onGenerateAudio?: WorkspaceActions["onGenerateAudio"];
    onTranscribeAudio?: WorkspaceActions["onTranscribeAudio"];
    onTrimAudio?: WorkspaceActions["onTrimAudio"];
    onApplyAudioEffect?: WorkspaceActions["onApplyAudioEffect"];
    onSeparateVideoAudio?: WorkspaceActions["onSeparateVideoAudio"];
    onExtractVideoFrame?: WorkspaceActions["onExtractVideoFrame"];
    onRemixVideoAudio?: WorkspaceActions["onRemixVideoAudio"];
    onUploadVoice?: (cardId: string, file: File) => void;
    onUpdateCharacter?: WorkspaceActions["onUpdateCharacter"];
    onGenerateLookSheet?: WorkspaceActions["onGenerateLookSheet"];
    onSelectLookSheet?: WorkspaceActions["onSelectLookSheet"];
    onSelectLookAsset?: WorkspaceActions["onSelectLookAsset"];
    onPreviewLookSheet?: WorkspaceActions["onPreviewLookSheet"];
    onDismissGeneration?: (generationId: string) => void;
    onSaveDialogueRecipeParams?: (
      dialogueLineId: string,
      recipeParams: Record<string, unknown>,
    ) => void;
    onCancelGeneration?: (generationId: string) => void;
    onSaveScript?: (scenes: Scene[]) => void;
    onConfirmScript?: () => void;
    onSelectNarrationAudio?: (
      sceneId: string,
      cueId: string,
      generationId: string,
    ) => void;
    onGenerateDialogue?: WorkspaceActions["onGenerateDialogue"];
    onSelectDialogueAudio?: WorkspaceActions["onSelectDialogueAudio"];
    onSetDialogueTiming?: WorkspaceActions["onSetDialogueTiming"];
    onClearNarrationAudioSelection?: (sceneId: string, cueId: string) => void;
    onApproveFinalVideo?: () => void;
    onGenerateFinalVideo?: () => void;
    onSaveSegmentVideoInputs?: (segmentId: string, promptText: string) => void;
    onGenerateSegmentVideo?: (segmentId: string, seed?: string) => void;
    onAttachSegmentVideoCandidate?: (segmentId: string, assetId: string) => void;
    onSaveSegmentVideoRecipe?: (
      segmentId: string,
      recipeId: string,
    ) => void;
    onSelectKeyframe?: (keyframeId: string, assetId: string) => void;
    onSaveKeyframe?: (
      keyframeId: string,
      segmentId: string,
      promptText: string,
      visibleCharacterIds: string[],
      characterReferences: KeyframeCharacterReference[],
      referenceAssetIds: string[],
    ) => void;
    onSaveSegmentKeyframeReferences?: (
      segmentId: string,
      assetIds: string[],
    ) => void;
    onSaveSegmentKeyframeActivation?: (
      segmentId: string,
      startEnabled: boolean,
      endEnabled: boolean,
    ) => void;
    onSaveSegmentKeyframeBoundary?: WorkspaceActions["onSaveSegmentKeyframeBoundary"];
    onExtractKeyframeVideoFrame?: WorkspaceActions["onExtractKeyframeVideoFrame"];
    onLoadVideoFrameInfo?: WorkspaceActions["onLoadVideoFrameInfo"];
    onGenerateSceneAnimatic?: (sceneId: string) => void;
    onGenerateSceneFinal?: (sceneId: string) => void;
    pendingSegmentVideoId?: string | null;
    globalReferencesOpen?: boolean;
    onCloseGlobalReferences?: () => void;
    onConfirmReferences?: () => void;
    onPreviewScriptChange?: WorkspaceActions["onPreviewScriptChange"];
    onApplyScriptChange?: WorkspaceActions["onApplyScriptChange"];
    error?: string | null;
  } = {},
  currentSnapshot = snapshot,
  enterProduction = true,
) {
  const workspace = (
    value: StructuredDirectorSnapshot,
    busy = false,
  ) => (
    <StructuredDirectorWorkspace
      project={project}
      snapshot={{ ...value, provider_recipes: [...(value.provider_recipes ?? []), ...videoRecipeViews] as StructuredDirectorSnapshot["provider_recipes"] }}
      busy={busy}
      pending={busy ? "edit_script" : null}
      pendingSegmentVideoId={overrides.pendingSegmentVideoId}
      error={overrides.error ?? null}
      globalReferencesOpen={overrides.globalReferencesOpen}
      onCloseGlobalReferences={overrides.onCloseGlobalReferences}
      onConfirmReferences={overrides.onConfirmReferences ?? vi.fn()}
      onPreviewScriptChange={overrides.onPreviewScriptChange}
      onApplyScriptChange={overrides.onApplyScriptChange}
      onSaveScript={overrides.onSaveScript ?? vi.fn()}
      onConfirmScript={overrides.onConfirmScript ?? vi.fn()}
      onSaveNarrationCue={vi.fn()}
      onGenerateNarration={vi.fn()}
      onGenerateNarrationBatch={vi.fn()}
      onSelectNarrationAudio={overrides.onSelectNarrationAudio ?? vi.fn()}
      onClearNarrationAudioSelection={
        overrides.onClearNarrationAudioSelection ?? vi.fn()
      }
      onGenerateDialogue={overrides.onGenerateDialogue ?? vi.fn()}
      onSelectDialogueAudio={overrides.onSelectDialogueAudio ?? vi.fn()}
      onSetDialogueTiming={overrides.onSetDialogueTiming ?? vi.fn()}
      onGenerateSceneAnimatic={overrides.onGenerateSceneAnimatic}
      onGenerateSceneFinal={overrides.onGenerateSceneFinal}
      onUnlockVisualProduction={vi.fn()}
      onSaveKeyframe={overrides.onSaveKeyframe ?? vi.fn()}
      onGenerateKeyframe={vi.fn()}
      onSelectKeyframe={overrides.onSelectKeyframe ?? vi.fn()}
      onSaveSegmentKeyframeReferences={
        overrides.onSaveSegmentKeyframeReferences ?? vi.fn()
      }
      onSaveSegmentKeyframeActivation={
        overrides.onSaveSegmentKeyframeActivation ?? vi.fn()
      }
      onSaveSegmentKeyframeBoundary={overrides.onSaveSegmentKeyframeBoundary ?? vi.fn()}
      onExtractKeyframeVideoFrame={overrides.onExtractKeyframeVideoFrame ?? vi.fn()}
      onLoadVideoFrameInfo={
        overrides.onLoadVideoFrameInfo ??
        (() => Promise.resolve({ frame_count: 120, duration_seconds: 5 }))
      }
      onAddCharacter={vi.fn()}
      onUpdateCharacter={overrides.onUpdateCharacter ?? vi.fn()}
      onUpdateNarrator={overrides.onUpdateNarrator ?? vi.fn()}
      onDiscard={vi.fn()}
      onImportImage={overrides.onImportImage ?? vi.fn()}
      onImportMedia={overrides.onImportMedia ?? vi.fn()}
      onDeleteAsset={overrides.onDeleteAsset ?? vi.fn()}
      onDeleteAssets={overrides.onDeleteAssets ?? vi.fn()}
      onGenerateAudio={overrides.onGenerateAudio ?? vi.fn()}
      onTranscribeAudio={overrides.onTranscribeAudio ?? vi.fn()}
      onTrimAudio={overrides.onTrimAudio ?? vi.fn()}
      onApplyAudioEffect={overrides.onApplyAudioEffect ?? vi.fn()}
      onSeparateVideoAudio={overrides.onSeparateVideoAudio ?? vi.fn()}
      onExtractVideoFrame={overrides.onExtractVideoFrame ?? vi.fn()}
      onRemixVideoAudio={overrides.onRemixVideoAudio ?? vi.fn()}
      onUploadVoice={overrides.onUploadVoice ?? vi.fn()}
      onUploadNarratorVoice={vi.fn()}
      onGenerateLookSheet={overrides.onGenerateLookSheet ?? vi.fn()}
      onSelectLookSheet={overrides.onSelectLookSheet ?? vi.fn()}
      onSelectLookAsset={overrides.onSelectLookAsset ?? vi.fn()}
      onPreviewLookSheet={overrides.onPreviewLookSheet ?? (() => Promise.resolve("Core 编译的提示词"))}
      onDesignVoice={overrides.onDesignVoice ?? vi.fn()}
      onDesignNarratorVoice={overrides.onDesignNarratorVoice ?? vi.fn()}
      onAttachVoice={vi.fn()}
      onAttachNarratorVoice={vi.fn()}
      onCancelGeneration={overrides.onCancelGeneration ?? vi.fn()}
      onDismissGeneration={overrides.onDismissGeneration ?? vi.fn()}
      onSaveDialogueRecipeParams={overrides.onSaveDialogueRecipeParams ?? vi.fn()}
      onSaveSegmentVideoInputs={overrides.onSaveSegmentVideoInputs ?? vi.fn()}
      onSaveSegmentVideoRecipe={overrides.onSaveSegmentVideoRecipe ?? vi.fn()}
      onGenerateSegmentVideo={overrides.onGenerateSegmentVideo ?? vi.fn()}
      onAttachSegmentVideoCandidate={
        overrides.onAttachSegmentVideoCandidate ?? vi.fn()
      }
      onSelectSegmentVideo={vi.fn()}
      onUpscaleSegmentVideo={vi.fn()}
      onGenerateFinalVideo={overrides.onGenerateFinalVideo ?? vi.fn()}
      onSelectFinalVideo={vi.fn()}
      onApproveFinalVideo={overrides.onApproveFinalVideo ?? vi.fn()}
    />
  );
  vi.spyOn(window,"confirm").mockReturnValue(true);
  const result = render(workspace(currentSnapshot));
  if (currentSnapshot.director_script && enterProduction && !currentSnapshot.workspace_layers.final_assembly_unlocked) {
    fireEvent.click(screen.getByRole("button", { name: /场景 1 ·/ }));
    if (currentSnapshot.workspace_layers.videos_unlocked || currentSnapshot.workspace_layers.keyframes_unlocked) {
      const nav=screen.getByRole("navigation",{name:"故事层级"});
      const segmentGroup=within(nav).queryByRole("list",{name:"场景 1 的生成片段"});
      const segment=segmentGroup ? within(segmentGroup).queryByRole("button",{name:/片段 1/}) : null;
      if(segment) { fireEvent.click(segment); const prompt=screen.queryByText("查看或编辑 视频提示词"); if(prompt) fireEvent.click(prompt); }
    }
  }
  return {
    ...result,
    rerenderSnapshot: (value: StructuredDirectorSnapshot, busy = false) =>
      result.rerender(workspace(value, busy)),

  };
}
type DesignVoiceHandler = (
  cardId: string,
  voiceDescription: string,
  sampleText: string,
  seed: number,
) => void;
it("shows external pending requests without builtin recovery and keeps human card editing", async () => {
  const view = renderWorkspace(
    {},
    {
      ...snapshot,
      status: "awaiting_reference_proposal",
      allowed_actions: [],
      active_director_run: {
        id: "f".repeat(32),
        kind: "reference_proposal",
        status: "running",
        waiting_reason: null,
        created_at: "2026-09-13T00:00:00Z",
        updated_at: "2026-09-13T00:00:00Z",
      },
    },
  );
  expect(screen.getByText("等待外部 Agent 提交")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "继续整理" }),
  ).not.toBeInTheDocument();
  view.unmount();
  renderWorkspace({}, { ...snapshot });
  expect(screen.queryByLabelText("外部 Agent 工作区")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "+ 新增角色" })).toBeEnabled();
  expect(
    screen.queryByRole("button", { name: "生成结构化导演脚本" }),
  ).not.toBeInTheDocument();
});
it('Scene 正文覆盖全部镜头对白；旁白未规划 Shot 时保持可读空态',()=>{
 const value=structuredClone(readerFixture.continuity.production_snapshot) as unknown as StructuredDirectorSnapshot;
 value.workspace_layers={...value.workspace_layers,keyframes_unlocked:false,videos_unlocked:false};
 const first=value.director_script!.scenes[0];
 const cueText=first.narration_cues[0].zh!.text;
 first.shots=[];
 renderWorkspace({},value);
 expect(screen.getAllByText(cueText).length).toBeGreaterThan(0);
 expect(screen.getByText(/完成旁白音频选择后由外部 Agent 按 Core 提供的目标画面时长规划/)).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:/场景 2 ·/}));
 const second=value.director_script!.scenes[1];
 for(const g of second.segments) {
   expect(screen.getAllByText(g.action).length).toBeGreaterThan(0);
   for(const line of g.dialogue_lines) expect(screen.getByText(line.text)).toBeInTheDocument();
 }
});
it('Segment 对白卡展示实时进度、失败原因和可试听的 Mac 产物',()=>{
 const value=structuredClone(readerFixture.continuity.production_snapshot) as unknown as StructuredDirectorSnapshot;
 const onDismissGeneration=vi.fn();
 const onSaveDialogueRecipeParams=vi.fn();
 if(!value.allowed_actions.includes('edit_dialogue_audio')) value.allowed_actions.push('edit_dialogue_audio');
 const scene=value.director_script!.scenes[1];
 const segment=scene.segments[0];
 const line=segment.dialogue_lines[0];
 const card=value.reference_library.characters.find(item=>item.id===line.character_id)!;
 card.voice_reference_asset_id='a'.repeat(32);
 card.voice_reference_transcript='完整参考音频文字稿。';
 const base=value.generations[0];
 const active={
   ...base,
   id:'8'.repeat(32),kind:'dialogue_audio' as const,operation:'synthesize' as const,
   target_id:line.id,language:null,phase:'running' as const,progress:.42,
   message:'Breeze 正在合成对白。',output_asset_id:null,error_code:null,
   allowed_actions:['cancel'] as typeof base.allowed_actions,
 };
 value.generations.push(active);
 const view=renderWorkspace({onDismissGeneration,onSaveDialogueRecipeParams},value);
 const nav=screen.getByRole('navigation',{name:'故事层级'});
 fireEvent.click(within(nav).getByRole('button',{name:/场景 2.*戏剧/}));
 const segmentList=within(nav).getByRole('list',{name:'场景 2 的生成片段'});
 fireEvent.click(within(segmentList).getByRole('button',{name:/片段 1.*小满抬头/}));
 const direction=within(screen.getByLabelText('对白 TTS')).getByText(line.text).closest('section');
 expect(direction).toHaveTextContent('基础音色年轻、克制、语速偏慢');
 expect(direction).toHaveTextContent('剧本表演轻声，带一点迟疑');
 const performance=screen.getByLabelText('表演指示（语气、情绪、语速、停顿）');
 fireEvent.change(performance,{target:{value:'压低声音，带一点迟疑，语速稍慢。'}});
 fireEvent.click(screen.getByRole('button',{name:'保存对白表演参数'}));
 expect(onSaveDialogueRecipeParams).toHaveBeenCalledWith(line.id,{
   'breeze_tts2.clone':{performance_instruction:'压低声音，带一点迟疑，语速稍慢。'},
 });
 expect(screen.getByText(/生成中 · 42% · Breeze 正在合成对白/)).toBeInTheDocument();
 expect(screen.getByRole('button',{name:'生成中…'})).toBeDisabled();

 const failed=structuredClone(value);
 Object.assign(failed.generations.at(-1)!,{
   phase:'failed',progress:.42,message:'Breeze 返回 HTTP 500：Internal Server Error',
   error_code:'RuntimeError',allowed_actions:['dismiss_history'],
 });
 view.rerenderSnapshot(failed);
 expect(screen.getByRole('alert')).toHaveTextContent('Breeze 返回 HTTP 500');
 expect(screen.getByRole('button',{name:'重新生成对白 TTS'})).toBeEnabled();
 fireEvent.click(screen.getByRole('button',{name:'隐藏失败记录'}));
 fireEvent.click(screen.getByRole('button',{name:'确认隐藏'}));
 expect(onDismissGeneration).toHaveBeenCalledWith('8'.repeat(32));
 onDismissGeneration.mockClear();

 const succeeded=structuredClone(failed);
 const assetId='9'.repeat(32);
 const historicalAssetId='7'.repeat(32);
 succeeded.assets.push({
   id:assetId,media_type:'audio/wav',image_category:null,byte_count:2048,
   duration_seconds:1.75,display_name:'小满对白.wav',content_url:'/dialogue.wav',
   is_in_use:true,usage_reasons:[],retains_derived_assets_on_delete:false,allowed_actions:[],
 });
 succeeded.assets.push({
   id:historicalAssetId,media_type:'audio/wav',image_category:null,byte_count:2048,
   duration_seconds:1.62,display_name:'小满旧对白.wav',content_url:'/dialogue-old.wav',
   is_in_use:false,usage_reasons:[],retains_derived_assets_on_delete:false,allowed_actions:[],
 });
 Object.assign(succeeded.generations.at(-1)!,{
   phase:'succeeded',progress:1,message:'完成',output_asset_id:assetId,error_code:null,
   allowed_actions:[],
 });
 succeeded.generations.push({
   ...succeeded.generations.at(-1)!,id:'7'.repeat(32),output_asset_id:historicalAssetId,
   inputs_outdated:true,allowed_actions:['select_dialogue_audio','dismiss_history'],
 });
 succeeded.dialogue_plan!.items.find(item=>item.dialogue_line_id===line.id)!.selected_audio_asset_id=assetId;
 view.rerenderSnapshot(succeeded);
 expect(screen.getByLabelText('试听已选对白 小满')).toHaveAttribute('src','/dialogue.wav');
 expect(screen.getByRole('button',{name:/对白候选.*2 条/})).toBeInTheDocument();
 expect(screen.getByLabelText('试听对白候选 888888')).toHaveAttribute('src','/dialogue.wav');
 expect(screen.getByText('当前已选 · 888888')).toBeInTheDocument();
 expect(screen.getByLabelText('试听对白候选 777777')).toHaveAttribute('src','/dialogue-old.wav');
 expect(screen.getByRole('button',{name:'选择候选 777777'})).toBeEnabled();
 expect(screen.getByText(/该候选生成后的正文、音色或表演参数已经变化/)).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'隐藏候选 777777'}));
 fireEvent.click(screen.getByRole('button',{name:'确认隐藏候选 777777'}));
 expect(onDismissGeneration).toHaveBeenCalledWith('7'.repeat(32));
 const candidateToggle=screen.getByRole('button',{name:/对白候选.*2 条.*收起/});
 fireEvent.click(candidateToggle);
 expect(candidateToggle).toHaveAttribute('aria-expanded','false');
 expect(screen.queryByLabelText('试听对白候选 888888')).not.toBeInTheDocument();
 const lineToggle=screen.getByRole('button',{name:/对白 1.*小满.*音色克隆.*已选择/});
 fireEvent.click(lineToggle);
 expect(lineToggle).toHaveAttribute('aria-expanded','false');
 expect(screen.queryByLabelText('试听已选对白 小满')).not.toBeInTheDocument();
 const panelToggle=screen.getByRole('button',{name:/对白 TTS.*已选 1\//});
 fireEvent.click(panelToggle);
 expect(panelToggle).toHaveAttribute('aria-expanded','false');
 expect(screen.queryByLabelText('对白与表演')).not.toBeInTheDocument();
});
it('引用库编辑作为临时弹窗，关闭后保留当前 Segment 和未保存输入',()=>{
 const value=structuredClone(readerFixture.continuity.production_snapshot) as unknown as StructuredDirectorSnapshot;
 value.allowed_actions.push('edit_script');
 const options={globalReferencesOpen:false};
 const view=renderWorkspace(options,value);
 fireEvent.click(screen.getByRole('button',{name:'编辑这一段'}));
 fireEvent.change(screen.getByLabelText('本段动作 *'),{target:{value:'保留这段草稿'}});
 const input=screen.getByLabelText('本段动作 *');
 options.globalReferencesOpen=true;view.rerenderSnapshot(value);
 fireEvent.click(within(screen.getByRole('dialog',{name:'全局引用'})).getByRole('button',{name:'编辑引用库'}));
 options.globalReferencesOpen=false;view.rerenderSnapshot(value);
 const dialog=screen.getByRole('dialog',{name:'编辑引用库'});
 expect(dialog).toBeInTheDocument();
 fireEvent.click(within(dialog).getByRole('button',{name:'返回当前故事位置'}));
 expect(screen.queryByRole('dialog',{name:'编辑引用库'})).not.toBeInTheDocument();
 expect(screen.getByLabelText('本段动作 *')).toBe(input);
 expect(input).toHaveValue('保留这段草稿');
});
it('已解锁成片层在上游回改后没有装配计划时，仍能使用 Core 允许的装配操作',()=>{
 const value=structuredClone(readerFixture.continuity.production_snapshot) as unknown as StructuredDirectorSnapshot;
 value.provider_availability.final_assembly=true;
 value.workspace_layers.final_assembly_unlocked=true;value.final_assembly=null;value.allowed_actions=['generate_final_video'];
 const generate=vi.fn();renderWorkspace({onGenerateFinalVideo:generate},value);
 fireEvent.click(screen.getByRole('button',{name:'一键生成成片'}));expect(generate).toHaveBeenCalledOnce();
});
it('删除当前 Segment 后回到所在 Scene；脏稿保留到用户确认离开',()=>{
 const value=structuredClone(readerFixture.continuity.production_snapshot) as unknown as StructuredDirectorSnapshot;
 value.allowed_actions.push('edit_script');
 const view=renderWorkspace({},value);
 const first=value.director_script!.scenes[0];
 fireEvent.click(screen.getByRole('button',{name:'编辑这一段'}));
 fireEvent.change(screen.getByLabelText('本段动作 *'),{target:{value:'删除后仍保留的输入'}});
 const updated=structuredClone(value);updated.revision+=1;updated.director_script!.scenes[0].segments.shift();
 view.rerenderSnapshot(updated);
 expect(screen.getByLabelText('本段动作 *')).toHaveValue('删除后仍保留的输入');
 expect(screen.getByRole('button',{name:'保存脚本修改'})).toBeDisabled();
 fireEvent.click(screen.getByRole('button',{name:'取消编辑'}));
 expect(screen.getByRole('heading',{name:first.title})).toBeInTheDocument();
 expect(screen.getByText(/已返回仍存在的上级/)).toBeInTheDocument();
});
it('普通导航不确认；有草稿时拒绝丢弃就保持原节点',()=>{
 const value=structuredClone(readerFixture.continuity.production_snapshot) as unknown as StructuredDirectorSnapshot;
 value.allowed_actions.push('edit_script');renderWorkspace({},value);
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
 expect(confirm).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'编辑这一段'}));
 fireEvent.change(screen.getByLabelText('本段动作 *'),{target:{value:'不要丢弃'}});
 fireEvent.click(screen.getByRole('button',{name:'项目概览'}));
 expect(confirm).toHaveBeenCalledOnce();expect(screen.getByLabelText('本段动作 *')).toHaveValue('不要丢弃');
});

it("discards only the departed segment draft and mounts one media pair", async () => {
  const value = structuredClone(readerFixture.continuity.production_snapshot) as unknown as StructuredDirectorSnapshot;
  value.allowed_actions.push("edit_segment_video_plan");
  const plans = value.video_plan!.segments;
  plans[0].prompt_text = "首段已保存";
  plans[1].prompt_text = "次段已保存";
  renderWorkspace({}, value);
  fireEvent.change(screen.getByRole("textbox", {name:"当前 视频提示词"}), {target:{value:"首段未保存"}});
  const confirm = vi.mocked(window.confirm);
  confirm.mockReturnValueOnce(false);
  fireEvent.click(screen.getByRole("button", {name:"下一片段"}));
  expect(screen.getByRole("textbox", {name:"当前 视频提示词"})).toHaveValue("首段未保存");
  confirm.mockReturnValueOnce(true);
  fireEvent.click(screen.getByRole("button", {name:"下一片段"}));
  fireEvent.click(screen.getByText("查看或编辑 视频提示词"));
  expect(screen.getByRole("textbox", {name:"当前 视频提示词"})).toHaveValue("次段已保存");
  expect(document.querySelectorAll(".segment-keyframe-inputs")).toHaveLength(1);
  expect(document.querySelectorAll(".segment-video-panel")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", {name:"上一片段"}));
  fireEvent.click(screen.getByText("查看或编辑 视频提示词"));
  expect(screen.getByRole("textbox", {name:"当前 视频提示词"})).toHaveValue("首段已保存");
});

it("当前视频任务取消使用精确 Generation，权限收回后不再提供取消", async () => {
  const value = structuredClone(readerFixture.continuity.production_snapshot) as unknown as StructuredDirectorSnapshot;
  const segment = value.director_script!.scenes[0].segments[0];
  const generation = {...value.generations[0], id: "f".repeat(32), kind: "segment_video" as const, target_id: segment.id, phase: "running" as const, seed: "42", allowed_actions: ["cancel" as const], output_asset_id: null};
  value.generations.push(generation);
  const cancel=vi.fn(); const view=renderWorkspace({onCancelGeneration:cancel}, value);
  fireEvent.click(screen.getByRole("button",{name:"取消视频生成"}));
  expect(cancel).toHaveBeenCalledExactlyOnceWith(generation.id);
  const changed=structuredClone(value);changed.generations.at(-1)!.allowed_actions=[];
  view.rerenderSnapshot(changed);
  expect(screen.queryByRole("button",{name:"取消视频生成"})).not.toBeInTheDocument();
});

it("未就绪的成片能力仍展示 Core 原因，媒体服务和动作缺一不可", async () => {
  const value = structuredClone(readerFixture.continuity.production_snapshot) as unknown as StructuredDirectorSnapshot;
  value.final_assembly = null;
  value.production_availability.final.reason = "请先为第二个片段选择视频。";
  value.allowed_actions = value.allowed_actions.filter(action => action !== "generate_final_video");
  const generate = vi.fn();
  const view = renderWorkspace({onGenerateFinalVideo: generate}, value);
  fireEvent.click(screen.getByRole("button", {name: "项目概览"}));
  expect(screen.getByText("请先为第二个片段选择视频。")).toBeVisible();
  expect(screen.getByRole("button", {name: "一键生成成片"})).toBeDisabled();
  value.allowed_actions.push("generate_final_video");
  value.provider_availability.final_assembly = false;
  view.rerenderSnapshot(value);
  expect(screen.getByRole("button", {name: "一键生成成片"})).toBeDisabled();
  expect(generate).not.toHaveBeenCalled();
});

it("confirms reference review through Core and displays voice-only identities without images", async () => {
  const confirm = vi.fn();
  renderWorkspace({onConfirmReferences: confirm}, {...snapshot,
    allowed_actions: [...snapshot.allowed_actions, "confirm_reference_review"],
    workflow: {
      ...snapshot.workflow,
      current_stage: "reference_library",
      stage_status: "awaiting_human_review",
      required_next_actions: [{
        action: "reference.confirm_review", tool: null, target_ids: [],
        human_only: true, requires_explicit_user_request: false,
      }],
    },
    reference_library: {narrator: null, reviewed: false, characters: [{
      id: "a".repeat(32), name: "广播", visual_description: null,
      voice_description: "稳定电台声音", voice_reference_asset_id: null, looks: [],
    }]},
  });
  expect(screen.getByText("非出镜声音")).toBeInTheDocument();
  expect(screen.queryByLabelText("稳定视觉描述")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "确认角色与声音引用"}));
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
});

const playgroundImageId = "f".repeat(32);
const playgroundImage = {
  id: playgroundImageId,
  media_type: "image/png",
  byte_count: 10,
  sha256: "f".repeat(64),
  relative_path: "assets/images/imported/playground-0123456789.png",
  duration_seconds: null,
  origin: { kind: "imported" },
  created_at: "2026-01-01T00:00:00+00:00",
  display_name: "Playground 图片",
  content_url: `/api/playground/assets/${playgroundImageId}/content`,
  is_in_use: false,
  usage_reasons: [],
  allowed_actions: ["copy_to_project", "delete"],
};
function playgroundResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
it("资产中心 Playground 页签要求图片先选分类，并按项目快照 revision 复制", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/playground") {
      return playgroundResponse({
        schema_version: 2,
        revision: 1,
        capabilities: [
          { id: "image.generate", label: "生图", execution: "async", group: "audio", available: true, notes: "", recipe: null },
        ],
        runs: [],
        assets: [playgroundImage],
      });
    }
    if (url.endsWith("/copy-from-playground")) {
      return playgroundResponse({
        asset_id: "e".repeat(32),
        project_revision: snapshot.revision + 1,
      });
    }
    throw new Error(`unexpected ${url}`);
  });
  try {
    renderWorkspace({}, snapshot, false);
    fireEvent.click(screen.getByRole("button", { name: "资产中心" }));
    const dialog = await screen.findByRole("dialog", { name: "资产中心" });
    expect(within(dialog).getByRole("tab", { name: "Playground" })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("tab", { name: "Playground" }));
    expect(await within(dialog).findByText("Playground 图片")).toBeInTheDocument();
    const copy = within(dialog).getByRole("button", { name: "复制到本项目" });
    expect(copy).toBeDisabled();
    fireEvent.change(
      within(dialog).getByRole("combobox", { name: "Playground 图片分类" }),
      { target: { value: "keyframe" } },
    );
    expect(copy).toBeEnabled();
    fireEvent.click(copy);
    await waitFor(() =>
      expect(fetcher).toHaveBeenCalledWith(
        expect.stringContaining("/assets/copy-from-playground"),
        expect.anything(),
      ),
    );
    const call = fetcher.mock.calls.find((item) =>
      String(item[0]).includes("/assets/copy-from-playground"),
    );
    expect(JSON.parse(String((call?.[1] as RequestInit).body))).toEqual({
      asset_id: playgroundImageId,
      expected_revision: snapshot.revision,
      image_category: "keyframe",
    });
  } finally {
    fetcher.mockRestore();
  }
});
it('导演台顶部提示条只展示服务端推荐动作，无可建议时不渲染',()=>{
 const value=structuredClone(readerFixture.continuity.production_snapshot) as unknown as StructuredDirectorSnapshot;
 value.workflow={...value.workflow,recommended_next_actions:[{
   action:"location.request_proposal",tool:"submit_proposal",target_ids:[],
   human_only:false,requires_explicit_user_request:true,tool_action:"request",
   capability:"location",message:"3 个 Scene 尚未绑定地点；可让 Director 规划地点与机位视图。",
 }]};
 const view=renderWorkspace({},value);
 const banner=screen.getByRole("region",{name:"可选建议"});
 expect(banner).toHaveTextContent("3 个 Scene 尚未绑定地点");
 const empty=structuredClone(value);
 empty.workflow={...value.workflow,recommended_next_actions:[]};
 view.rerenderSnapshot(empty);
 expect(screen.queryByRole("region",{name:"可选建议"})).not.toBeInTheDocument();
});
it('阅读视图按 shot_ids 展示段内切镜的覆盖镜头',()=>{
 const value=structuredClone(readerFixture.continuity.production_snapshot) as unknown as StructuredDirectorSnapshot;
 const scene=value.director_script!.scenes[1];
 scene.segments[0].shot_ids=[scene.shots[0].id,scene.shots[1].id];
 renderWorkspace({},value,false);
 const nav=screen.getByRole("navigation",{name:"故事层级"});
 fireEvent.click(within(nav).getByRole("button",{name:/场景 2.*戏剧/}));
 // 导航树与 Scene 页的片段列表都按覆盖关系给出同一标签。
 expect(screen.getAllByRole("button",{name:/片段 1 · 镜头 1–2/})).toHaveLength(2);
 const list=within(nav).getByRole("list",{name:"场景 2 的生成片段"});
 fireEvent.click(within(list).getByRole("button",{name:/片段 1 · 镜头 1–2/}));
 expect(screen.getByText("覆盖 镜头 1、镜头 2")).toBeInTheDocument();
 expect(screen.getByText(/片段 1（镜头 1–2）/)).toBeInTheDocument();
});

function scriptSnapshot(): StructuredDirectorSnapshot {
  return structuredClone(
    readerFixture.continuity.production_snapshot,
  ) as unknown as StructuredDirectorSnapshot;
}

function withLocation(
  value: StructuredDirectorSnapshot,
  sceneIndex: number,
): { locationId: string; viewId: string } {
  const scene = value.director_script!.scenes[sceneIndex];
  const locationId = "a".repeat(32);
  const viewId = "b".repeat(32);
  scene.location_id = locationId;
  scene.state_id = null;
  value.location_library = {
    locations: [
      {
        id: locationId,
        name: "站台",
        description: "站台。",
        fixtures: [],
        key_light: null,
        states: [],
        images: [
          {
            id: viewId,
            name: "正打",
            kind: "image",
            description: "正打中景。",
            prompt_text: "",
            reference_asset_ids: [],
            selected_asset_id: null,
            source: null,
          },
        ],
        allowed_actions: ["edit", "create_image", "create_fixture", "create_state"],
      },
    ],
    allowed_actions: ["create_location", "bind_scene"],
  };
  return { locationId, viewId };
}

function openScene(index: number) {
  const nav = screen.getByRole("navigation", { name: "故事层级" });
  fireEvent.click(
    within(nav).getByRole("button", { name: new RegExp(`场景 ${index} ·`) }),
  );
}

function openSegment(sceneIndex: number, segmentIndex: number) {
  const nav = screen.getByRole("navigation", { name: "故事层级" });
  const list = within(nav).getByRole("list", {
    name: `场景 ${sceneIndex} 的生成片段`,
  });
  fireEvent.click(within(list).getAllByRole("button")[segmentIndex - 1]);
}

function impactFor(revision: number) {
  return {
    revision,
    command_name: "script.apply_operations",
    will_write: true,
    high_impact: false,
    changed_ids: ["segment"],
    invalidated: [],
    preserved: ["asset_history", "generation_history"],
  };
}

it("Scene 镜头设计列出覆盖片段，Segment 页列出覆盖镜头描述", () => {
  const value = scriptSnapshot();
  const scene = value.director_script!.scenes[1];
  scene.segments[0].shot_ids = [scene.shots[0].id, scene.shots[1].id];
  renderWorkspace({}, value, false);
  openScene(2);
  expect(
    screen.getByText("被片段 1（镜头 1–2）覆盖"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "被片段 1（镜头 1–2）、2（镜头 2（续））、3（镜头 2（续））覆盖",
    ),
  ).toBeInTheDocument();
  openSegment(2, 1);
  const list = screen.getByRole("list", { name: "覆盖的镜头" });
  expect(within(list).getAllByRole("listitem")).toHaveLength(2);
  expect(within(list).getAllByText(/构图：/)).toHaveLength(2);
  expect(within(list).getAllByText(/运镜：/)).toHaveLength(2);
});

it("Shot 编辑器不再暴露地点图片绑定，并以整卡保存", () => {
  const value = scriptSnapshot();
  withLocation(value, 1);
  const onSaveScript = vi.fn();
  renderWorkspace({ onSaveScript }, value, false);
  openScene(2);
  fireEvent.click(screen.getByRole("button", { name: "镜头 1" }));
  fireEvent.click(screen.getByRole("button", { name: "编辑这一段" }));
  expect(screen.queryByLabelText(/空间参考建议/)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("构图"), {
    target: { value: "修改后的构图。" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存脚本修改" }));
  expect(onSaveScript).toHaveBeenCalledOnce();
  expect(onSaveScript.mock.calls[0][0][1].shots[0]).not.toHaveProperty("view_id");
});

it("Scene 未绑定地点时 Shot 编辑器同样不出现地点图片绑定", () => {
  const value = scriptSnapshot();
  renderWorkspace({}, value, false);
  openScene(1);
  fireEvent.click(screen.getByRole("button", { name: "镜头 1" }));
  fireEvent.click(screen.getByRole("button", { name: "编辑这一段" }));
  expect(screen.queryByLabelText(/空间参考建议/)).not.toBeInTheDocument();
  expect(screen.queryByText(/镜头只能不使用空间参考视图/)).not.toBeInTheDocument();
});

it("Segment 覆盖区间选择按连续区间写 shot_ids，提交整卡保存", () => {
  const value = scriptSnapshot();
  const onSaveScript = vi.fn();
  renderWorkspace({ onSaveScript }, value, false);
  openScene(2);
  openSegment(2, 1);
  fireEvent.click(screen.getByRole("button", { name: "编辑这一段" }));
  expect(screen.getByText(/本段从新镜头开始/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("结束镜头"), {
    target: { value: "1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存脚本修改" }));
  expect(onSaveScript).toHaveBeenCalledOnce();
  const saved = onSaveScript.mock.calls[0][0][1];
  expect(saved.segments[0].shot_ids).toEqual([
    saved.shots[0].id,
    saved.shots[1].id,
  ]);
  expect(saved.segments[0].boundary_from_previous).toBeNull();
});

it("共享边界 Shot 的 Segment 显示并保存延续说明", () => {
  const value = scriptSnapshot();
  const onSaveScript = vi.fn();
  renderWorkspace({ onSaveScript }, value, false);
  openScene(2);
  openSegment(2, 3);
  fireEvent.click(screen.getByRole("button", { name: "编辑这一段" }));
  expect(screen.getByText(/本段与上一片段共享镜头 2/)).toBeInTheDocument();
  expect(screen.getByLabelText("边界连续性说明 *")).toHaveValue(
    "从同一静态交接时刻继续",
  );
  fireEvent.change(screen.getByLabelText("边界连续性说明 *"), {
    target: { value: "保持同一抬手姿态。" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存脚本修改" }));
  const saved = onSaveScript.mock.calls[0][0][1];
  expect(saved.segments[2].boundary_from_previous).toEqual({
    reason: "model_constraint",
    continuity_instruction: "保持同一抬手姿态。",
  });
});

it("Segment 结构修改服务端拒绝时保留输入并显示原始错误", async () => {
  const value = scriptSnapshot();
  const message = "Scene「沿岸行走」的 Segment 1 覆盖必须恰好覆盖全部 Shot。";
  const onPreview = vi.fn().mockRejectedValue(new Error(message));
  renderWorkspace(
    { onPreviewScriptChange: onPreview, onApplyScriptChange: vi.fn() },
    value,
    false,
  );
  openScene(2);
  openSegment(2, 1);
  fireEvent.click(screen.getByRole("button", { name: "拆分片段" }));
  fireEvent.change(screen.getByLabelText("边界连续性说明 *"), {
    target: { value: "延续站台动作。" },
  });
  fireEvent.click(screen.getByRole("button", { name: "预览影响" }));
  expect(await screen.findByText(message)).toBeInTheDocument();
  expect(screen.getByLabelText("边界连续性说明 *")).toHaveValue(
    "延续站台动作。",
  );
  expect(screen.getByRole("dialog", { name: "拆分片段" })).toBeInTheDocument();
});

it("新增镜头并入已有片段与新建片段的整卡请求形状", () => {
  const value = scriptSnapshot();
  const onSaveScript = vi.fn();
  const first = renderWorkspace({ onSaveScript }, value, false);
  openScene(2);
  fireEvent.click(screen.getByRole("button", { name: "新增镜头" }));
  expect(screen.getByRole("form", { name: "新增镜头" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "保存新镜头" }));
  expect(onSaveScript).toHaveBeenCalledOnce();
  const attached = onSaveScript.mock.calls[0][0][1];
  expect(attached.shots).toHaveLength(3);
  const newShot = attached.shots[2];
  expect(newShot.id.startsWith("new:")).toBe(true);
  expect(newShot).not.toHaveProperty("view_id");
  expect(attached.segments[2].shot_ids).toEqual([
    attached.shots[1].id,
    newShot.id,
  ]);
  first.unmount();

  const onSaveScriptNew = vi.fn();
  renderWorkspace({ onSaveScript: onSaveScriptNew }, value, false);
  openScene(2);
  fireEvent.click(screen.getByRole("button", { name: "新增镜头" }));
  fireEvent.click(screen.getByLabelText("新建片段"));
  fireEvent.click(screen.getByRole("button", { name: "保存新镜头" }));
  expect(onSaveScriptNew).toHaveBeenCalledOnce();
  const created = onSaveScriptNew.mock.calls[0][0][1];
  expect(created.shots).toHaveLength(3);
  const newSegment = created.segments.at(-1)!;
  expect(newSegment.shot_ids).toEqual([created.shots[2].id]);
  expect(newSegment.boundary_from_previous).toBeNull();
  expect(newSegment.duration_estimate_seconds).toBe(3);
});

it("拆分片段时两段共享 Shot 且第二段必填延续说明；预览后提交 apply_operations", async () => {
  const value = scriptSnapshot();
  const onPreview = vi.fn().mockImplementation(async (_change: unknown, revision: number) =>
    impactFor(revision),
  );
  const onApply = vi.fn().mockResolvedValue(true);
  renderWorkspace(
    { onPreviewScriptChange: onPreview, onApplyScriptChange: onApply },
    value,
    false,
  );
  openScene(2);
  openSegment(2, 1);
  const scene = value.director_script!.scenes[1];
  fireEvent.click(screen.getByRole("button", { name: "拆分片段" }));
  fireEvent.change(screen.getByLabelText("边界连续性说明 *"), {
    target: { value: "从同一抬手姿态继续。" },
  });
  fireEvent.click(screen.getByRole("button", { name: "预览影响" }));
  await waitFor(() => expect(onPreview).toHaveBeenCalledOnce());
  const change = onPreview.mock.calls[0][0];
  expect(change.arguments.scope.scene_ids).toEqual([scene.id]);
  const operation = change.arguments.operations[0];
  expect(operation.op).toBe("split_segment");
  expect(operation.segment_id).toBe(scene.segments[0].id);
  expect(operation.preserve_id).toBe("first");
  expect(operation.first.shot_ids).toEqual([scene.shots[0].id]);
  expect(operation.second.shot_ids).toEqual([scene.shots[0].id]);
  expect(operation.second.boundary_from_previous).toEqual({
    reason: "continuity_anchor",
    continuity_instruction: "从同一抬手姿态继续。",
  });
  expect(operation.first.boundary_from_previous).toBeNull();
  fireEvent.click(await screen.findByRole("button", { name: "确认保存" }));
  await waitFor(() => expect(onApply).toHaveBeenCalledOnce());
  expect(onApply.mock.calls[0][0]).toEqual(change);
});

it("合并相邻片段时 shot_ids 为并集，预览后提交 apply_operations", async () => {
  const value = scriptSnapshot();
  const onPreview = vi.fn().mockImplementation(async (_change: unknown, revision: number) =>
    impactFor(revision),
  );
  const onApply = vi.fn().mockResolvedValue(true);
  renderWorkspace(
    { onPreviewScriptChange: onPreview, onApplyScriptChange: onApply },
    value,
    false,
  );
  openScene(2);
  openSegment(2, 1);
  const scene = value.director_script!.scenes[1];
  fireEvent.click(screen.getByRole("button", { name: "与下一片段合并" }));
  fireEvent.click(screen.getByRole("button", { name: "预览影响" }));
  await waitFor(() => expect(onPreview).toHaveBeenCalledOnce());
  const change = onPreview.mock.calls[0][0];
  const operation = change.arguments.operations[0];
  expect(operation.op).toBe("merge_adjacent_segments");
  expect(operation.left_segment_id).toBe(scene.segments[0].id);
  expect(operation.right_segment_id).toBe(scene.segments[1].id);
  expect(operation.preserve_id).toBe("left");
  expect(operation.merged.shot_ids).toEqual([
    scene.shots[0].id,
    scene.shots[1].id,
  ]);
  expect(operation.merged.duration_estimate_seconds).toBe(
    scene.segments[0].duration_estimate_seconds +
      scene.segments[1].duration_estimate_seconds,
  );
  fireEvent.click(await screen.findByRole("button", { name: "确认保存" }));
  await waitFor(() => expect(onApply).toHaveBeenCalledOnce());
});

it("Segment 保存被服务端拒绝时保留输入并原样显示错误", () => {
  const value = scriptSnapshot();
  const message = "Scene「沿岸行走」的 Segment 2 覆盖必须恰好覆盖全部 Shot。";
  const onSaveScript = vi.fn();
  renderWorkspace({ onSaveScript, error: message }, value, false);
  openScene(2);
  openSegment(2, 1);
  fireEvent.click(screen.getByRole("button", { name: "编辑这一段" }));
  const input = screen.getByLabelText("本段动作 *");
  fireEvent.change(input, { target: { value: "服务端拒绝后仍保留的输入" } });
  fireEvent.click(screen.getByRole("button", { name: "保存脚本修改" }));
  expect(
    screen.getByText(`${message} 输入已保留。`),
  ).toBeInTheDocument();
  expect(input).toHaveValue("服务端拒绝后仍保留的输入");
});

it("新增镜头不携带地点图片绑定", () => {
  const value = scriptSnapshot();
  withLocation(value, 1);
  const onSaveScript = vi.fn();
  renderWorkspace({ onSaveScript }, value, false);
  openScene(2);
  fireEvent.click(screen.getByRole("button", { name: "新增镜头" }));
  expect(screen.queryByLabelText(/空间参考建议/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "保存新镜头" }));
  const saved = onSaveScript.mock.calls[0][0][1];
  expect(saved.shots.at(-1)).not.toHaveProperty("view_id");
});
