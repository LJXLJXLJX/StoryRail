from __future__ import annotations

import hashlib
import io
import json
import struct
import wave
from dataclasses import replace
from uuid import uuid4

from core.director_commands import LocationViewSelection, parse_location_operations_patch
from core.director_proposals import (
    CharacterCardProposal,
    DialogueLineProposal,
    KeyframePlanProposal,
    KeyframeSegmentProposal,
    KeyframeShotProposal,
    NarrationCueProposal,
    NarrationTrackProposal,
    NarratorProfileProposal,
    ReferenceLibraryProposal,
    SceneProposal,
    ShotProposal,
    ShotSegmentProposal,
    StructuredDirectorScriptProposal,
)
from core.director_proposals.script_codec import (
    parse_structured_director_script_revision,
)
from core.model_providers.boundary import (
    ArtifactDescriptor,
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)
from core.model_providers.manifest import Capability
from core.model_providers.minimax_h3.prompt_contract import H3PromptProposal
from core.project_settings import ProjectAspectRatio
from core.structured_director import (
    Asset,
    StructuredDirectorStore,
)
from core.structured_director.models import (
    LocationKind,
    NarrationLanguage,
    ReferenceGenerationKind,
    Shot,
    ShotSegment,
    StructuredDirectorDocument,
)


def png_header_bytes(label: str, width: int = 2048, height: int = 1024) -> bytes:
    """带 IHDR 的 PNG 头：满足 Core 读宽高的契约（默认 2:1 全景），标签保证字节互不相同。"""
    ihdr = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + label.encode()


def add_image_asset(
    store: StructuredDirectorStore, *, width: int = 2048, height: int = 1024
) -> str:
    """写入真实图片字节（默认 2:1 全景头）并登记 Asset；返回 Asset ID。"""
    document = store.read()
    content = png_header_bytes(uuid4().hex, width, height)
    digest = hashlib.sha256(content).hexdigest()
    relative_path = f"assets/images/library/{digest[:12]}.png"
    path = store._project_directory / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    asset = Asset(digest[:32], "image/png", len(content), digest, relative_path)
    store._atomic_write(
        replace(document, revision=document.revision + 1, assets=(*document.assets, asset))
    )
    return asset.id


def wav_bytes(*, duration_seconds: float = 1.0, sample_rate: int = 8_000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(b"\x00\x00" * int(duration_seconds * sample_rate))
    return output.getvalue()


class RecordingProposer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.restart_values: list[bool] = []

    async def propose(self, **kwargs: object) -> ReferenceLibraryProposal:
        self.restart_values.append(bool(kwargs["restart_thread"]))
        if self.fail:
            raise RuntimeError("模拟 Agent 中断")
        return ReferenceLibraryProposal(
            characters=(
                CharacterCardProposal(
                    "小满",
                    "短发，蓝色外套，一直带着红色行李箱",
                    "年轻、克制、语速偏慢",
                ),
            ),
        )


class RecordingH3PromptWriter:
    def __init__(self) -> None:
        self.contexts = []

    async def write(self, context):
        self.contexts.append(context)
        return H3PromptProposal("这是一条符合当前画面输入的中文视频提示词。")


class RecordingScriptProposer:
    def __init__(self, *, fail: bool = False, unknown_character: bool = False) -> None:
        self.fail = fail
        self.unknown_character = unknown_character
        self.restart_values: list[bool] = []

    async def propose(self, **kwargs: object) -> StructuredDirectorScriptProposal:
        self.restart_values.append(bool(kwargs["restart_thread"]))
        if self.fail:
            raise RuntimeError("模拟结构化脚本 Agent 中断")
        characters = kwargs["characters"]
        character_id = "f" * 32 if self.unknown_character else characters[0].id
        return StructuredDirectorScriptProposal(
            scenes=(
                SceneProposal(
                    title="末班车",
                    summary="小满在停用前的车站等最后一班车。",
                    setting="傍晚，空旷站台，冷蓝色天光。",
                    shots=(
                        ShotProposal(
                            visible_character_ids=(character_id,),
                            composition="中远景，人物位于画面右侧。",
                            camera_movement="缓慢推近。",
                            action="小满握住行李箱拉杆，抬头看向站牌。",
                            audio_direction="远处风声和站内电流声。",
                            transition_in=None,
                        ),
                    ),
                    segments=(
                        ShotSegmentProposal(
                            shot_indexes=(0,),
                            duration_estimate_seconds=6.0,
                            action="小满抬头看向站牌。",
                            dialogue_lines=(
                                DialogueLineProposal(
                                    character_id,
                                    "还会来吗？",
                                    "轻声，带一点迟疑",
                                ),
                            ),
                            boundary_from_previous=None,
                        ),
                    ),
                    narration_cues=(),
                ),
            ),
        )


class ScopedRevisionScriptProposer(RecordingScriptProposer):
    def __init__(self) -> None:
        super().__init__()
        self.scene_revision_requests: list[dict[str, object]] = []
        self.return_wrong_scene_id = False

    async def revise(self, **kwargs: object):
        self.scene_revision_requests.append(kwargs)
        state = json.loads(str(kwargs["current_script_json"]))
        for scene in state["scenes"]:
            scene.pop("narration_timing", None)
        targets = set(kwargs["target_scene_ids"])
        scenes = [scene for scene in state["scenes"] if scene["id"] in targets]
        scenes[0]["summary"] = "仅目标 Scene 被局部回改。"
        if self.return_wrong_scene_id:
            scenes[0]["id"] = "f" * 32
        return parse_structured_director_script_revision(
            json.dumps(
                {
                    "reply_markdown": "已完成局部回改。",
                    "operations": [
                        {
                            "operation": "replace_scene",
                            "scene_id": scenes[0]["id"],
                            "after_scene_id": None,
                            "scene": scenes[0],
                            "segment": None,
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )


class AssessmentScriptProposer(RecordingScriptProposer):
    async def revise(self, **_kwargs: object):
        return parse_structured_director_script_revision(
            json.dumps(
                {
                    "reply_markdown": (
                        "Shot 2、3、4 需要保持叙事与视线连续，"
                        "但不需要共享首尾关键帧。\n\n本轮仅作评估，未修改脚本。"
                    ),
                    "operations": [],
                },
                ensure_ascii=False,
            )
        )


class NarrationReferenceProposer(RecordingProposer):
    async def propose(self, **kwargs: object) -> ReferenceLibraryProposal:
        proposal = await super().propose(**kwargs)
        return replace(
            proposal,
            narrator=NarratorProfileProposal(
                "旁白", "克制、温和、纪录片式表达", "Calm, warm documentary narrator."
            ),
        )


class NarrationScriptProposer(RecordingScriptProposer):
    """旁白驱动初稿：只有一条双语 Cue，TTS 选择后再规划 Shot。"""

    async def propose(self, **kwargs: object) -> StructuredDirectorScriptProposal:
        base = await super().propose(**kwargs)
        return StructuredDirectorScriptProposal(
            scenes=(
                replace(
                    base.scenes[0],
                    driver="narration",
                    shots=(),
                    segments=(),
                    narration_cues=(
                        NarrationCueProposal(
                            zh=NarrationTrackProposal(
                                text="末班车到来以前，站台仍旧保持着漫长的安静。", seed=42
                            ),
                            en=NarrationTrackProposal(
                                text="Before the last train arrives, the platform stays quiet.",
                                seed=42,
                            ),
                        ),
                    ),
                ),
            ),
        )


class TwoSceneScriptProposer(RecordingScriptProposer):
    async def propose(self, **kwargs: object) -> StructuredDirectorScriptProposal:
        base = await super().propose(**kwargs)
        return StructuredDirectorScriptProposal(
            scenes=(
                base.scenes[0],
                replace(
                    base.scenes[0],
                    title="第二场",
                    summary="小满进入车厢。",
                    setting="末班车车厢内。",
                ),
            )
        )


class TwoShotScriptProposer(RecordingScriptProposer):
    async def propose(self, **kwargs: object) -> StructuredDirectorScriptProposal:
        base = await super().propose(**kwargs)
        first = base.scenes[0].shots[0]
        return StructuredDirectorScriptProposal(
            scenes=(
                replace(
                    base.scenes[0],
                    shots=(
                        first,
                        replace(first, action="小满进入到站的末班车。"),
                    ),
                ),
            )
        )


class RealisticEditingScriptProposer(RecordingScriptProposer):
    def __init__(self) -> None:
        super().__init__()
        self.current_scripts: list[dict[str, object]] = []

    async def revise(self, **kwargs: object):
        current = json.loads(str(kwargs["current_script_json"]))
        self.current_scripts.append(current)
        scenes = current["scenes"]
        for scene in scenes:
            scene.pop("narration_timing", None)
        message = str(kwargs["user_message"])
        if "删除" in message:
            operation = {
                "operation": "delete_scene",
                "scene_id": scenes[-1]["id"],
                "after_scene_id": None,
                "scene": None,
                "shot_id": None,
                "segment": None,
            }
        elif "插入" in message:
            inserted = json.loads(json.dumps(scenes[0], ensure_ascii=False))
            inserted["id"] = None
            inserted["title"] = "雨棚下的误会"
            inserted["summary"] = "小满误把远处车灯当成末班车，随后发现只是清扫车。"
            for shot in inserted["shots"]:
                shot["id"] = None
                for segment in shot["segments"]:
                    segment["id"] = None
            operation = {
                "operation": "insert_scene",
                "scene_id": None,
                "after_scene_id": scenes[0]["id"],
                "scene": inserted,
                "shot_id": None,
                "segment": None,
            }
        elif "修改" in message:
            scenes[0]["title"] = "暮色中的末班车"
            scenes[0]["setting"] = "入夜前，细雨中的空旷站台，冷蓝天光逐渐转暗。"
            operation = {
                "operation": "replace_scene",
                "scene_id": scenes[0]["id"],
                "after_scene_id": None,
                "scene": scenes[0],
                "shot_id": None,
                "segment": None,
            }
        else:
            raise AssertionError("测试消息未覆盖")
        return parse_structured_director_script_revision(
            json.dumps({"reply_markdown": "已按要求更新脚本。", "operations": [operation]})
        )


class ContinuousKeyframePlanner:
    def __init__(self) -> None:
        self.prompt_requests: list[dict[str, object]] = []

    async def propose(self, **kwargs: object) -> KeyframePlanProposal:
        scene = kwargs["scenes"][0]
        first, second = scene.shots
        # Shot 绑定了地点视图时两帧都以视图为编辑底图。
        view_id = first.view_id
        mode = "edit" if view_id is not None else None
        # 这个静态边界只出现 Shot 可见角色中的第一个；其余角色不得被带入生图输入。
        character_ids = tuple(item.id for item in first.visible_characters[:1])
        second_character_ids = tuple(item.id for item in second.visible_characters[:1])
        return KeyframePlanProposal(
            (
                KeyframeShotProposal(
                    shot_id=first.id,
                    continues_from_previous_shot=False,
                    start_prompt_text="小满站在站牌旁，手扶行李箱，尚未抬头。",
                    start_visible_character_ids=character_ids,
                    start_environment_mode=mode,
                    start_environment_view_id=view_id,
                    segments=(
                        KeyframeSegmentProposal(
                            first.segments[0].id,
                            "both",
                            "小满已经抬头看向站牌，手仍扶住行李箱。",
                            character_ids,
                            mode,
                            view_id,
                        ),
                    ),
                ),
                KeyframeShotProposal(
                    shot_id=second.id,
                    continues_from_previous_shot=True,
                    start_prompt_text="小满已经抬头看向站牌，手仍扶住行李箱。",
                    start_visible_character_ids=character_ids,
                    start_environment_mode=mode,
                    start_environment_view_id=view_id,
                    segments=(
                        KeyframeSegmentProposal(
                            second.segments[0].id,
                            "both",
                            "远处车灯已经进入画面，近景中没有角色。",
                            second_character_ids,
                            mode,
                            view_id,
                        ),
                    ),
                ),
            )
        )

    async def generate_prompt(self, **kwargs: object) -> str:
        self.prompt_requests.append(dict(kwargs))
        return "观察实际附件，保持站台布局；人物停在画面右侧，使用傍晚冷蓝色天光。"


class SingleKeyframePlanner:
    async def propose(self, **kwargs: object) -> KeyframePlanProposal:
        shot = kwargs["scenes"][0].shots[0]
        character_ids = tuple(item.id for item in shot.visible_characters)
        return KeyframePlanProposal(
            (
                KeyframeShotProposal(
                    shot_id=shot.id,
                    continues_from_previous_shot=False,
                    start_prompt_text="角色尚未开始动作的静态首帧。",
                    start_visible_character_ids=character_ids,
                    segments=tuple(
                        KeyframeSegmentProposal(
                            segment.id,
                            "both",
                            "本段动作刚刚完成的静态尾帧。",
                            character_ids,
                        )
                        for segment in shot.segments
                    ),
                ),
            )
        )


class FailingKeyframePlanner:
    async def propose(self, **kwargs: object) -> KeyframePlanProposal:
        del kwargs
        raise RuntimeError("fetch failed")


class RecordingScopedKeyframePlanner:
    def __init__(self) -> None:
        self.scene_requests: list[tuple[str, ...]] = []

    async def propose(self, **kwargs: object) -> KeyframePlanProposal:
        scenes = kwargs["scenes"]
        self.scene_requests.append(tuple(scene.id for scene in scenes))
        return KeyframePlanProposal(
            tuple(
                KeyframeShotProposal(
                    shot_id=shot.id,
                    continues_from_previous_shot=False,
                    start_prompt_text=f"{scene.title}的静态首帧。",
                    start_visible_character_ids=tuple(item.id for item in shot.visible_characters),
                    segments=tuple(
                        KeyframeSegmentProposal(
                            segment.id,
                            "start",
                            f"{scene.title}的静态尾帧。",
                            tuple(item.id for item in shot.visible_characters),
                        )
                        for segment in shot.segments
                    ),
                )
                for scene in scenes
                for shot in scene.shots
            )
        )


def create_project(
    store: StructuredDirectorStore,
    aspect_ratio: ProjectAspectRatio = ProjectAspectRatio.LANDSCAPE,
):
    return store.create_project(
        title="测试项目",
        aspect_ratio=aspect_ratio,
        director_plan_markdown="# 完整导演方案\n\n小满带着红色行李箱等候末班车。",
        narration_languages=tuple(NarrationLanguage),
    )


class RecordingProvider:
    def __init__(
        self, *, media_type: str, content: bytes, duration_seconds: float | None = None
    ) -> None:
        self.plugin_id = "test.voice"
        self.generate_plugin_id = "test.image.generate"
        self.edit_plugin_id = "test.image.edit"
        self.plugin_version = 1
        self.media_type = media_type
        self.content = content
        self.duration_seconds = duration_seconds
        self.requests: list[object] = []
        self.observations = [GenerationPhase.RUNNING, GenerationPhase.SUCCEEDED]

    def submit(self, request: object) -> ProviderHandle:
        self.requests.append(request)
        return ProviderHandle(self.plugin_id, self.plugin_version, "external-1")

    def submit_recipe(self, request: object) -> ProviderHandle:
        return self.submit(request)

    def submit_generate(self, request: object) -> ProviderHandle:
        self.requests.append(request)
        return ProviderHandle(self.generate_plugin_id, self.plugin_version, "external-1")

    def submit_edit(self, request: object) -> ProviderHandle:
        self.requests.append(request)
        return ProviderHandle(self.edit_plugin_id, self.plugin_version, "external-1")

    def observe(self, _handle: ProviderHandle) -> GenerationObservation:
        phase = self.observations.pop(0)
        if phase is GenerationPhase.SUCCEEDED:
            descriptor = ArtifactDescriptor(
                "artifact-1",
                self.media_type,
                len(self.content),
                hashlib.sha256(self.content).hexdigest(),
                self.duration_seconds,
            )
            return GenerationObservation(phase, 1.0, "完成", descriptor)
        return GenerationObservation(phase, 0.5, "生成中")

    def cancel(self, _handle: ProviderHandle) -> GenerationObservation:
        return GenerationObservation(GenerationPhase.CANCELLED, 0.0, "已取消")

    def read_artifact(self, _handle: ProviderHandle, _artifact_id: str) -> bytes:
        return self.content


class FailingCancelProvider(RecordingProvider):
    def cancel(self, _handle: ProviderHandle) -> GenerationObservation:
        raise RuntimeError("模拟取消调用中断")


class FailingSubmitProvider(RecordingProvider):
    def __init__(self, error: ModelProviderError) -> None:
        super().__init__(media_type="audio/wav", content=b"unused")
        self.error = error

    def submit(self, request: object) -> ProviderHandle:
        self.requests.append(request)
        raise self.error


class UnreachableObserveProvider(RecordingProvider):
    def observe(self, _handle: ProviderHandle) -> GenerationObservation:
        raise ModelProviderError("transport_error", "节点离线", retryable=True)


class InvalidObserveProvider(RecordingProvider):
    def observe(self, _handle: ProviderHandle) -> GenerationObservation:
        raise ModelProviderError("invalid_response", "节点返回了不合法的状态。")


async def upload_narrator_voice(service, document, content: bytes | None = None):
    """为中英旁白各上传参考音色并补齐完整文字稿；Breeze 克隆要求两者同时存在。"""

    narrator = document.reference_library.narrator
    voiced = document
    for language in document.narration_languages:
        voiced = await service.upload_narrator_voice(
            narrator_id=narrator.id,
            language=language,
            media_type="audio/wav",
            content=content if content is not None else wav_bytes(),
            expected_revision=voiced.revision,
        )
    narrator = voiced.reference_library.narrator
    for language, voice in narrator.voices:
        narrator = narrator.with_voice(
            language, replace(voice, voice_reference_transcript="旁白参考音频的完整文字稿。")
        )
    return await service.update_narrator(narrator, expected_revision=voiced.revision)


async def synthesize_narration(service, cue_id: str, expected_revision: int, language: str):
    """提交一条旁白 TTS 并推进到成功；返回 (document, generation_id)。"""

    found = service._registry.recipe_for(Capability.SPEECH_SYNTHESIZE)
    provider = None if found is None else found[0].recipes[found[1].id]
    if isinstance(provider, RecordingProvider):
        # RecordingProvider 的观察序列只够一个任务；双语每种语言都要重新给出一轮。
        provider.observations = [GenerationPhase.RUNNING, GenerationPhase.SUCCEEDED]
    submitted = await service.generate_narration(
        cue_id=cue_id, language=language, expected_revision=expected_revision
    )
    generation_id = submitted.generations[-1].id
    await service._generation_observer.refresh_generation(generation_id)
    completed = await service._generation_observer.refresh_generation(generation_id)
    return completed, generation_id


async def synthesize_and_select_narration(
    service, cue_id: str, expected_revision: int, languages: tuple[str, ...] = ("zh", "en")
):
    """双语旁白：逐语言合成并选择音频；返回 (document, {language: generation_id})。"""

    document = None
    revision = expected_revision
    generation_ids: dict[str, str] = {}
    for language in languages:
        completed, generation_id = await synthesize_narration(service, cue_id, revision, language)
        document = await service.select_narration_audio(
            cue_id=cue_id, generation_id=generation_id, expected_revision=completed.revision
        )
        revision = document.revision
        generation_ids[language] = generation_id
    return document, generation_ids


def plan_narration_shots(store: StructuredDirectorStore, document):
    """旁白音频选定后为首个 Narration Scene 规划两个 Shot，Cue 覆盖全部 Shot。"""

    scenes = document.director_script.scenes
    scene = scenes[0]
    character_id = document.reference_library.characters[0].id
    shots = (
        Shot(
            id=uuid4().hex,
            visible_character_ids=(character_id,),
            composition="中远景，人物位于画面右侧。",
            camera_movement="缓慢推近。",
            action="小满握住行李箱拉杆，抬头看向站牌。",
            audio_direction="远处风声和站内电流声。",
            transition_in=None,
        ),
        Shot(
            id=uuid4().hex,
            visible_character_ids=(character_id,),
            composition="中远景，人物位于画面右侧。",
            camera_movement="缓慢推近。",
            action="车灯从远处进入画面，小满仍在等待。",
            audio_direction="远处风声和站内电流声。",
            transition_in=None,
        ),
    )
    segments = (
        ShotSegment(uuid4().hex, (shots[0].id,), 1.5, "小满抬头看向站牌。", (), None),
        ShotSegment(uuid4().hex, (shots[1].id,), 1.5, "远处车灯出现。", (), None),
    )
    return store.save_director_script(
        (replace(scene, shots=shots, segments=segments), *scenes[1:]),
        expected_revision=document.revision,
    )


def install_location(
    store: StructuredDirectorStore,
    *,
    view_asset_id: str | None = None,
    scene_ids: tuple[str, ...] = (),
    kind: LocationKind = LocationKind.INTERIOR,
    name: str = "共享客厅",
) -> StructuredDirectorDocument:
    """经正式地点操作建一个地点和一个视图，可选绑定 Scene 及其全部 Shot；
    视图图片走人类候选选择入口。"""
    document = store.read()
    shot_ids = [
        shot.id
        for scene in (() if document.director_script is None else document.director_script.scenes)
        if scene.id in scene_ids
        for shot in scene.shots
    ]
    patch = parse_location_operations_patch(
        {
            "scope": {"location_ids": [], "scene_ids": list(scene_ids), "shot_ids": shot_ids},
            "operations": [
                {
                    "op": "create_location",
                    "key": "place",
                    "name": name,
                    "kind": kind.value,
                    "description": "固定空间、陈设和光线。",
                },
                {
                    "op": "update_location",
                    "location_id": "place",
                    "fields": {"master_prompt_text": "空间全景，无人物。"},
                },
                {
                    "op": "create_view",
                    "location_id": "place",
                    "key": "main",
                    "fields": {
                        "name": "主机位",
                        "purpose": "人眼高中景，覆盖本地点的主要对话",
                        "azimuth_deg": 0.0,
                    },
                },
                *(
                    {
                        "op": "bind_scene",
                        "scene_id": scene_id,
                        "location_id": "place",
                        "state_id": None,
                    }
                    for scene_id in scene_ids
                ),
                *(
                    {"op": "bind_shot", "shot_id": shot_id, "view_id": "main"}
                    for shot_id in shot_ids
                ),
            ],
        }
    )
    document, _receipt, data = store.apply_location_operations(
        patch, expected_revision=document.revision, command_id=uuid4().hex
    )
    if view_asset_id is not None:
        # 局部导入：tests/build_*_fixture.py 在 pytest 之外运行，那里 scripts 包不在导入路径上。
        from scripts.harness.fixtures.candidates import register_image_candidate

        view_id = data["created_ids"]["main"]
        register_image_candidate(
            store,
            kind=ReferenceGenerationKind.LOCATION_VIEW_IMAGE,
            target_id=view_id,
            asset_id=view_asset_id,
        )
        store.select_location_view(
            LocationViewSelection(view_id, view_asset_id),
            expected_revision=store.read().revision,
            command_id=uuid4().hex,
        )
    return store.read()
