"""HTTP 边缘路由矩阵与门控直接测试。

P5-A1 为 http_api.handle 的 if/elif 链建立行为网：每个声明的
(method, path) 至少经过 handle 分派；授权由真实 loopback server 覆盖。
测试只 monkeypatch 边界 handler/service，不复制领域状态。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.structured_director import JsonResponse
from core.structured_director.errors import RevisionConflictError
from core.structured_director.http_api import StructuredDirectorHttpApi
from core.structured_director.models import DirectorRunKind, DirectorRunStatus
from core.structured_director.reads.workflow_state import StagePrerequisiteError

PROJECT_ID = "a" * 32
SCENE_ID = "b" * 32
SHOT_ID = "c" * 32
SEGMENT_ID = "d" * 32
KEYFRAME_ID = "e" * 32
CUE_ID = "f" * 32
ASSET_ID = "1" * 32
GENERATION_ID = "2" * 32
CARD_ID = "3" * 32
LOCATION_ID = "4" * 32
VIEW_ID = "5" * 32
RESOURCE_PATH = f"/api/projects/{PROJECT_ID}/structured-director"


@dataclass(frozen=True, slots=True)
class RouteCase:
    method: str
    suffix: str
    handler: str | None = None
    body: bytes = b"{}"

    @property
    def path(self) -> str:
        return f"{RESOURCE_PATH}{self.suffix}"


NAMED_ROUTE_CASES: tuple[RouteCase, ...] = (
    RouteCase("GET", "", "_serialize_snapshot"),
    RouteCase("PUT", "/director-script", "_save_script"),
    RouteCase("POST", "/director-script/confirm", "_confirm_script"),
    RouteCase("POST", "/narration/generate-batch", "_generate_narration_batch"),
    RouteCase("PUT", "/narrator", "_update_narrator"),
    RouteCase("POST", "/narrator/voice-generations", "_design_narrator_voice"),
    RouteCase("POST", "/narrator/voice-reference/upload", "_upload_narrator_voice"),
    RouteCase("POST", "/narrator/voice-reference/attach", "_attach_narrator_voice"),
    RouteCase("POST", "/visual-production/unlock", "_unlock_visual_production"),
    RouteCase("POST", "/keyframes/generate-batch", "_generate_keyframe_batch"),
    RouteCase("POST", "/locations/operations", "_apply_location_operations"),
    RouteCase("POST", f"/locations/{LOCATION_ID}/master/select", "_location_action"),
    RouteCase("POST", f"/locations/{LOCATION_ID}/master/generate", "_location_action"),
    RouteCase("POST", f"/locations/{LOCATION_ID}/calibrate", "_location_action"),
    RouteCase("POST", f"/location-views/{VIEW_ID}/select", "_location_view_action"),
    RouteCase("POST", f"/location-views/{VIEW_ID}/generate", "_location_view_action"),
    RouteCase("POST", "/generations/refresh", "_refresh_active_generations"),
    RouteCase("POST", "/commands", "_execute_command"),
    RouteCase("POST", "/application/commands", "_execute_command"),
    RouteCase("POST", "/final/enter", "_enter_final"),
    RouteCase("POST", "/final/generate", "_generate_final"),
    RouteCase("POST", "/final/select", "_select_final"),
    RouteCase("POST", "/final/clear-selection", "_clear_final_selection"),
    RouteCase("POST", "/final/approve", "_approve_final"),
    RouteCase("POST", "/final/reopen-videos", "_reopen_video_production"),
    RouteCase("POST", "/assets/images", "_import_image_asset"),
    RouteCase("POST", "/assets/media", "_import_media_asset"),
    RouteCase("POST", f"/generations/{GENERATION_ID}/refresh", "_generation_action"),
    RouteCase("POST", f"/generations/{GENERATION_ID}/cancel", "_generation_action"),
    RouteCase("POST", f"/generations/{GENERATION_ID}/retry", "_generation_action"),
    RouteCase("POST", f"/generations/{GENERATION_ID}/dismiss", "_generation_action"),
    RouteCase("POST", f"/generations/{GENERATION_ID}/wait", "_generation_action"),
    RouteCase("POST", f"/scenes/{SCENE_ID}/animatic", "_generate_scene_animatic"),
    RouteCase("POST", f"/scenes/{SCENE_ID}/final", "_generate_scene_final"),
    RouteCase("PUT", f"/keyframes/{KEYFRAME_ID}", "_keyframe_action"),
    RouteCase("POST", f"/keyframes/{KEYFRAME_ID}/preview", "_keyframe_action"),
    RouteCase("POST", f"/keyframes/{KEYFRAME_ID}/generate", "_keyframe_action"),
    RouteCase("POST", f"/keyframes/{KEYFRAME_ID}/select", "_keyframe_action"),
    RouteCase("POST", f"/keyframes/{KEYFRAME_ID}/extract-frame", "_keyframe_action"),
    RouteCase("GET", f"/assets/{ASSET_ID}/video-frame-info", "_video_frame_info"),
    RouteCase(
        "PUT", f"/segments/{SEGMENT_ID}/keyframe-references", "_save_segment_keyframe_references"
    ),
    RouteCase(
        "PUT", f"/segments/{SEGMENT_ID}/keyframe-activation", "_save_segment_keyframe_activation"
    ),
    RouteCase(
        "PUT", f"/segments/{SEGMENT_ID}/keyframe-boundary", "_save_segment_keyframe_boundary"
    ),
    RouteCase("PUT", f"/segments/{SEGMENT_ID}/videos/inputs", "_segment_video_action"),
    RouteCase("PUT", f"/segments/{SEGMENT_ID}/videos/recipe", "_segment_video_action"),
    RouteCase("POST", f"/segments/{SEGMENT_ID}/videos/generate", "_segment_video_action"),
    RouteCase("POST", f"/segments/{SEGMENT_ID}/videos/attach-candidate", "_segment_video_action"),
    RouteCase("POST", f"/segments/{SEGMENT_ID}/videos/select", "_segment_video_action"),
    RouteCase("POST", f"/segments/{SEGMENT_ID}/videos/clear-selection", "_segment_video_action"),
    RouteCase("POST", f"/segments/{SEGMENT_ID}/videos/upscale", "_segment_video_action"),
    RouteCase("POST", "/audio-generations", "_generate_asset_audio"),
    RouteCase("POST", f"/assets/{ASSET_ID}/transcription", "_transcribe_audio"),
    RouteCase("POST", f"/assets/{ASSET_ID}/audio-trim", "_trim_audio"),
    RouteCase("POST", f"/assets/{ASSET_ID}/audio-effect", "_apply_audio_effect"),
    RouteCase("POST", f"/assets/{ASSET_ID}/audio-separation", "_separate_video_audio"),
    RouteCase("POST", f"/assets/{ASSET_ID}/audio-remix", "_remix_video_audio"),
    RouteCase("DELETE", "/assets/batch-delete", "_delete_assets"),
    RouteCase("DELETE", f"/assets/{ASSET_ID}", "_delete_asset"),
    RouteCase("PUT", f"/scenes/{SCENE_ID}/narration-cues/{CUE_ID}", "_narration_cue_action"),
    RouteCase(
        "POST", f"/scenes/{SCENE_ID}/narration-cues/{CUE_ID}/generate", "_narration_cue_action"
    ),
    RouteCase(
        "POST", f"/scenes/{SCENE_ID}/narration-cues/{CUE_ID}/select", "_narration_cue_action"
    ),
    RouteCase(
        "POST",
        f"/scenes/{SCENE_ID}/narration-cues/{CUE_ID}/clear-selection",
        "_narration_cue_action",
    ),
    RouteCase("POST", "/characters", "_card_action"),
    RouteCase("PUT", f"/characters/{CARD_ID}", "_card_action"),
    RouteCase("DELETE", f"/characters/{CARD_ID}", "_card_action"),
    RouteCase("POST", f"/characters/{CARD_ID}/looks/{CARD_ID}/select-asset", "_card_action"),
    RouteCase("POST", f"/characters/{CARD_ID}/looks/{CARD_ID}/select-sheet", "_card_action"),
    RouteCase("POST", f"/characters/{CARD_ID}/looks/{CARD_ID}/sheet-generations", "_card_action"),
    RouteCase("POST", f"/characters/{CARD_ID}/voice-generations", "_card_action"),
    RouteCase("POST", f"/characters/{CARD_ID}/voice-reference/upload", "_card_action"),
    RouteCase("POST", f"/characters/{CARD_ID}/voice-reference/attach", "_card_action"),
)

INLINE_ROUTE_CASES: tuple[tuple[RouteCase, str], ...] = (
    (
        RouteCase(
            "POST",
            f"/assets/{ASSET_ID}/video-frame",
            body=b'{"expected_revision":1,"frame_index":0}',
        ),
        "_media.extract_asset_video_frame",
    ),
)

ALL_ROUTE_CASES = tuple(
    [case for case in NAMED_ROUTE_CASES] + [case for case, _ in INLINE_ROUTE_CASES]
)


class _RouteTestHttpApi(StructuredDirectorHttpApi):
    """以空 snapshot 序列化替换响应组装，聚焦路由分派。"""

    def _serialize_snapshot(self, document: object) -> dict[str, object]:
        del document
        return {"serialized": True}


def _build_api(snapshot: object | None = None) -> _RouteTestHttpApi:
    if snapshot is None:
        snapshot = SimpleNamespace(active_director_run=None)
    service = SimpleNamespace(
        snapshot=lambda: snapshot,
        _media=SimpleNamespace(extract_asset_video_frame=AsyncMock()),
    )
    return _RouteTestHttpApi(service, resource_path=RESOURCE_PATH)


def test_named_route_matrix_reaches_declared_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _build_api()
    for case in NAMED_ROUTE_CASES:
        assert case.handler is not None
        recorder = (
            Mock(return_value={"serialized": True})
            if case.handler == "_serialize_snapshot"
            else AsyncMock(return_value=JsonResponse(200, {"ok": True}))
        )
        monkeypatch.setattr(api, case.handler, recorder)
        response = asyncio.run(api.handle(case.method, case.path, case.body))
        assert response.status in {200, 201, 202}, (case, response)
        if case.handler == "_serialize_snapshot":
            assert recorder.call_count == 1, case
        else:
            assert recorder.await_count == 1, case


def test_inline_route_matrix_reaches_service(monkeypatch: pytest.MonkeyPatch) -> None:
    for case, service_target in INLINE_ROUTE_CASES:
        api = _build_api()
        owner: object = api._service
        *parts, attr = service_target.split(".")
        for part in parts:
            owner = getattr(owner, part)
        recorder = AsyncMock(return_value=object())
        monkeypatch.setattr(owner, attr, recorder)
        response = asyncio.run(api.handle(case.method, case.path, case.body))
        assert response.status in {200, 201}, (case, response)
        assert recorder.await_count == 1, (case, service_target)


def test_every_declared_route_requires_authorization(http_server) -> None:
    for case in ALL_ROUTE_CASES:
        body = None if case.method == "GET" else {}
        status, _ = http_server.request(case.method, case.path, body=body, role=None)
        assert status in {401, 404}, (case, status)


def _active_snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        application_requests=(),
        active_director_run=SimpleNamespace(
            id="f" * 32,
            kind=DirectorRunKind.DIRECTOR,
            status=DirectorRunStatus.RUNNING,
        ),
    )


@pytest.mark.parametrize(
    "case",
    [
        RouteCase("POST", "/final/generate"),
        RouteCase("PUT", "/narrator"),
        RouteCase("POST", "/keyframes/generate-batch"),
    ],
)
def test_agent_period_blocks_unrelated_writes(case: RouteCase) -> None:
    api = _build_api(snapshot=_active_snapshot())
    response = asyncio.run(api.handle(case.method, case.path, b"{}"))
    assert response.status == 409
    assert response.body["error"]["code"] == "action_not_allowed"
    # 锁的来源随错误返回，调用方不必另行排查。
    assert response.body["error"]["active_task"] == {"run_id": "f" * 32}


def test_revision_conflict_is_translated_with_full_error_contract() -> None:
    api = _build_api()
    api._service.enter_final_stage = AsyncMock(
        side_effect=RevisionConflictError(
            "revision 已变化。",
            expected_revision=1,
            current_revision=2,
        )
    )
    response = asyncio.run(
        api.handle("POST", f"{RESOURCE_PATH}/final/enter", b'{"expected_revision":1}')
    )
    assert response.status == 409
    error = response.body["error"]
    assert set(error) == {
        "code",
        "message",
        "recoverable",
        "origin",
        "state_changed",
        "retry_policy",
        "automatic_retry_allowed",
    }
    assert error["code"] == "revision_conflict"


def test_second_revision_conflict_route_translates_to_same_contract() -> None:
    api = _build_api()
    api._service.execute_director_command = AsyncMock(
        side_effect=RevisionConflictError("revision 已变化。")
    )
    response = asyncio.run(
        api.handle("POST", f"{RESOURCE_PATH}/final/generate", b'{"expected_revision":1}')
    )
    assert response.status == 409
    assert response.body["error"]["code"] == "revision_conflict"


def test_stage_prerequisite_error_uses_complete_workflow_envelope() -> None:
    exc = StagePrerequisiteError.__new__(StagePrerequisiteError)
    exc.reason = "reference_library_not_ready"
    exc.workflow = {"stage": "reference_library"}
    api = _build_api()
    api._service.enter_final_stage = AsyncMock(side_effect=exc)
    response = asyncio.run(
        api.handle("POST", f"{RESOURCE_PATH}/final/enter", b'{"expected_revision":1}')
    )
    assert response.status == 409
    error = response.body["error"]
    assert error["code"] == "stage_prerequisite_not_met"
    assert error["reason"] == "reference_library_not_ready"
    assert error["stage"] == "reference_library"
    assert set(error) >= {
        "code",
        "message",
        "recoverable",
        "origin",
        "state_changed",
        "retry_policy",
        "automatic_retry_allowed",
    }


def test_runtime_error_route_translates_to_provider_unavailable() -> None:
    api = _build_api()
    api._service.execute_director_command = AsyncMock(side_effect=RuntimeError("provider down"))
    response = asyncio.run(
        api.handle("POST", f"{RESOURCE_PATH}/final/generate", b'{"expected_revision":1}')
    )
    assert response.status == 409
    assert response.body["error"]["code"] == "provider_unavailable"


def test_value_error_route_translates_to_invalid_request() -> None:
    api = _build_api()
    api._service.enter_final_stage = AsyncMock(side_effect=ValueError("bad state"))
    response = asyncio.run(
        api.handle("POST", f"{RESOURCE_PATH}/final/enter", b'{"expected_revision":1}')
    )
    assert response.status == 400
    assert response.body["error"]["code"] == "invalid_request"


# _card_action 是 handle 中的一个二级分派器；对它的子路由做行为锁定，
# 保证 P5-A2 数据化后仍能到达同一能力。
CARD_SUBROUTES: tuple[tuple[RouteCase, str], ...] = (
    (
        RouteCase(
            "POST",
            "/characters",
            body=b'{"expected_revision":1,"name":"n","visual_description":null,"voice_description":"v"}',
        ),
        "_add_card",
    ),
    (RouteCase("PUT", f"/characters/{CARD_ID}", body=b'{"expected_revision":1}'), "_update_card"),
    (
        RouteCase("DELETE", f"/characters/{CARD_ID}", body=b'{"expected_revision":1}'),
        "_discard_card",
    ),
    (
        RouteCase("POST", f"/characters/{CARD_ID}/looks/{CARD_ID}/select-asset", body=b"{}"),
        "_look_action",
    ),
    (RouteCase("POST", f"/characters/{CARD_ID}/voice-generations", body=b"{}"), "_design_voice"),
    (
        RouteCase("POST", f"/characters/{CARD_ID}/voice-reference/upload", body=b"{}"),
        "_upload_voice",
    ),
    (
        RouteCase("POST", f"/characters/{CARD_ID}/voice-reference/attach", body=b"{}"),
        "_attach_output",
    ),
)


def test_card_action_subroutes_reach_domain_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _build_api()
    for case, handler in CARD_SUBROUTES:
        recorder = AsyncMock(return_value=JsonResponse(200, {"ok": True}))
        monkeypatch.setattr(api, handler, recorder)
        suffix = case.suffix
        method = case.method
        if method == "POST" and suffix == "/characters":
            card_id = None
            action = ""
            kind = "characters"
        else:
            parts = suffix.split("/")
            kind = parts[1]
            card_id = parts[2]
            action = "/" + "/".join(parts[3:]) if len(parts) > 3 else ""
        response = asyncio.run(
            api._card_action(
                method,
                kind,
                card_id,
                action,
                case.body,
                media_type="application/json",
                query="",
            )
        )
        assert response.status == 200, (case, handler)
        assert recorder.await_count == 1, (case, handler)
