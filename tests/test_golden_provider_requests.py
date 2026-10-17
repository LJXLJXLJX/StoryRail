"""黄金 Provider 请求：代表性项目与 Playground 操作发给各外部服务的线上请求逐字节不变。

录制方式见 ``golden_provider_requests``。黄金文件在 Provider 插件化重构前的代码上录制，
重构期间只能为同一行为重新装配插件，不能改写黄金文件。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from conftest import Journey, JourneyStepError, OracleHttpServer
from golden_provider_requests import (
    GoldenProviders,
    assert_golden,
    golden_providers,
    mp4_bytes,
    panorama_png_bytes,
    png_bytes,
    wav_bytes,
)
from structured_director_fixtures import install_location
from video_recipes import video_wire_dict, video_wire_mode

from core.structured_director import StructuredDirectorService


class GoldenHttpServer(OracleHttpServer):
    """与 oracle 相同的真实 loopback HTTP，Provider 换成录制线上请求的真实插件。"""

    def __init__(self, root: Path, policy_path: Path, golden: GoldenProviders) -> None:
        self.golden = golden
        super().__init__(root, policy_path)

    def _service_factory(self, project_id: str) -> StructuredDirectorService:
        return StructuredDirectorService(
            self.workspaces.structured_director_store(project_id),
            registry=self.golden.registry,
        )

    def _playground_service(self):
        from core.playground.service import PlaygroundService
        from core.playground.store import PlaygroundStore

        return PlaygroundService(
            PlaygroundStore(self.stories_root / ".playground"),
            self.golden.registry,
        )


@pytest.fixture
def golden_server(stories_root: Path, tmp_path: Path):
    golden = golden_providers(tmp_path / "runtime")
    server = GoldenHttpServer(stories_root, tmp_path / "access_policy.json", golden).start()
    try:
        yield server
    finally:
        server.stop()


def _ok(step: str, response: tuple[int, Any]) -> Any:
    status, body = response
    if status >= 400:
        raise JourneyStepError(step, status, body)
    return body


class GoldenJourney(Journey):
    """在 Journey 之上补充黄金场景需要的 Web 同款入口；每步登记录制步骤名。"""

    def __init__(self, server: GoldenHttpServer) -> None:
        super().__init__(server)
        self.log = server.golden.log

    def step(self, name: str) -> None:
        self.log.step = name

    def upload_media(self, label: str, content: bytes, media_type: str) -> str:
        self.log.label(content, label)
        path = f"{self.resource}/assets/media?" + urlencode(
            {"expected_revision": self._revision(), "filename": label}
        )
        _ok("upload_media", self._server.upload(path, content, media_type))
        return self.asset_id(content)

    def upload_image(self, label: str, category: str) -> str:
        content = self.log.label(png_bytes(label), label)
        path = f"{self.resource}/assets/images?" + urlencode(
            {"expected_revision": self._revision(), "category": category, "filename": label}
        )
        _ok("upload_image", self._server.upload(path, content, "image/png"))
        return self.asset_id(content)

    @staticmethod
    def _pending_keyframe_ids(snap: dict) -> list[str]:
        """只看启用的帧；单帧 Segment 的未启用槽位不生成。"""
        return [
            frame_id
            for frame_id in _enabled_keyframe_ids(snap)
            if not any(
                generation["kind"] == "keyframe_image"
                and generation["target_id"] == frame_id
                and generation["phase"] == "succeeded"
                and not generation["dismissed"]
                for generation in snap["generations"]
            )
        ]

    def select_keyframe_candidates(self) -> dict:
        for frame_id in _enabled_keyframe_ids(self.snapshot()):
            output = self.latest_output("keyframe_image", frame_id)
            self._post(
                "select_keyframe_candidates",
                f"{self.resource}/keyframes/{frame_id}/select",
                {"expected_revision": self._revision(), "asset_id": output["output_asset_id"]},
            )
        return self.snapshot()

    def install_location(self, name: str, scene_id: str, view_asset_id: str) -> str:
        """经正式地点操作建库、绑定 Scene 并选定视图图片；返回视图 ID。"""
        store = self._server.workspaces.structured_director_store(self.project_id)
        document = install_location(
            store, view_asset_id=view_asset_id, scene_ids=(scene_id,), name=name
        )
        return document.location_library.locations[-1].views[0].id

    def asset_id(self, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        return next(item["id"] for item in self.document()["assets"] if item["sha256"] == digest)

    def latest_output(self, kind: str, target_id: str, **match: Any) -> dict:
        snap = self.wait_generations(kind=kind, target_ids={target_id})
        return next(
            generation
            for generation in reversed(snap["generations"])
            if generation["kind"] == kind
            and generation["target_id"] == target_id
            and generation["phase"] == "succeeded"
            and all(generation.get(key) == value for key, value in match.items())
        )


def _segment_seed(segment_id: str) -> int:
    """Segment 视频与超分首次提交的默认 seed：Segment ID 前 16 位十六进制。"""
    return int(segment_id[:16], 16) % (2**63)


def _enabled_keyframe_ids(snap: dict) -> list[str]:
    enabled = []
    for segment in snap["keyframe_plan"]["segments"]:
        for side in ("start", "end"):
            frame_id = segment[f"{side}_keyframe_id"]
            if segment[f"{side}_enabled"] and frame_id not in enabled:
                enabled.append(frame_id)
    return enabled


def _drama_scene(character_id: str) -> dict:
    """一个 Shot、两个 Segment：第一个有对白（默认 Ref2VA），第二个无对白（默认 FL2VA）。"""
    scene = Journey.drama_scene(character_id)
    shot = scene["shots"][0]
    shot["segments"].append(
        {
            "duration_estimate_seconds": 4.5,
            "action": "小满松开拉杆，转身望向轨道尽头。",
            "dialogue_lines": [],
            "boundary_from_previous": {
                "reason": "model_constraint",
                "continuity_instruction": "从抬头看站牌的静止瞬间继续",
            },
        }
    )
    return scene


def _narration_scene() -> dict:
    scene = Journey.narration_scene()
    cue = scene["narration_cues"][0]
    cue["zh"]["seed"] = 101
    cue["en"]["seed"] = 202
    cue["en"]["recipe_params"] = {
        "breeze_tts2.clone": {
            "performance_instruction": "Slow and calm, with a short pause after 'arrives'."
        }
    }
    return scene


def test_project_provider_requests(golden_server: GoldenHttpServer) -> None:
    server = golden_server
    journey = GoldenJourney(server)
    journey.create_project(title="黄金项目")
    journey.propose_references()
    snap = journey.snapshot()
    character_id = snap["reference_library"]["characters"][0]["id"]
    narrator_id = snap["reference_library"]["narrator"]["id"]
    card = f"{journey.resource}/characters/{character_id}"

    journey.step("character.voice_design")
    journey._post(
        "voice_design",
        f"{card}/voice-generations",
        {
            "expected_revision": journey._revision(),
            "voice_description": "年轻、克制、语速偏慢",
            "sample_text": "还会来吗？",
            "seed": 7,
        },
    )
    journey.latest_output("character_voice", character_id)

    journey.step("narrator.voice_design")
    for language, description, sample, seed in (
        ("zh", "克制、温和、纪录片式表达", "站台很安静。", 11),
        ("en", "Calm, warm documentary narrator.", "The platform is quiet.", 12),
    ):
        journey._post(
            "narrator_voice_design",
            f"{journey.resource}/narrator/voice-generations",
            {
                "expected_revision": journey._revision(),
                "narrator_id": narrator_id,
                "language": language,
                "voice_description": description,
                "sample_text": sample,
                "seed": seed,
            },
        )
        journey.latest_output("narrator_voice", narrator_id, language=language)

    journey.step("character.look_sheet")
    current = journey.snapshot()["reference_library"]["characters"][0]
    journey._put(
        "character_looks",
        card,
        {
            "expected_revision": journey._revision(),
            "name": current["name"],
            "visual_description": current["visual_description"],
            "voice_description": current["voice_description"],
            "voice_reference_asset_id": current["voice_reference_asset_id"],
            "looks": [
                {"id": None, "name": "冬装", "appearance": "蓝色外套，红色行李箱", "usage": "全片"},
                {"id": None, "name": "便服", "appearance": "灰色卫衣", "usage": "回忆段落"},
            ],
        },
    )
    winter, casual = (
        item["id"] for item in journey.snapshot()["reference_library"]["characters"][0]["looks"]
    )
    reference_upload = journey.upload_image("upload:小满服装参考.png", "character_reference")
    journey._post(
        "look_sheet",
        f"{card}/looks/{winter}/sheet-generations",
        {"expected_revision": journey._revision(), "identity_asset_ids": [reference_upload]},
    )
    generation = journey.latest_output("character_look_sheet", winter)
    journey._post(
        "look_sheet_select",
        f"{card}/looks/{winter}/select-sheet",
        {"expected_revision": journey._revision(), "generation_id": generation["id"]},
    )
    journey._post(
        "look_select_asset",
        f"{card}/looks/{casual}/select-asset",
        {"expected_revision": journey._revision(), "asset_id": reference_upload},
    )

    journey.approve_references()
    journey.apply_script(scenes=[_drama_scene(character_id), _narration_scene()])

    journey.step("narration.tts")
    voice = journey.log.label(wav_bytes("upload:旁白参考音色.wav", 2.0), "upload:旁白参考音色.wav")
    journey.select_narrator_voice(content=voice)
    journey.select_narration_audio()
    journey.plan_narration_shots()

    journey.step("narration.regenerate")
    narration_scene = journey.snapshot()["director_script"]["scenes"][1]
    cue_id = narration_scene["narration_cues"][0]["id"]
    journey._post(
        "narration_regenerate",
        f"{journey.resource}/scenes/{narration_scene['id']}/narration-cues/{cue_id}/generate",
        {"expected_revision": journey._revision(), "language": "zh"},
    )
    journey.wait_generations(kind="narration_audio", target_ids={cue_id})
    drama, narration = journey.snapshot()["director_script"]["scenes"]
    drama_shot = drama["shots"][0]
    narration_shot = narration["shots"][0]
    first_segment, second_segment = (item["id"] for item in drama["segments"])
    narration_segment = narration["segments"][0]["id"]

    journey.step("location.install")
    station_image = journey.upload_image("upload:空旷站台视图.png", "location_view")
    night_image = journey.upload_image("upload:入夜站台视图.png", "location_view")
    station = journey.install_location("空旷站台", drama["id"], station_image)
    night = journey.install_location("入夜站台", narration["id"], night_image)

    journey.step("keyframe.generate")
    journey.unlock_visual_production()
    journey.plan_keyframes(
        proposal={
            "shots": [
                {
                    "shot_id": drama_shot["id"],
                    "continues_from_previous_shot": False,
                    "start_prompt_text": "小满站在站台右侧，握着红色行李箱拉杆抬头。",
                    "start_visible_character_ids": [character_id],
                    "start_character_references": [
                        {"character_id": character_id, "look_id": winter}
                    ],
                    "start_environment_view_id": station,
                    "start_environment_mode": "edit",
                    "start_environment_none_reason": None,
                    "segments": [
                        {
                            "segment_id": first_segment,
                            "frame_strategy": "both",
                            "end_prompt_text": "小满抬头看站牌，表情迟疑。",
                            "end_visible_character_ids": [character_id],
                            "end_character_references": [
                                {"character_id": character_id, "look_id": casual}
                            ],
                            "end_environment_view_id": station,
                            "end_environment_mode": "reference",
                            "end_environment_none_reason": None,
                        },
                        {
                            "segment_id": second_segment,
                            "frame_strategy": "both",
                            "end_prompt_text": "小满转身望向轨道尽头，行李箱留在身侧。",
                            "end_visible_character_ids": [character_id],
                            "end_character_references": [
                                {"character_id": character_id, "look_id": None}
                            ],
                            "end_environment_view_id": None,
                            "end_environment_mode": "none",
                            "end_environment_none_reason": "站台主机位不覆盖轨道尽头方向",
                        },
                    ],
                },
                {
                    "shot_id": narration_shot["id"],
                    "continues_from_previous_shot": False,
                    "start_prompt_text": "入夜的空旷站台全景，站灯亮起。",
                    "start_visible_character_ids": [],
                    "start_character_references": [],
                    "start_environment_view_id": night,
                    "start_environment_mode": "edit",
                    "start_environment_none_reason": None,
                    "segments": [
                        {
                            "segment_id": narration_segment,
                            "frame_strategy": "start",
                            "end_prompt_text": "入夜站台的静止尾帧。",
                            "end_visible_character_ids": [],
                            "end_character_references": [],
                            "end_environment_view_id": None,
                            "end_environment_mode": "none",
                            "end_environment_none_reason": "尾帧未启用，不提交地点视图",
                        }
                    ],
                },
            ]
        }
    )
    keyframe_upload = journey.upload_image("upload:行李箱细节.png", "keyframe")
    journey._put(
        "keyframe_references",
        f"{journey.resource}/segments/{first_segment}/keyframe-references",
        {"expected_revision": journey._revision(), "asset_ids": [keyframe_upload]},
    )
    journey.generate_keyframe_candidates()
    journey.select_keyframe_candidates()
    snap = journey.snapshot()
    modes = {item["segment_id"]: video_wire_mode(item) for item in snap["video_plan"]["segments"]}
    assert modes == {first_segment: "ref2va", second_segment: "fl2va", narration_segment: "fl2va"}

    journey.step("video.ref2va")
    reference_image = journey.upload_image("upload:站牌字样.png", "keyframe")
    reference_audio = journey.upload_media(
        "upload:小满对白.wav", wav_bytes("upload:小满对白.wav", 1.5), "audio/wav"
    )
    reference_ambience = journey.upload_media(
        "upload:站台环境声.wav", wav_bytes("upload:站台环境声.wav", 3.0), "audio/wav"
    )
    reference_video = journey.upload_media(
        "upload:推镜参考.mp4", mp4_bytes("upload:推镜参考.mp4", 3.0), "video/mp4"
    )
    # 外部 Agent 经 video.update_recipe_inputs 保存正文、参考素材与参数；
    # Provider 请求与人工保存逐字节一致。
    journey._command(
        "video.update_recipe_inputs",
        {
            "scope": {"scene_ids": [drama["id"]]},
            "segment_id": first_segment,
            "prompt_text": (
                "<Picture 1> 小满抬头看 <Picture 3> 站牌，用 <Audio 1> 的声音说“还会来吗？”"
            ),
            "bindings": {
                "additional_images": [
                    {"asset_id": reference_image, "description": "站牌上的站名字样"}
                ],
                "reference_audios": [
                    {"asset_id": reference_audio, "description": "小满的对白，原样使用"},
                    {"asset_id": reference_ambience, "description": "站台环境底噪"},
                ],
                "reference_videos": [
                    {"asset_id": reference_video, "description": "缓慢推近的运镜参考"}
                ],
            },
            "params": {},
        },
        role="agent",
        step="video_plan",
    )
    journey._post(
        "video_generate",
        f"{journey.resource}/segments/{first_segment}/videos/generate",
        {"expected_revision": journey._revision(), "seed": "1001"},
    )

    journey.step("video.fl2va")
    # 旁白 Segment 不传 seed，录制 Core 的默认 seed 派生。
    for segment_id, seed, prompt in (
        (second_segment, "1002", "小满松开拉杆，转身望向轨道尽头。"),
        (narration_segment, None, "固定机位观察入夜站台，站灯轻微闪烁。"),
    ):
        journey._put(
            "video_plan",
            f"{journey.resource}/segments/{segment_id}/videos/inputs",
            video_wire_dict(
                {
                    "expected_revision": journey._revision(),
                    "prompt_text": prompt,
                    "additional_image_references": [],
                    "audio_references": [],
                    "video_references": [],
                }
            ),
        )
        journey._post(
            "video_generate",
            f"{journey.resource}/segments/{segment_id}/videos/generate",
            {"expected_revision": journey._revision()} | ({} if seed is None else {"seed": seed}),
        )
    for segment_id in (first_segment, second_segment, narration_segment):
        output = journey.latest_output("segment_video", segment_id)
        journey._post(
            "video_select",
            f"{journey.resource}/segments/{segment_id}/videos/select",
            {"expected_revision": journey._revision(), "asset_id": output["output_asset_id"]},
        )
    first_video = journey.latest_output("segment_video", first_segment)["output_asset_id"]

    journey.step("keyframe.extract_frame")
    second_start = next(
        item["start_keyframe_id"]
        for item in journey.snapshot()["keyframe_plan"]["segments"]
        if item["segment_id"] == second_segment
    )
    journey._post(
        "extract_frame",
        f"{journey.resource}/keyframes/{second_start}/extract-frame",
        {
            "expected_revision": journey._revision(),
            "frame_index": 70,
            "source_video_asset_id": first_video,
        },
    )
    journey.latest_output("video_frame", second_start)

    journey.step("asset.video_frame")
    journey._post(
        "asset_video_frame",
        f"{journey.resource}/assets/{first_video}/video-frame",
        {"expected_revision": journey._revision(), "frame_index": 0},
    )

    journey.step("video.upscale")
    journey._post(
        "upscale",
        f"{journey.resource}/segments/{first_segment}/videos/upscale",
        {"expected_revision": journey._revision()},
    )
    journey.latest_output("video_upscale", first_segment)

    journey.step("asset.audio_separation")
    journey._post(
        "audio_separation",
        f"{journey.resource}/assets/{first_video}/audio-separation",
        {"expected_revision": journey._revision()},
    )
    voice_stem = journey.latest_output("video_audio_voice", first_video)["output_asset_id"]
    background_stem = journey.latest_output("video_audio_background", first_video)[
        "output_asset_id"
    ]

    journey.step("asset.audio_remix")
    journey._post(
        "audio_remix",
        f"{journey.resource}/assets/{first_video}/audio-remix",
        {
            "expected_revision": journey._revision(),
            "voice_asset_id": voice_stem,
            "background_asset_id": background_stem,
            "voice_gain_db": 3.0,
            "background_gain_db": -6.0,
            "voice_gain_start_seconds": 1.0,
            "voice_gain_end_seconds": 4.0,
        },
    )
    journey.latest_output("video_audio_remix", first_video)

    journey.step("asset.transcription")
    _ok(
        "transcription",
        server.request(
            "POST",
            f"{journey.resource}/assets/{reference_audio}/transcription",
            {"language": "zh"},
        ),
    )

    journey.step("asset.audio_generation")
    journey._post(
        "audio_generation.design",
        f"{journey.resource}/audio-generations",
        {
            "expected_revision": journey._revision(),
            "operation": "voice_design",
            "text": "列车即将进站，请站在黄线以内。",
            "seed": 21,
            "voice_description": "车站广播女声，略带回声",
        },
    )
    journey._post(
        "audio_generation.synthesize",
        f"{journey.resource}/audio-generations",
        {
            "expected_revision": journey._revision(),
            "operation": "synthesize",
            "text": "末班车已经停运了。",
            "seed": 22,
            "voice_asset_id": reference_audio,
            "reference_transcript": "还会来吗？",
            "recipe_params": {"breeze_tts2.clone": {"performance_instruction": "低声，带一点失望"}},
        },
    )
    journey.wait_generations(kind="generated_audio")

    journey.step("scene.animatic")
    journey._post(
        "animatic",
        f"{journey.resource}/scenes/{drama['id']}/animatic",
        {"expected_revision": journey._revision()},
    )
    journey.latest_output("scene_animatic", drama["id"])

    journey.step("final.assembly")
    journey.assemble_scene_finals()
    journey.assemble_final()

    journey.step("settings.h3_turbo_1080p")
    journey._post(
        "reopen_videos",
        f"{journey.resource}/final/reopen-videos",
        {"expected_revision": journey._revision()},
    )
    server.golden.set_h3("turbo_v2", "1080p", False, False)
    for segment_id, seed in ((first_segment, "2001"), (second_segment, "2002")):
        journey._post(
            "video_generate",
            f"{journey.resource}/segments/{segment_id}/videos/generate",
            {"expected_revision": journey._revision(), "seed": seed},
        )
        journey.wait_generations(kind="segment_video", target_ids={segment_id})

    journey.step("video.retry_after_failure")
    server.golden.plugins["h3_fl2va"].fail_next()
    journey._post(
        "video_generate",
        f"{journey.resource}/segments/{second_segment}/videos/generate",
        {"expected_revision": journey._revision(), "seed": "3001"},
    )
    failed = journey.wait_generations(
        kind="segment_video", target_ids={second_segment}, phases={"succeeded", "failed"}
    )
    failed_id = next(
        item["id"] for item in reversed(failed["generations"]) if item["phase"] == "failed"
    )
    journey._post(
        "video_retry",
        f"{journey.resource}/generations/{failed_id}/retry",
        {"expected_revision": journey._revision()},
    )
    journey.wait_generations(
        kind="segment_video", target_ids={second_segment}, phases={"succeeded", "failed"}
    )

    journey.step("settings.image_provider_agy")
    server.golden.bind_images("agy_image")
    journey._post(
        "keyframe_regenerate",
        f"{journey.resource}/keyframes/{second_start}/generate",
        {"expected_revision": journey._revision()},
    )
    journey.wait_generations(kind="keyframe_image", target_ids={second_start})

    _location_generation_steps(journey, server)

    generations = journey.snapshot()["generations"]
    videos = [item for item in generations if item["kind"] == "segment_video"]
    assert videos[0]["provider"] == {
        "plugin_id": "minimax_h3",
        "recipe_id": "minimax_h3.ref2va",
        "summary": "DaSiWa Hybrid V2 · 20 步 · 720p · Sage · SelfLift",
    }
    assert videos[-1]["provider"]["summary"] == "Turbo V2 · 8 步 · 1080p"
    assert {
        item["provider"]["plugin_id"]
        for item in generations
        if item["kind"] == "keyframe_image" and item["provider"] is not None
    } == {"codex_image", "agy_image"}
    assert all(item["provider"] is None for item in generations if item["kind"] == "final_video")
    assert_golden(
        "project",
        journey.log.entries,
        substitutions={
            _segment_seed(first_segment): "<默认 seed：drama 第 1 个 Segment ID 前 16 位>",
            _segment_seed(narration_segment): "<默认 seed：narration Segment ID 前 16 位>",
        },
    )


def _location_generation_steps(journey: GoldenJourney, server: GoldenHttpServer) -> None:
    """地点主图（室内 2:1 全景、室外项目画幅）→ 选择 → 室内裁切 → 显式细化；室外 edit 转向。"""
    server.golden.bind_images("codex_image")
    journey.step("location.edit")
    journey._post(
        "location_operations",
        f"{journey.resource}/locations/operations",
        {
            "expected_revision": journey._revision(),
            "scope": {"location_ids": [], "scene_ids": [], "shot_ids": []},
            "operations": [
                {
                    "op": "create_location",
                    "key": "hall",
                    "name": "候车大厅",
                    "kind": "interior",
                    "description": "水磨石地面、木长椅、拱形高窗。",
                },
                {
                    "op": "update_location",
                    "location_id": "hall",
                    "fields": {
                        "master_prompt_text": "老式火车站候车大厅，冬夜，暖黄灯光。",
                        "key_light": {"description": "高窗透入的冷月光", "azimuth_deg": 270.0},
                    },
                },
                {
                    "op": "upsert_fixture",
                    "location_id": "hall",
                    "fixture": "board",
                    "name": "时刻表",
                    "description": "翻牌式时刻表",
                    "azimuth_deg": None,
                },
                {
                    "op": "create_view",
                    "location_id": "hall",
                    "key": "bench",
                    "fields": {
                        "name": "长椅正打",
                        "purpose": "人眼高中景，小满坐在长椅上",
                        "azimuth_deg": 45.0,
                        "pitch_deg": -5.0,
                        "hfov_deg": 70.0,
                        "refine_prompt_text": "地面有融雪水渍。",
                    },
                },
                {
                    "op": "create_location",
                    "key": "yard",
                    "name": "站前广场",
                    "kind": "exterior",
                    "description": "积雪广场、路灯、远处钟楼。",
                },
                {
                    "op": "update_location",
                    "location_id": "yard",
                    "fields": {"master_prompt_text": "雪夜站前广场，路灯昏黄。"},
                },
                {
                    "op": "create_view",
                    "location_id": "yard",
                    "key": "tower",
                    "fields": {
                        "name": "望向钟楼",
                        "purpose": "广角远景，交代钟楼方位",
                        "azimuth_deg": 300.0,
                        "hfov_deg": 100.0,
                    },
                },
            ],
        },
    )
    libraries = journey.snapshot()["location_library"]["locations"]
    hall, yard = (
        next(item for item in libraries if item["name"] == name)
        for name in ("候车大厅", "站前广场")
    )
    journey.step("location.master_generate")
    for location in (hall, yard):
        journey._post(
            "location_master",
            f"{journey.resource}/locations/{location['id']}/master/generate",
            {"expected_revision": journey._revision()},
        )
        master = journey.latest_output("location_master_image", location["id"])
        journey._post(
            "location_master_select",
            f"{journey.resource}/locations/{location['id']}/master/select",
            {"expected_revision": journey._revision(), "asset_id": master["output_asset_id"]},
        )
    bench, tower = hall["views"][0]["id"], yard["views"][0]["id"]
    for step, kind in (
        ("location_view_crop", "location_view_crop"),
        ("location_view_refine", "location_view_image"),
    ):
        journey.step(f"location.{step.removeprefix('location_')}")
        journey._post(
            step,
            f"{journey.resource}/location-views/{bench}/generate",
            {"expected_revision": journey._revision()},
        )
        journey.latest_output(kind, bench)
    journey.step("location.view_turn")
    journey._post(
        "location_view_turn",
        f"{journey.resource}/location-views/{tower}/generate",
        {"expected_revision": journey._revision()},
    )
    journey.latest_output("location_view_image", tower)


class PlaygroundDriver:
    """经真实 HTTP 驱动 Playground：上传素材、提交实验并等待结束。"""

    def __init__(self, server: GoldenHttpServer) -> None:
        self._server = server
        self.log = server.golden.log
        self._count = 0

    def upload(self, label: str, content: bytes, media_type: str) -> str:
        self.log.label(content, label)
        body = _ok(
            "playground.upload",
            self._server.upload(
                "/api/playground/assets/media?" + urlencode({"filename": label}),
                content,
                media_type,
            ),
        )
        return body["asset"]["id"]

    def command(self, name: str, arguments: dict) -> dict:
        self._count += 1
        body = _ok(
            name,
            self._server.request(
                "POST",
                "/api/playground/commands",
                {"name": name, "idempotency_key": f"golden:{self._count}", "arguments": arguments},
            ),
        )
        return body["data"]

    def run(self, step: str, capability: str, parameters: dict) -> dict:
        self.log.step = step
        run = self.command(
            "playground.submit_run",
            {"capability": capability, "parameters": parameters, "note": None},
        )["run"]
        return self.wait(run["id"])

    def wait(self, run_id: str) -> dict:
        (run,) = self.command("playground.wait_runs", {"run_ids": [run_id]})["runs"]
        return run


def test_playground_provider_requests(golden_server: GoldenHttpServer) -> None:
    server = golden_server
    playground = PlaygroundDriver(server)
    character = playground.upload(
        "upload:角色参考.png", png_bytes("upload:角色参考.png"), "image/png"
    )
    prop = playground.upload("upload:道具参考.png", png_bytes("upload:道具参考.png"), "image/png")
    voice = playground.upload(
        "upload:参考音色.wav", wav_bytes("upload:参考音色.wav", 2.0), "audio/wav"
    )
    ambience = playground.upload(
        "upload:环境声.wav", wav_bytes("upload:环境声.wav", 3.0), "audio/wav"
    )
    motion = playground.upload(
        "upload:运镜参考.mp4", mp4_bytes("upload:运镜参考.mp4", 2.5), "video/mp4"
    )

    generated = playground.run(
        "image.generate",
        "codex_image.generate",
        {
            "prompt": "雨夜站台上的红色行李箱。",
            "aspect_ratio": "9:16",
            "reference_image_asset_ids": [character, prop],
        },
    )
    server.golden.bind_images("agy_image")
    edited = playground.run(
        "image.edit.agy",
        "agy_image.edit",
        {
            "prompt": "把雨夜改成清晨，保留行李箱位置。",
            "aspect_ratio": "2:1",
            "source_image_asset_id": generated["output_asset_id"],
            "reference_image_asset_ids": [prop],
        },
    )
    server.golden.bind_images("codex_image")
    playground.run(
        "tts.voice_design",
        "breeze_tts2.voice_design",
        {"text": "末班车已经离开。", "voice_description": "低沉的男中音，略带沙哑", "seed": 31},
    )
    playground.run(
        "tts.voice_clone",
        "breeze_tts2.clone",
        {
            "text": "我再等一会儿。",
            "voice_asset_id": voice,
            "reference_transcript": "参考音频的完整文字稿。",
            "performance_instruction": "轻声，犹豫",
            "seed": 32,
        },
    )
    playground.run(
        "tts.voice_clone.no_instruction",
        "breeze_tts2.clone",
        {
            "text": "I will wait a little longer.",
            "voice_asset_id": voice,
            "reference_transcript": "参考音频的完整文字稿。",
            "performance_instruction": None,
            "seed": 33,
        },
    )
    playground.run(
        "asr.transcribe", "whisper_asr.transcribe", {"audio_asset_id": voice, "language": "auto"}
    )

    fl2va = playground.run(
        "video.fl2va",
        "minimax_h3.fl2va",
        {
            "prompt": "行李箱在站台上缓慢滑动。",
            "aspect_ratio": "9:16",
            "duration_seconds": 5.0,
            "seed": 41,
            "first_frame_asset_id": generated["output_asset_id"],
            "last_frame_asset_id": None,
        },
    )
    fl2va_frame = generated["output_asset_id"]
    server.golden.set_h3("hybrid_v2", "480p", True, False)
    playground.run(
        "video.fl2va.480p_last_only",
        "minimax_h3.fl2va",
        {
            "prompt": "镜头停在清晨的站台。",
            "aspect_ratio": "16:9",
            "duration_seconds": 16.5,
            "seed": 42,
            "first_frame_asset_id": None,
            "last_frame_asset_id": edited["output_asset_id"],
        },
    )
    server.golden.set_h3("turbo_v2", "1080p", False, True)
    playground.run(
        "video.ref2va.1080p_turbo",
        "minimax_h3.ref2va",
        {
            "prompt": (
                "<Picture 1> 到 <Picture 2>，<Picture 3> 的道具保持可见，<Audio 1> 作为环境声。"
            ),
            "aspect_ratio": "2:1",
            "duration_seconds": 6.0,
            "seed": 43,
            "first_frame_asset_id": generated["output_asset_id"],
            "last_frame_asset_id": edited["output_asset_id"],
            "additional_images": [{"asset_id": prop, "description": "行李箱道具"}],
            "reference_audios": [
                {"asset_id": ambience, "description": "雨声环境"},
                {"asset_id": voice, "description": "角色音色"},
            ],
            "reference_videos": [{"asset_id": motion, "description": "推镜节奏"}],
        },
    )
    server.golden.set_h3("hybrid_v2", "720p", True, True)
    playground.run(
        "video.ref2va.first_frame_and_audio",
        "minimax_h3.ref2va",
        {
            "prompt": "<Picture 1> 中 <Picture 2> 的人物用 <Audio 1> 的声音独白。",
            "aspect_ratio": "16:9",
            "duration_seconds": 4.0,
            "seed": 44,
            "first_frame_asset_id": fl2va_frame,
            "last_frame_asset_id": None,
            "additional_images": [{"asset_id": character, "description": "人物外观"}],
            "reference_audios": [{"asset_id": voice, "description": "独白原声"}],
            "reference_videos": [],
        },
    )

    playground.run(
        "video.ref2va.no_audio",
        "minimax_h3.ref2va",
        {
            "prompt": "<Picture 1> 结束在 <Picture 2> 的道具特写。",
            "aspect_ratio": "9:16",
            "duration_seconds": 3.0,
            "seed": 45,
            "first_frame_asset_id": None,
            "last_frame_asset_id": generated["output_asset_id"],
            "additional_images": [{"asset_id": prop, "description": "道具特写"}],
            "reference_audios": [],
            "reference_videos": [],
        },
    )
    playground.run(
        "video.ref2va.no_images",
        "minimax_h3.ref2va",
        {
            "prompt": "空旷站台上，一盏顶灯轻微闪烁。",
            "aspect_ratio": "16:9",
            "duration_seconds": 3.0,
            "seed": 46,
            "first_frame_asset_id": None,
            "last_frame_asset_id": None,
            "additional_images": [],
            "reference_audios": [{"asset_id": ambience, "description": "雨声环境"}],
            "reference_videos": [],
        },
    )

    video = fl2va["output_asset_id"]
    playground.run(
        "video.upscale", "seedvr2_7b_sharp_fp8.upscale", {"video_asset_id": video, "seed": 51}
    )
    playground.run(
        "video.extract_frame", "video.extract_frame", {"video_asset_id": video, "frame_index": 119}
    )
    panorama = playground.upload(
        "upload:客厅全景.png", panorama_png_bytes("upload:客厅全景.png"), "image/png"
    )
    pano_view = playground.run(
        "image.pano_view",
        "image.pano_view",
        {
            "image_asset_id": panorama,
            "yaw_deg": 270,
            "pitch_deg": -10.5,
            "hfov_deg": 75,
            "aspect_ratio": "9:16",
        },
    )
    assert pano_view["phase"] == "succeeded"
    voice_stem = playground.run(
        "audio.separate.voice", "demucs_audio.separate", {"video_asset_id": video, "stem": "voice"}
    )
    background_stem = playground.run(
        "audio.separate.background",
        "demucs_audio.separate",
        {"video_asset_id": video, "stem": "background"},
    )
    playground.run(
        "audio.remix",
        "audio.remix",
        {
            "video_asset_id": video,
            "voice_asset_id": voice_stem["output_asset_id"],
            "background_asset_id": background_stem["output_asset_id"],
            "voice_gain_db": -2.5,
            "background_gain_db": 6.0,
            "voice_gain_start_seconds": None,
            "voice_gain_end_seconds": None,
            "background_gain_start_seconds": 0.5,
            "background_gain_end_seconds": 2.5,
        },
    )
    playground.run(
        "audio.generate",
        "stable_audio_3.generate",
        {
            "prompt": "rain on a train platform, distant announcement",
            "duration_seconds": 12.5,
            "seed": 61,
        },
    )

    server.golden.plugins["seedvr2"].fail_next()
    failed = playground.run(
        "run.retry", "seedvr2_7b_sharp_fp8.upscale", {"video_asset_id": video, "seed": 52}
    )
    assert failed["phase"] == "failed"
    retried = playground.command("playground.retry_run", {"run_id": failed["id"]})["run"]
    playground.wait(retried["id"])

    assert_golden("playground", playground.log.entries)
