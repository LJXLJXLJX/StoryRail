"""有限生产工具的完整输入 schema 与固定 HTTP 命令翻译；无 Core/Store 依赖。"""

from functools import reduce
from operator import or_
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

ID = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
IDs = Annotated[list[ID], Field(max_length=100)]
Targets = Annotated[list[ID], Field(min_length=1, max_length=100)]
Text = Annotated[str, Field(max_length=20000)]
# 与 Core 的 IMAGE_ASPECT_RATIOS 一致（测试守护）；MCP 进程不导入 Core。
AspectRatio = Literal[
    "16:9",
    "9:16",
    "2:1",
    "1:2",
    "1:1",
    "3:2",
    "2:3",
    "4:3",
    "3:4",
    "5:4",
    "4:5",
    "21:9",
    "9:21",
    "3:1",
    "1:3",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Request(Strict):
    project_id: ID
    expected_revision: Annotated[int, Field(ge=1)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]


class ReadRequest(Strict):
    project_id: ID
    expected_revision: Annotated[int, Field(ge=1)] | None = None
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)] = "read"


def object_model(name, properties, optional=()):
    return create_model(
        name,
        __base__=Strict,
        **{key: (value, None if key in optional else ...) for key, value in properties.items()},
    )


def operation(name, fields):
    return object_model(name, {"op": Literal[name], **fields})


# 说话者二选一：引用库角色 character_id，或 character_id=null 加引用库外说话者 speaker_label。
Dialogue = object_model(
    "Dialogue",
    {
        "id": ID | None,
        "character_id": ID | None,
        "speaker_label": Annotated[str, Field(min_length=1, max_length=60, pattern=r"\S")] | None,
        "voice_description": Annotated[str, Field(min_length=1, max_length=500, pattern=r"\S")]
        | None,
        "text": Text,
        "delivery": Text,
    },
    optional=("id", "speaker_label", "voice_description"),
)
BoundaryReason = Literal[
    "model_constraint",
    "continuity_anchor",
    "control_boundary",
    "failure_cost",
]
Boundary = object_model("Boundary", {"reason": BoundaryReason, "continuity_instruction": Text})
segment_fields = {
    # 只要求不短于 0.2 秒；15 秒是 Agent 侧软约束（超过可能 OOM），Core 与适配层都不设上限。
    "duration_estimate_seconds": Annotated[float, Field(ge=0.2, allow_inf_nan=False)],
    "action": Text,
    "dialogue_lines": list[Dialogue],
    "boundary_from_previous": Boundary | None,
}
shot_fields = {
    "visible_character_ids": IDs,
    "composition": Text,
    "camera_movement": Text,
    "action": Text,
    "audio_direction": Text,
    "transition_in": str | None,
}
# 已有 Scene 内的 Segment 用已有 Shot ID 表达覆盖。
Segment = object_model(
    "Segment",
    {"shot_ids": Annotated[list[ID], Field(min_length=1, max_length=100)], **segment_fields},
)
# 随新 Scene 一起创建的 Segment 用新 shots 数组的序号表达覆盖。
NewSegment = object_model(
    "NewSegment",
    {
        "shot_indexes": Annotated[
            list[Annotated[int, Field(ge=0)]], Field(min_length=1, max_length=100)
        ],
        **segment_fields,
    },
)
Shot = object_model("Shot", shot_fields)
ShotFields = object_model("ShotFields", shot_fields, shot_fields)
scene_fields = {
    "title": Annotated[str, Field(min_length=1, max_length=300)],
    "summary": Annotated[str, Field(min_length=1, max_length=4000)],
    "setting": Annotated[str, Field(min_length=1, max_length=4000)],
}
SceneFields = object_model("SceneFields", scene_fields, scene_fields)
Language = Literal["zh", "en"]
RecipeParams = dict[str, dict[str, str | int | float | bool | list[float] | None]]
Seed = Annotated[int, Field(ge=0, le=2**63 - 1)]
NarrationTrackInput = object_model(
    "NarrationTrackInput",
    {
        "text": Annotated[str, Field(min_length=1, max_length=4000)],
        "seed": Seed,
        "recipe_params": RecipeParams,
    },
    ("recipe_params",),
)
# 旁白固定中英双语：zh 与 en 各自合成，时间以较长的一条为准；英文是适合朗读的意译。
SceneNarrationCue = object_model(
    "SceneNarrationCue", {"zh": NarrationTrackInput, "en": NarrationTrackInput}
)
scene_insert_optional = {
    "driver": Literal["drama", "narration"],
    "shots": Annotated[list[Shot], Field(max_length=100)],
    "segments": Annotated[list[NewSegment], Field(max_length=100)],
    "narration_cue": SceneNarrationCue,
}
SceneInsert = object_model(
    "SceneInsert", {**scene_fields, **scene_insert_optional}, scene_insert_optional
)
SegmentFields = object_model(
    "SegmentFields",
    {"shot_ids": Annotated[list[ID], Field(min_length=1, max_length=100)], **segment_fields},
    ("shot_ids", *segment_fields),
)


# 新 Shot 必须同时说明它如何进入覆盖：并入已有 Segment，或新建一个只覆盖它的 Segment。
class InsertShot(Strict):
    op: Literal["insert_shot"]
    scene_id: ID
    after_shot_id: ID | None
    shot: Shot
    attach_to_segment_id: ID | None = None
    new_segment: NewSegment | None = None

    @model_validator(mode="after")
    def exact_coverage(self):
        if (self.attach_to_segment_id is None) == (self.new_segment is None):
            raise ValueError(
                "insert_shot 必须且只能给出 attach_to_segment_id 或 new_segment 之一。"
            )
        return self


ScriptOperation = reduce(
    or_,
    (InsertShot,)
    + tuple(
        operation(name, fields)
        for name, fields in {
            "update_scene_fields": {"scene_id": ID, "fields": SceneFields},
            "insert_scene": {"after_scene_id": ID | None, "scene": SceneInsert},
            "move_scene": {"scene_id": ID, "after_scene_id": ID | None},
            "delete_scene": {"scene_id": ID},
            "update_shot_fields": {"shot_id": ID, "fields": ShotFields},
            "delete_shot": {"scene_id": ID, "shot_id": ID},
            "update_segment_fields": {"segment_id": ID, "fields": SegmentFields},
            "insert_segment": {
                "scene_id": ID,
                "after_segment_id": ID | None,
                "segment": Segment,
            },
            "move_segment": {"scene_id": ID, "segment_id": ID, "after_segment_id": ID | None},
            "delete_segment": {"scene_id": ID, "segment_id": ID},
            "split_segment": {
                "segment_id": ID,
                "preserve_id": Literal["first", "second"],
                "first": Segment,
                "second": Segment,
            },
            "merge_adjacent_segments": {
                "left_segment_id": ID,
                "right_segment_id": ID,
                "preserve_id": Literal["left", "right"],
                "merged": Segment,
            },
        }.items()
    ),
)
CharacterReference = object_model(
    "CharacterReference",
    {"character_id": ID, "look_id": ID | None},
)
FrameFields = object_model(
    "FrameFields",
    {
        "prompt_text": Text,
        "visible_character_ids": IDs,
        # 本帧每个可见角色提交的角色卡参考图；空 asset_ids 表示不提交该角色图片。
        "character_references": list[CharacterReference],
        # 整体替换本帧参考的其它 Keyframe；只能引用已有选中图的 Keyframe。
        "reference_keyframe_ids": Annotated[list[ID], Field(max_length=4)],
        # 整体替换本帧参考的地点库普通图片条目 ID；只能引用已有选中图的条目。
        "reference_location_image_ids": Annotated[list[ID], Field(max_length=4)],
    },
    (
        "prompt_text",
        "visible_character_ids",
        "character_references",
        "reference_keyframe_ids",
        "reference_location_image_ids",
    ),
)
FrameOperation = reduce(
    or_,
    tuple(
        operation(name, fields)
        for name, fields in {
            "update_frame_fields": {"keyframe_id": ID, "fields": FrameFields},
            "set_activation": {"segment_id": ID, "start_enabled": bool, "end_enabled": bool},
            "set_aux_references": {"segment_id": ID, "asset_ids": IDs},
            "bind_slot": {"segment_id": ID, "slot": Literal["start", "end"], "keyframe_id": ID},
            "share_boundary": {
                "left_segment_id": ID,
                "right_segment_id": ID,
                "source_keyframe_id": ID | None,
                "expected_adjacency": Literal["cross_shot", "intra_shot"] | None,
            },
            "split_boundary": {
                "left_segment_id": ID,
                "right_segment_id": ID,
                "clone_side": Literal["left_end", "right_start"],
                "copy_selection": bool,
            },
        }.items()
    ),
)


# 地点操作：同一 patch 内新建项用局部 key 引用，Core 分配正式 ID；角度与上限由 Core 模型校验。
Ref = Annotated[str, Field(pattern=r"^(?:[0-9a-f]{32}|[a-z][a-z0-9_-]{0,63})$")]
Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
Degrees = Annotated[float, Field(allow_inf_nan=False)]
Name = Annotated[str, Field(min_length=1, max_length=200)]
KeyLight = object_model("KeyLight", {"description": Text})
location_fields = {
    "name": Name,
    "description": Text,
    "key_light": KeyLight | None,
}
LocationFields = object_model("LocationFields", location_fields, location_fields)
CaptureSource = object_model(
    "CaptureSource",
    {
        "panorama_image_id": Ref,
        "yaw_deg": Degrees,
        "pitch_deg": Degrees,
        "hfov_deg": Degrees,
    },
)
image_fields = {
    "name": Name,
    "kind": Literal["image", "panorama"],
    "description": Text,
    "prompt_text": Text,
    "reference_asset_ids": Annotated[list[ID], Field(max_length=5)],
    "source": CaptureSource | None,
}
ImageFields = object_model("ImageFields", image_fields, image_fields)
LocationOperation = reduce(
    or_,
    tuple(
        operation(name, fields)
        for name, fields in {
            "create_location": {
                "key": Key,
                "name": Name,
                "description": Text,
            },
            "update_location": {"location_id": Ref, "fields": LocationFields},
            "delete_location": {"location_id": ID},
            "upsert_fixture": {
                "location_id": Ref,
                "fixture": Ref,
                "name": Name,
                "description": Text,
            },
            "delete_fixture": {"location_id": Ref, "fixture_id": ID},
            "upsert_state": {"location_id": Ref, "state": Ref, "name": Name, "description": Text},
            "delete_state": {"location_id": Ref, "state_id": ID},
            "create_image": {"location_id": Ref, "key": Key, "fields": ImageFields},
            "update_image": {"image_id": Ref, "fields": ImageFields},
            "delete_image": {"image_id": ID},
            "bind_scene": {"scene_id": ID, "location_id": Ref | None, "state_id": Ref | None},
            "clear_image_selection": {"image_id": ID},
        }.items()
    ),
)


class ScriptEdit(Request):
    scene_ids: Targets
    operations: Annotated[list[ScriptOperation], Field(min_length=1, max_length=100)]


class FrameEdit(Request):
    operations: Annotated[list[FrameOperation], Field(min_length=1, max_length=100)]


class ReferenceImagePlan(Request):
    scene_ids: Targets
    segment_id: ID
    slot_index: Annotated[int, Field(ge=0, le=3, description="其他图片子卡片，0–3。")]
    prompt_text: Annotated[str, Field(min_length=1, max_length=18000, pattern=r"\S")]
    description: Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]
    visible_character_ids: IDs
    character_references: list[CharacterReference]
    reference_asset_ids: Annotated[list[ID], Field(max_length=5)]


class LocationEdit(Request):
    location_ids: IDs
    scene_ids: IDs
    operations: Annotated[list[LocationOperation], Field(min_length=1, max_length=100)]


# 角色造型：Core 分配造型 ID；删除只由人类在卡片编辑中完成。
look_fields = {
    "name": Annotated[str, Field(min_length=1, max_length=100)],
    "appearance": Annotated[str, Field(min_length=1, max_length=2000)],
    "usage": Annotated[str, Field(min_length=1, max_length=1000)],
}
LookFields = object_model("LookFields", look_fields, look_fields)
LookOperation = operation("add_look", {"character_id": ID, **look_fields}) | operation(
    "update_look", {"look_id": ID, "fields": LookFields}
)


class LookEdit(Request):
    operations: Annotated[list[LookOperation], Field(min_length=1, max_length=32)]


narration_track_fields = {
    "text": Text,
    "recipe_params": RecipeParams,
    "seed": Seed,
}
NarrationTrackFields = object_model(
    "NarrationTrackFields", narration_track_fields, narration_track_fields
)
narration_fields = {
    "zh": NarrationTrackFields,
    "en": NarrationTrackFields,
    "clear_selected_audio": Annotated[
        Language | None,
        Field(
            default=None,
            description="指定 zh 或 en 时，只解除该语言对已选音频资产的引用。",
        ),
    ],
}
NarrationFields = object_model("NarrationFields", narration_fields, narration_fields)


class NarrationEdit(Request):
    scene_ids: Targets
    cue_id: ID
    fields: NarrationFields

    @model_validator(mode="after")
    def exact_action(self):
        supplied = self.fields.model_fields_set
        clear = self.fields.clear_selected_audio
        if clear is not None:
            if supplied != {"clear_selected_audio"}:
                raise ValueError("clear_selected_audio 只接受独立的语言解绑动作。")
        elif not supplied - {"clear_selected_audio"}:
            raise ValueError("旁白编辑至少需要一个字段。")
        for language in ("zh", "en"):
            track = getattr(self.fields, language)
            if language in supplied and (track is None or not track.model_fields_set):
                raise ValueError(f"fields.{language} 至少需要一个字段。")
        return self


class Generate(Request):
    kind: Literal[
        "narration",
        "dialogue",
        "keyframe",
        "reference_image",
        "video",
        "upscale",
        "look_sheet",
        "location_image",
        "panorama_capture",
    ]
    target_id: ID
    language: Annotated[
        Language | None,
        Field(description="仅旁白生成需要：zh 或 en，两种语言各自合成。"),
    ] = None
    identity_asset_ids: Annotated[
        list[ID] | None,
        Field(
            max_length=4,
            description="仅 look_sheet（target_id 为造型 ID）：身份参考图 Asset，可为空列表。",
        ),
    ] = None

    @model_validator(mode="after")
    def kind_specific_fields(self):
        if (self.kind == "narration") != (self.language is not None):
            raise ValueError("只有旁白生成需要且必须指定 language（zh 或 en）。")
        if (self.kind == "look_sheet") != (self.identity_asset_ids is not None):
            raise ValueError("只有 look_sheet 需要且必须提供 identity_asset_ids。")
        return self


class GenerationAction(ReadRequest):
    # wait 只观察 Provider 状态，不受项目 revision 约束；cancel/retry/dismiss 是写入，仍需两者。
    action: Literal["wait", "cancel", "retry", "dismiss"]
    generation_ids: Targets

    @model_validator(mode="after")
    def one_target(self):
        if len(self.generation_ids) != len(set(self.generation_ids)):
            raise ValueError("Generation ID 不能重复。")
        if self.action != "wait":
            if len(self.generation_ids) != 1:
                raise ValueError("只有 wait 接受多个目标。")
            if self.expected_revision is None or "idempotency_key" not in self.model_fields_set:
                raise ValueError(
                    "cancel/retry/dismiss 必须提供 expected_revision 与 idempotency_key。"
                )
        return self


class Batch(Request):
    # kind=keyframe：Keyframe 波次；kind=location：地点成套参考图（location.generate_set）。
    kind: Literal["keyframe", "location"]
    action: Literal["start", "continue"]
    target_ids: Targets | None = None
    run_id: ID | None = None

    @model_validator(mode="after")
    def exact(self):
        if self.target_ids is not None and len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("批次目标 ID 不能重复。")
        if (self.action == "start") != (self.target_ids is not None) or (
            self.action == "continue"
        ) != (self.run_id is not None):
            raise ValueError("start 只带目标，continue 只带原 batch_id 或 execution_run_id。")
        return self


class Unlock(Request):
    action: Literal["unlock_visual_production"]


class Assemble(Request):
    kind: Literal["animatic", "scene", "final"]
    scene_id: ID | None = None

    @model_validator(mode="after")
    def exact(self):
        if (self.kind != "final") != (self.scene_id is not None):
            raise ValueError("Scene 装配须指定 Scene；全片装配不能带 Scene。")
        return self


class RunRead(ReadRequest):
    run_id: ID


class RunAction(Request):
    run_id: ID


class RequestRead(ReadRequest):
    request_key: Annotated[str, Field(min_length=1, max_length=200)]


class ProjectRead(ReadRequest):
    cursor: str | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 30


class Candidates(ReadRequest):
    kind: Literal[
        "video_reference_image",
        "character_look_sheet",
        "character_voice",
        "narrator_voice",
        "narration_audio",
        "dialogue_audio",
        "location_image",
        "panorama_capture",
        "keyframe_image",
        "segment_video",
        "video_upscale",
        "final_video",
        "scene_final_video",
        "scene_animatic",
    ]
    target_ids: Targets
    cursor: str | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 30


class KeyframeSelection(Request):
    keyframe_id: ID
    generation_id: ID


class VideoRecipe(Request):
    scene_ids: Targets
    segment_id: ID
    recipe_id: Annotated[str, Field(min_length=1, max_length=128)]


class DialogueTiming(Request):
    scene_ids: Targets
    segment_id: ID
    starts: dict[ID, Annotated[float, Field(ge=0, allow_inf_nan=False)]]
    duration_seconds: Annotated[float, Field(ge=0.2, allow_inf_nan=False)]


MODELS = {
    "edit_script": ScriptEdit,
    "edit_narration": NarrationEdit,
    "edit_keyframes": FrameEdit,
    "edit_locations": LocationEdit,
    "edit_looks": LookEdit,
    "generate_media": Generate,
    "manage_generation": GenerationAction,
    "media_batch": Batch,
    "unlock_production": Unlock,
    "assemble_media": Assemble,
    "read_run": RunRead,
    "cancel_run": RunAction,
    "read_request": RequestRead,
    "read_human_handoff": ProjectRead,
    "read_workflow_state": ProjectRead,
    "list_candidates": Candidates,
    "select_keyframe_candidate": KeyframeSelection,
    "set_video_recipe": VideoRecipe,
    "set_dialogue_timing": DialogueTiming,
    "save_reference_image_plan": ReferenceImagePlan,
}
DESCRIPTIONS = {
    name: description
    for name, description in zip(
        MODELS,
        (
            "局部脚本类型化编辑，Core分配新ID。",
            "局部更新旁白正文/参数，或解除当前音频引用；不自动生成。",
            "更新 Keyframe 计划/辅助图/边界，不生成。",
            "编辑地点语义、独立图片条目与可选Scene关系；新建项以key互引，不能选候选。",
            "新增/修改角色造型（外观、使用场合），不生成、不删除。",
            "生成明确授权的图片、音频或视频候选，或执行一次全景取景；"
            "其他图片用 kind=reference_image，target_id 为 reference_image_plans 中的规划 ID；"
            "不自动选择。",
            "观察/取消/重试/隐藏明确Generation。",
            "成套生成批次：keyframe 波次或 location 成套参考图；continue 带原批次 ID。",
            "解锁视觉生产，建立 Keyframe 与视频计划；不生成。",
            "提交Scene Animatic、Scene成片或全片装配，不自动批准。",
            "只读指定run状态。",
            "显式取消指定领域run。",
            "按原请求key恢复本caller的应用回执。",
            "读取人类审核入口与Core允许动作，不授予人类权限。",
            "读取主流程阶段、必需下一步、可选准备和阻塞原因；推进请求只按必需下一步处理。",
            "分页读取明确目标候选，不选择。",
            "采用一个 Keyframe 的成功候选（keyframe_image 或抽帧），成为后续生成与引用的选中图；"
            "人类可随时改选。",
            "设置单Segment视频模式，不生成。",
            "按已选 TTS WAV 的真实时长设置逐句发声起点与 Segment 视频时长。",
            "新建或编辑一个 Segment 的其他图片规划，slot_index 为 0–3；"
            "可规划任意画面内容，不限角色或地点，无时间位置；不生成、不选择。"
            "用 read_story 的 selection/keyframe 扩展读取 video_inputs 中的规划 ID 和实际绑定。",
        ),
        strict=True,
    )
}


def translate(name, request):
    args = request.model_dump(
        exclude={"project_id", "expected_revision", "idempotency_key"}, exclude_unset=True
    )
    if isinstance(request, LocationEdit):
        args["scope"] = {key: args.pop(key) for key in ("location_ids", "scene_ids")}
    elif "scene_ids" in args:
        args["scope"] = {"scene_ids": args.pop("scene_ids")}
    if isinstance(request, NarrationEdit):
        if request.fields.clear_selected_audio is not None:
            args.pop("fields")
            args["language"] = request.fields.clear_selected_audio
            return "narration.clear_selection", args
        args["fields"].pop("clear_selected_audio", None)
    direct = {
        "edit_script": "script.apply_operations",
        "edit_narration": "narration.update_cue",
        "edit_keyframes": "keyframe.apply_operations",
        "edit_locations": "location.apply_operations",
        "edit_looks": "reference.apply_look_operations",
        "read_run": "run.get_status",
        "cancel_run": "run.cancel",
        "read_request": "project.get_request",
        "read_human_handoff": "project.get_handoff",
        "read_workflow_state": "project.get_workflow_state",
        "list_candidates": "project.list_candidates",
        "select_keyframe_candidate": "keyframe.select_candidate",
        "set_video_recipe": "video.set_recipe",
        "set_dialogue_timing": "dialogue.set_timing",
        "save_reference_image_plan": "video.save_reference_image_plan",
    }
    if name in direct:
        return direct[name], args
    if isinstance(request, Generate):
        command, target = {
            "narration": ("narration.generate", "cue_id"),
            "dialogue": ("dialogue.generate", "dialogue_line_id"),
            "keyframe": ("keyframe.generate", "keyframe_id"),
            "reference_image": ("video.generate_reference_image", "image_id"),
            "video": ("video.generate", "segment_id"),
            "upscale": ("video.upscale", "segment_id"),
            "look_sheet": ("reference.generate_look_sheet", "look_id"),
            "location_image": ("location.generate_image", "image_id"),
            "panorama_capture": ("location.capture_panorama", "image_id"),
        }[request.kind]
        if request.kind == "narration":
            return command, {target: request.target_id, "language": request.language}
        if request.kind == "look_sheet":
            return command, {
                target: request.target_id,
                "identity_asset_ids": request.identity_asset_ids,
            }
        return command, {target: request.target_id}
    if isinstance(request, GenerationAction):
        return f"generation.{request.action}", (
            {"generation_ids": request.generation_ids}
            if request.action == "wait"
            else {"generation_id": request.generation_ids[0]}
        )
    if isinstance(request, Batch):
        commands = {
            "keyframe": ("keyframe.generate_batch", "keyframe.continue_batch"),
            "location": ("location.generate_set", "location.generate_set"),
        }[request.kind]
        return (
            (commands[0], {"target_ids": request.target_ids})
            if request.action == "start"
            else (commands[1], {"run_id": request.run_id})
        )
    if isinstance(request, Unlock):
        return "visual_production.unlock", {}
    if isinstance(request, Assemble):
        return {
            "animatic": "animatic.generate_scene",
            "scene": "final.assemble_scene",
            "final": "final.assemble",
        }[request.kind], ({} if request.kind == "final" else {"scene_id": request.scene_id})
    raise ValueError("未开放该生产工具。")
