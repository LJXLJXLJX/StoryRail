from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from core.application.caller import READ_OPERATIONS, AccessDenied
from core.audio_effects import AudioEffectRequest, AudioTrimRequest
from core.director_commands import (
    CommandNeedsUserInput,
    DirectorCommand,
    parse_director_command,
)
from core.director_commands.narration_commands import parse_narration_language
from core.director_proposals import (
    CharacterCardProposal,
    StructuredDirectorScriptRevisionProposal,
)
from core.director_proposals.wire_fields import NARRATION_CUE_EDIT_FIELDS
from core.model_providers.recipe import RecipeInputs, RecipeParams
from storyrail_contracts.http_edge import query_is_allowed as _query_is_allowed

from .errors import InvalidArgumentsError
from .http_requests import (
    JsonResponse as JsonResponse,
)
from .http_requests import (
    _boolean as _boolean,
)
from .http_requests import (
    _error as _error,
)
from .http_requests import (
    _id as _id,
)
from .http_requests import (
    _id_list as _id_list,
)
from .http_requests import (
    _integer as _integer,
)
from .http_requests import (
    _is_active_run_command as _is_active_run_command,
)
from .http_requests import (
    _number as _number,
)
from .http_requests import (
    _optional_id as _optional_id,
)
from .http_requests import (
    _optional_text as _optional_text,
)
from .http_requests import (
    _parse_character_looks as _parse_character_looks,
)
from .http_requests import (
    _parse_keyframe_character_references as _parse_keyframe_character_references,
)
from .http_requests import (
    _parse_narration_track as _parse_narration_track,
)
from .http_requests import (
    _parse_query as _parse_query,
)
from .http_requests import (
    _parse_request as _parse_request,
)
from .http_requests import (
    _parse_revision as _parse_revision,
)
from .http_requests import (
    _parse_scenes as _parse_scenes,
)
from .http_requests import (
    _plain_string as _plain_string,
)
from .http_requests import (
    _query_filename as _query_filename,
)
from .http_requests import (
    _query_revision as _query_revision,
)
from .http_requests import (
    _required_media_type as _required_media_type,
)
from .http_requests import (
    _required_revision as _required_revision,
)
from .http_requests import (
    _revision_error as _revision_error,
)
from .http_requests import (
    _string as _string,
)
from .manual_commands import (
    location_calibration_command,
    location_operations_command,
    location_selection_command,
)
from .models import (
    CharacterCard,
    DirectorRunKind,
    DirectorRunStatus,
    GenerationOperation,
    ImageAssetCategory,
    Keyframe,
    KeyframeEnvironmentMode,
    NarrationCue,
    NarrationLanguage,
    NarrationTrack,
    NarratorProfile,
    NarratorVoice,
    StructuredDirectorDocument,
    normalize_environment_none_reason,
)
from .reads.proposal_observation import proposal_observation
from .reads.read_tools import ReadResultTooLarge
from .reads.snapshot_view import (
    serialize_snapshot,
)
from .reads.workflow_state import StagePrerequisiteError, workflow_state
from .service import (
    StructuredDirectorService,
)
from .store import RevisionConflictError, StructuredDirectorStore

_CARD_RESOURCE = re.compile(r"/(?P<kind>characters)(?:/(?P<card_id>[0-9a-f]{32}))?(?P<action>/.*)?")
_GENERATION_RESOURCE = re.compile(
    r"/generations/(?P<generation_id>[0-9a-f]{32})/"
    r"(?P<action>refresh|cancel|retry|dismiss|wait)"
)
_SCENE_ANIMATIC_RESOURCE = re.compile(r"/scenes/(?P<scene_id>[0-9a-f]{32})/animatic")
_SCENE_FINAL_RESOURCE = re.compile(r"/scenes/(?P<scene_id>[0-9a-f]{32})/final")
_KEYFRAME_RESOURCE = re.compile(
    r"/keyframes/(?P<keyframe_id>[0-9a-f]{32})"
    r"(?P<action>/generate|/select|/preview|/extract-frame)?"
)
_SEGMENT_KEYFRAME_REFERENCE_RESOURCE = re.compile(
    r"/segments/(?P<segment_id>[0-9a-f]{32})/keyframe-references"
)
_SEGMENT_KEYFRAME_ACTIVATION_RESOURCE = re.compile(
    r"/segments/(?P<segment_id>[0-9a-f]{32})/keyframe-activation"
)
_SEGMENT_KEYFRAME_BOUNDARY_RESOURCE = re.compile(
    r"/segments/(?P<segment_id>[0-9a-f]{32})/keyframe-boundary"
)
_SEGMENT_VIDEO_RESOURCE = re.compile(
    r"/segments/(?P<segment_id>[0-9a-f]{32})/videos"
    r"(?P<action>/inputs-preview|/inputs|/recipe|/generate|/attach-candidate|/select|/clear-selection|/upscale)?"
)
_LOCATION_RESOURCE = re.compile(
    r"/locations/(?P<location_id>[0-9a-f]{32})/(?P<action>master/select|master/generate|calibrate)"
)
_LOCATION_VIEW_RESOURCE = re.compile(
    r"/location-views/(?P<view_id>[0-9a-f]{32})/(?P<action>select|generate)"
)
_AUDIO_GENERATIONS_RESOURCE = "/audio-generations"
_ASSET_RESOURCE = re.compile(r"/assets/(?P<asset_id>[0-9a-f]{32})")
_ASSET_BATCH_DELETE_RESOURCE = "/assets/batch-delete"
_ASSET_AUDIO_TRIM_RESOURCE = re.compile(r"/assets/(?P<asset_id>[0-9a-f]{32})/audio-trim")
_ASSET_TRANSCRIPTION_RESOURCE = re.compile(r"/assets/(?P<asset_id>[0-9a-f]{32})/transcription")
_ASSET_AUDIO_EFFECT_RESOURCE = re.compile(r"/assets/(?P<asset_id>[0-9a-f]{32})/audio-effect")
_ASSET_AUDIO_SEPARATION_RESOURCE = re.compile(
    r"/assets/(?P<asset_id>[0-9a-f]{32})/audio-separation"
)
_ASSET_AUDIO_REMIX_RESOURCE = re.compile(r"/assets/(?P<asset_id>[0-9a-f]{32})/audio-remix")
_ASSET_VIDEO_FRAME_RESOURCE = re.compile(r"/assets/(?P<asset_id>[0-9a-f]{32})/video-frame")
_ASSET_VIDEO_FRAME_INFO_RESOURCE = re.compile(
    r"/assets/(?P<asset_id>[0-9a-f]{32})/video-frame-info"
)
_NARRATION_CUE_RESOURCE = re.compile(
    r"/scenes/(?P<scene_id>[0-9a-f]{32})/narration-cues/"
    r"(?P<cue_id>[0-9a-f]{32})(?P<action>/generate|/select|/clear-selection)?"
)
_LOOK_ACTION = re.compile(
    r"/looks/(?P<look_id>[0-9a-f]{32})/(?P<verb>sheet-generations|sheet-preview|select-sheet|select-asset)"
)
_CHARACTER_UPDATE_FIELDS = {
    "expected_revision",
    "name",
    "visual_description",
    "voice_description",
    "voice_reference_asset_id",
    "voice_reference_transcript",
    "looks",
}
_NARRATION_CUE_UPDATE_FIELDS = NARRATION_CUE_EDIT_FIELDS


def _narration_track(value: object, label: str) -> NarrationTrack | None:
    track = _parse_narration_track(value, label)
    if track is None:
        return None
    return NarrationTrack(track.text, track.seed, None, RecipeParams.from_json(track.recipe_params))


class StructuredDirectorHttpApi:
    def __init__(
        self,
        service: StructuredDirectorService,
        *,
        resource_path: str,
        store: StructuredDirectorStore | None = None,
    ) -> None:
        self._service = service
        self.resource_path = resource_path.rstrip("/")
        self._store = store

    async def _execute_button_command(
        self,
        name: str,
        expected_revision: int,
        *,
        target_ids: tuple[str, ...] = (),
        user_instruction: str = "",
        options: dict[str, object] | None = None,
    ) -> StructuredDirectorDocument:
        arguments: dict[str, object] = {
            "target_ids": list(target_ids),
            "user_instruction": user_instruction,
        }
        if options:
            arguments["options"] = options
        return await self._service.execute_production_command(
            DirectorCommand(
                name=name,
                expected_revision=expected_revision,
                idempotency_key=f"button:{name}:{expected_revision}",
                arguments=arguments,
            ),
            raw_user_request=user_instruction,
        )

    async def handle(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        *,
        media_type: str | None = None,
    ) -> JsonResponse:
        target = urlsplit(path)
        route_path = target.path
        if not _query_is_allowed(route_path, target.query):
            return _error(400, "invalid_request", "该请求不接受查询字段。")
        suffix = self._route_suffix(route_path)
        route, match = _match_route(method, suffix)
        if method != "GET":
            snapshot = self._service.snapshot()
            active_run = None if snapshot is None else snapshot.active_director_run
            if (
                active_run is not None
                and not _director_run_yielded(active_run)
                and not self._write_gate_allows(route, method, route_path, body, active_run)
            ):
                # 带出锁的来源与可用动作，调用方不必再排查是哪个请求占用了写入。
                active_task = proposal_observation(snapshot, active_run) or {
                    "run_id": active_run.id
                }
                return _error(
                    409,
                    "action_not_allowed",
                    "Agent 工作期间，结构化导演台的其它写入入口已锁定；"
                    "先提交或取消 active_task 中的请求。",
                    recoverable=True,
                    details={"active_task": active_task},
                    origin="core_domain",
                    retry_policy="change_business_state_or_request",
                )
        if route is None:
            return _error(404, "not_found", "请求的资源不存在。")
        try:
            return await route.invoke(self, method, match, body, media_type, target.query)
        except StagePrerequisiteError as exc:
            return _stage_error(exc)
        except RevisionConflictError as exc:
            return self._translate_revision_error(route, exc)
        except RuntimeError as exc:
            return _error(
                409,
                route.error_policy.runtime_code,
                str(exc),
                recoverable=route.error_policy.runtime_recoverable,
            )
        except ValueError as exc:
            return _error(
                route.error_policy.value_status,
                route.error_policy.value_code,
                str(exc),
            )

    def _route_suffix(self, path: str) -> str:
        if path == self.resource_path:
            return ""
        prefix = f"{self.resource_path}/"
        if path.startswith(prefix):
            return path[len(self.resource_path) :]
        return "\x00"

    def _translate_revision_error(self, route: _Route, exc: RevisionConflictError) -> JsonResponse:
        if route.error_policy.revision_details:
            current = self._current_revision()
            return _revision_error(
                exc,
                expected_revision=exc.expected_revision,
                current_revision=current,
            )
        return _error(
            409,
            "revision_conflict",
            str(exc),
            recoverable=True,
        )

    def _current_revision(self) -> int | None:
        if self._store is not None:
            return self._store.read().revision
        snapshot = self._service.snapshot()
        return None if snapshot is None else snapshot.revision

    def _require_current_revision(self) -> int:
        current = self._current_revision()
        if current is None:
            raise FileNotFoundError("项目权威状态不存在。")
        return current

    def _write_gate_allows(
        self,
        route: _Route | None,
        method: str,
        path: str,
        body: bytes,
        active_run: object,
    ) -> bool:
        if route is None:
            return False
        if route.gate == "none":
            return True
        if route.gate == "active_command":
            return method == "POST" and _is_active_run_command(body)
        if route.gate == "provider_observation":
            if method == "POST" and path == f"{self.resource_path}/generations/refresh":
                return True
            match = _GENERATION_RESOURCE.fullmatch(path[len(self.resource_path) :])
            return match is not None and match.group("action") in {"cancel", "refresh"}
        if route.gate == "session":
            return True
        if route.gate == "recovery":
            return path == _recovery_path(self.resource_path, active_run)
        return False

    async def _card_action(
        self,
        method: str,
        kind: str,
        card_id: str | None,
        action: str,
        body: bytes,
        *,
        media_type: str | None,
        query: str,
    ) -> JsonResponse:
        if method == "POST" and card_id is None and not action:
            return await self._add_card(kind, body)
        if card_id is None:
            return _error(404, "not_found", "请求的资源不存在。")
        if method == "PUT" and not action:
            return await self._update_card(kind, card_id, body)
        if method == "DELETE" and not action:
            return await self._discard_card(kind, card_id, body)
        look = _LOOK_ACTION.fullmatch(action or "")
        if method == "POST" and look is not None:
            return await self._look_action(card_id, look.group("look_id"), look.group("verb"), body)
        if method == "POST" and kind == "characters" and action == "/voice-generations":
            return await self._design_voice(card_id, body)
        if method == "POST" and kind == "characters" and action == "/voice-reference/upload":
            return await self._upload_voice(
                card_id,
                body,
                media_type=media_type,
                query=query,
            )
        if method == "POST" and kind == "characters" and action == "/voice-reference/attach":
            return await self._attach_output("voice", card_id, body)
        return _error(404, "not_found", "请求的资源不存在。")

    async def _save_script(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision", "scenes"})
        if isinstance(request, JsonResponse):
            return request
        revision = _parse_revision(request)
        if isinstance(revision, JsonResponse):
            return revision
        proposal = StructuredDirectorScriptRevisionProposal(
            reply_markdown="已保存人工修改。",
            scenes=_parse_scenes(request["scenes"]),
        )
        _reject_location_binding_changes(self._service.snapshot_required(), request["scenes"])
        result = await self._service.save_script(proposal, expected_revision=revision)
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _confirm_script(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision"})
        if isinstance(request, JsonResponse):
            return request
        revision = _parse_revision(request)
        if isinstance(revision, JsonResponse):
            return revision
        try:
            result = await self._execute_button_command("script.confirm", revision)
        except StagePrerequisiteError as exc:
            return _stage_error(exc)
        except RevisionConflictError as exc:
            return _error(409, "revision_conflict", str(exc), recoverable=True)
        except ValueError as exc:
            return _error(409, "action_not_allowed", str(exc))
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _narration_cue_action(
        self, method: str, scene_id: str, cue_id: str, action: str, body: bytes
    ) -> JsonResponse:
        if method == "PUT" and not action:
            request = _parse_request(
                body,
                required={"expected_revision", *_NARRATION_CUE_UPDATE_FIELDS},
            )
            if isinstance(request, JsonResponse):
                return request
            try:
                cue = NarrationCue(
                    id=cue_id,
                    zh=_narration_track(request["zh"], "zh"),
                    en=_narration_track(request["en"], "en"),
                )
            except ValueError as exc:
                return _error(400, "invalid_request", str(exc))
            result = await self._service.save_narration_cue(
                scene_id=scene_id,
                cue=cue,
                expected_revision=_required_revision(request),
            )
            return JsonResponse(200, self._serialize_snapshot(result))
        request = _parse_request(
            body,
            required={"expected_revision", "generation_id"}
            if action == "/select"
            else {"expected_revision", "language"}
            if action in {"/generate", "/clear-selection"}
            else {"expected_revision"},
        )
        if isinstance(request, JsonResponse):
            return request
        try:
            if method == "POST" and action == "/generate":
                result = await self._execute_button_command(
                    "narration.generate",
                    _required_revision(request),
                    target_ids=(cue_id,),
                    options={"language": parse_narration_language(request["language"])},
                )
                return JsonResponse(202, self._serialize_snapshot(result))
            if method == "POST" and action == "/select":
                result = await self._execute_button_command(
                    "narration.select_candidate",
                    _required_revision(request),
                    target_ids=(
                        cue_id,
                        _id(request["generation_id"], "generation_id"),
                    ),
                )
                return JsonResponse(200, self._serialize_snapshot(result))
            if method == "POST" and action == "/clear-selection":
                revision = _required_revision(request)
                result = (
                    await self._service.execute_director_command(
                        DirectorCommand(
                            "narration.clear_selection",
                            revision,
                            f"button:narration.clear_selection:{cue_id}:{revision}",
                            {
                                "scope": {"scene_ids": [scene_id]},
                                "cue_id": cue_id,
                                "language": request["language"],
                            },
                        )
                    )
                ).document
                return JsonResponse(200, self._serialize_snapshot(result))
        except StagePrerequisiteError as exc:
            return _stage_error(exc)
        except RevisionConflictError as exc:
            return _error(409, "revision_conflict", str(exc), recoverable=True)
        except (RuntimeError, ValueError) as exc:
            return _error(409, "action_not_allowed", str(exc))
        return _error(404, "not_found", "请求的旁白动作不存在。")

    async def _generate_narration_batch(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision"})
        if isinstance(request, JsonResponse):
            return request
        try:
            result = await self._execute_button_command(
                "narration.generate", _required_revision(request)
            )
        except (RuntimeError, ValueError) as exc:
            return _error(409, "action_not_allowed", str(exc))
        return JsonResponse(202, self._serialize_snapshot(result))

    async def _extract_asset_video_frame(self, asset_id: str, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision", "frame_index"})
        if isinstance(request, JsonResponse):
            return request
        result = await self._service._media.extract_asset_video_frame(
            asset_id=asset_id,
            frame_index=_frame_index(request),
            expected_revision=_required_revision(request),
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _video_frame_info(self, asset_id: str, body: bytes) -> JsonResponse:
        del body
        frames = self._service.video_frame_info(asset_id)
        return JsonResponse(
            200,
            {
                "asset_id": asset_id,
                "frame_count": frames.frame_count,
                "duration_seconds": frames.duration_seconds,
            },
        )

    async def _unlock_visual_production(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision"})
        if isinstance(request, JsonResponse):
            return request
        result = await self._execute_button_command(
            "visual_production.unlock", _required_revision(request)
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _generate_keyframe_batch(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision"})
        if isinstance(request, JsonResponse):
            return request
        result = await self._execute_button_command(
            "keyframe.generate", _required_revision(request)
        )
        return JsonResponse(202, self._serialize_snapshot(result))

    async def _execute_command(self, body: bytes, *, include_snapshot: bool) -> JsonResponse:
        request = _parse_request(
            body,
            required={"name", "idempotency_key", "arguments"},
            optional={"expected_revision"},
        )
        if isinstance(request, JsonResponse):
            return request
        if "expected_revision" not in request:
            # generation.wait 只观察 Provider 状态，与读命令一样可省略 revision。
            if request.get("name") not in READ_OPERATIONS | {"generation.wait"}:
                return _error(400, "invalid_request", "写命令必须提供 expected_revision。")
            request["expected_revision"] = self._require_current_revision()
        command = parse_director_command(request)
        try:
            execution = await self._service.execute_director_command(command)
        except AccessDenied as exc:
            return _error(
                exc.status,
                exc.code,
                str(exc),
                origin="authorization",
                retry_policy="obtain_authorization_or_user_action",
            )
        except StagePrerequisiteError as exc:
            return _stage_error(exc)
        except RevisionConflictError as exc:
            return _revision_error(
                exc,
                expected_revision=command.expected_revision,
                current_revision=self._current_revision(),
            )
        except CommandNeedsUserInput as exc:
            return JsonResponse(
                409,
                {
                    "error": {
                        "code": "user_choice_required",
                        "message": str(exc),
                        "recoverable": True,
                        "impact": exc.impact,
                    }
                },
            )
        except ReadResultTooLarge as exc:
            return _error(
                413,
                "result_too_large",
                str(exc),
                recoverable=True,
                details={
                    "retry": "缩小 scope/limit/layers，或使用返回的 cursor 续读。",
                },
            )
        except InvalidArgumentsError as exc:
            return _error(400, "invalid_request", str(exc))
        except RuntimeError as exc:
            current_revision = self._require_current_revision()
            changed = current_revision != command.expected_revision
            return _error(
                409,
                "provider_unavailable",
                str(exc),
                recoverable=True,
                details={"current_revision": current_revision},
                origin="provider_boundary",
                state_changed=changed,
                retry_policy=(
                    "inspect_generation_before_retry"
                    if changed
                    else "restore_dependency_then_replay_same_request"
                ),
            )
        except ValueError as exc:
            if command.name in READ_OPERATIONS:
                return _error(400, "invalid_request", str(exc))
            return _error(
                409,
                "business_rule_rejected",
                str(exc),
                origin="core_domain",
                retry_policy="change_business_state_or_request",
            )
        receipt = execution.receipt
        payload = {
            "workflow": workflow_state(execution.document),
            "receipt": {
                "command_id": receipt.command_id,
                "status": receipt.status,
                "old_revision": receipt.old_revision,
                "new_revision": receipt.new_revision,
                "changed_ids": list(receipt.changed_ids),
                "invalidated": list(receipt.invalidated),
                "preserved": list(receipt.preserved),
                "decision_summary": receipt.decision_summary,
                "applied_summary": receipt.applied_summary,
                "assumptions": list(receipt.assumptions),
                "next_allowed_actions": [],  # 主流程建议只在顶层 workflow 返回，回执保持可重放。
                "warnings": list(receipt.warnings),
            },
        }
        if execution.application_request_id is not None:
            payload["application_request_id"] = execution.application_request_id
            payload["replay"] = execution.replay
        if execution.data is None and include_snapshot:
            payload["snapshot"] = self._serialize_snapshot(execution.document)
        elif execution.data is not None:
            payload["data"] = execution.data
        else:
            payload["data"] = {
                "command_name": request["name"],
                "revision": execution.document.revision,
                "changed_ids": list(receipt.changed_ids),
            }
        if execution.repair_receipt is not None:
            repair = execution.repair_receipt
            payload["repair_receipt"] = {
                "gap_id": repair.gap_id,
                "missing_command": repair.missing_command,
                "normalized_operations": [
                    {
                        "entity_type": item.entity_type,
                        "entity_id": item.entity_id,
                        "fields": item.fields,
                    }
                    for item in repair.normalized_operations
                ],
                "reverse_operations": [
                    {
                        "entity_type": item.entity_type,
                        "entity_id": item.entity_id,
                        "fields": item.fields,
                    }
                    for item in repair.reverse_operations
                ],
            }
        return JsonResponse(200, payload)

    async def _keyframe_action(
        self, method: str, keyframe_id: str, action: str, body: bytes
    ) -> JsonResponse:
        required = {"expected_revision"}
        if action == "/select":
            required.add("asset_id")
        elif action == "/extract-frame":
            required.update({"frame_index", "source_video_asset_id"})
        elif method == "POST" and action in {"/preview"} or method == "PUT" and not action:
            required.update(
                {
                    "segment_id",
                    "prompt_text",
                    "visible_character_ids",
                    "character_references",
                    "reference_asset_ids",
                    "environment_mode",
                    "environment_view_id",
                    "environment_none_reason",
                }
            )
        request = _parse_request(body, required=required)
        if isinstance(request, JsonResponse):
            return request
        if method == "PUT" and not action:
            snapshot = self._service.snapshot()
            if snapshot is None or snapshot.keyframe_plan is None:
                raise ValueError("关键帧计划尚未建立。")
            current = next(
                (item for item in snapshot.keyframe_plan.keyframes if item.id == keyframe_id),
                None,
            )
            if current is None:
                raise ValueError("Keyframe 不存在。")
            visible_character_ids = request["visible_character_ids"]
            if not isinstance(visible_character_ids, list):
                raise ValueError("visible_character_ids 必须是数组。")
            result = await self._service.save_keyframe(
                Keyframe(
                    id=current.id,
                    owner_segment_id=current.owner_segment_id,
                    predecessor_keyframe_id=current.predecessor_keyframe_id,
                    prompt_text=_plain_string(request["prompt_text"], "prompt_text").strip(),
                    visible_character_ids=tuple(
                        _id(item, "visible_character_ids") for item in visible_character_ids
                    ),
                    character_references=_parse_keyframe_character_references(
                        request["character_references"]
                    ),
                    selected_asset_id=current.selected_asset_id,
                    **_keyframe_environment(request),
                ),
                expected_revision=_required_revision(request),
                segment_id=_id(request["segment_id"], "segment_id"),
                reference_asset_ids=_id_list(request["reference_asset_ids"]),
            )
            return JsonResponse(200, self._serialize_snapshot(result))
        if method == "POST" and action == "/preview":
            result = await self._service.preview_keyframe(
                keyframe_id=keyframe_id,
                segment_id=_id(request["segment_id"], "segment_id"),
                prompt_text=_plain_string(request["prompt_text"], "prompt_text"),
                visible_character_ids=_id_list(request["visible_character_ids"]),
                character_references=_parse_keyframe_character_references(
                    request["character_references"]
                ),
                reference_asset_ids=_id_list(request["reference_asset_ids"]),
                **_keyframe_environment(request),
                expected_revision=_required_revision(request),
            )
            return JsonResponse(
                200,
                {
                    "reference_prompt": result.reference_prompt,
                    "instruction": result.instruction,
                    "ready": result.ready,
                    "operation": result.operation.value,
                    "attachments": [
                        {
                            "asset_id": asset.id,
                            "display_name": asset.display_name,
                            "content_url": f"{self.resource_path}/assets/{asset.id}/content",
                            "role": (
                                "source_image"
                                if result.operation is GenerationOperation.EDIT and index == 0
                                else "reference_image"
                            ),
                            "input_roles": list(result.input_roles[index]),
                            "purpose": result.input_purposes[index],
                        }
                        for index, asset in enumerate(result.input_assets)
                    ],
                },
            )
        if method == "POST" and action == "/extract-frame":
            result = await self._service._media.extract_keyframe_video_frame(
                keyframe_id=keyframe_id,
                frame_index=_frame_index(request),
                expected_source_video_asset_id=_id(
                    request["source_video_asset_id"], "source_video_asset_id"
                ),
                expected_revision=_required_revision(request),
            )
            return JsonResponse(200, self._serialize_snapshot(result))
        if method == "POST" and action == "/generate":
            result = await self._execute_button_command(
                "keyframe.generate",
                _required_revision(request),
                target_ids=(keyframe_id,),
            )
            return JsonResponse(202, self._serialize_snapshot(result))
        if method == "POST" and action == "/select":
            result = await self._execute_button_command(
                "keyframe.select_candidate",
                _required_revision(request),
                target_ids=(keyframe_id, _id(request["asset_id"], "asset_id")),
            )
            return JsonResponse(200, self._serialize_snapshot(result))
        return _error(404, "not_found", "请求的资源不存在。")

    async def _save_segment_keyframe_references(self, segment_id: str, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision", "asset_ids"})
        if isinstance(request, JsonResponse):
            return request
        result = await self._service.save_segment_keyframe_references(
            segment_id=segment_id,
            asset_ids=_id_list(request["asset_ids"]),
            expected_revision=_required_revision(request),
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _save_segment_keyframe_boundary(self, segment_id: str, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision", "shared"})
        if isinstance(request, JsonResponse):
            return request
        result = await self._service.save_segment_boundary_sharing(
            segment_id=segment_id,
            shared=_boolean(request["shared"], "shared"),
            expected_revision=_required_revision(request),
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _save_segment_keyframe_activation(self, segment_id: str, body: bytes) -> JsonResponse:
        binding_fields = {
            "expected_start_keyframe_id",
            "expected_end_keyframe_id",
            "expected_start_enabled",
            "expected_end_enabled",
            "expected_start_selected_asset_id",
            "expected_end_selected_asset_id",
        }
        request = _parse_request(
            body,
            required={"expected_revision", "start_enabled", "end_enabled"},
            optional=binding_fields,
        )
        if isinstance(request, JsonResponse):
            return request
        provided_binding_fields = binding_fields & set(request)
        if provided_binding_fields and provided_binding_fields != binding_fields:
            return _error(400, "invalid_request", "关键帧并发前置条件必须完整提供。")
        expected_binding = None
        if provided_binding_fields:
            expected_binding = (
                _id(request["expected_start_keyframe_id"], "expected_start_keyframe_id"),
                _id(request["expected_end_keyframe_id"], "expected_end_keyframe_id"),
                _boolean(request["expected_start_enabled"], "expected_start_enabled"),
                _boolean(request["expected_end_enabled"], "expected_end_enabled"),
                _optional_id(
                    request["expected_start_selected_asset_id"],
                    "expected_start_selected_asset_id",
                ),
                _optional_id(
                    request["expected_end_selected_asset_id"],
                    "expected_end_selected_asset_id",
                ),
            )
        result = await self._service.save_segment_keyframe_activation(
            segment_id=segment_id,
            start_enabled=_boolean(request["start_enabled"], "start_enabled"),
            end_enabled=_boolean(request["end_enabled"], "end_enabled"),
            expected_revision=_required_revision(request),
            expected_binding=expected_binding,
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _segment_video_action(
        self, method: str, segment_id: str, action: str, body: bytes
    ) -> JsonResponse:
        required = {
            "/inputs-preview": {"expected_revision", "bindings", "params"},
            "/inputs": {"expected_revision", "prompt_text", "bindings", "params"},
            "/recipe": {"expected_revision", "recipe_id"},
            "/attach-candidate": {"expected_revision", "asset_id"},
            "/select": {"expected_revision", "asset_id"},
        }.get(action, {"expected_revision"})
        request = _parse_request(
            body,
            required=required,
            optional={"seed"} if method == "POST" and action == "/generate" else set(),
        )
        if isinstance(request, JsonResponse):
            return request
        if method == "POST" and action == "/inputs-preview":
            state = self._service.preview_segment_video_inputs(
                segment_id,
                RecipeInputs.from_json(
                    {"bindings": request["bindings"], "params": request["params"]}
                ),
                _required_revision(request),
            )
            return JsonResponse(200, state)
        if method == "PUT" and action == "/inputs":
            result = await self._service.save_segment_video_inputs(
                segment_id=segment_id,
                prompt_text=_string(request, "prompt_text"),
                bindings=request["bindings"],
                params=request["params"],
                expected_revision=_required_revision(request),
            )
            return JsonResponse(200, self._serialize_snapshot(result))
        if method == "PUT" and action == "/recipe":
            result = await self._service.save_segment_video_recipe(
                segment_id=segment_id,
                recipe_id=_string(request, "recipe_id"),
                expected_revision=_required_revision(request),
            )
            return JsonResponse(200, self._serialize_snapshot(result))
        if method == "POST" and action == "/generate":
            seed = None
            if "seed" in request:
                raw_seed = request["seed"]
                if (
                    not isinstance(raw_seed, str)
                    or not raw_seed
                    or len(raw_seed) > 19
                    or not raw_seed.isascii()
                    or not raw_seed.isdecimal()
                ):
                    raise ValueError("视频 Seed 必须是十进制整数字符串。")
                seed = int(raw_seed)
            result = await self._execute_button_command(
                "video.generate",
                _required_revision(request),
                target_ids=(segment_id,),
                options={"seed": seed},
            )
            return JsonResponse(202, self._serialize_snapshot(result))
        if method == "POST" and action == "/attach-candidate":
            result = await self._service.attach_segment_video_candidate(
                segment_id=segment_id,
                asset_id=_id(request["asset_id"], "asset_id"),
                expected_revision=_required_revision(request),
            )
            return JsonResponse(200, self._serialize_snapshot(result))
        if method == "POST" and action == "/select":
            result = await self._execute_button_command(
                "video.select_candidate",
                _required_revision(request),
                target_ids=(segment_id, _id(request["asset_id"], "asset_id")),
            )
            return JsonResponse(200, self._serialize_snapshot(result))
        if method == "POST" and action == "/clear-selection":
            result = await self._service.clear_segment_video_selection(
                segment_id=segment_id,
                expected_revision=_required_revision(request),
            )
            return JsonResponse(200, self._serialize_snapshot(result))
        if method == "POST" and action == "/upscale":
            result = await self._execute_button_command(
                "video.upscale",
                _required_revision(request),
                target_ids=(segment_id,),
            )
            return JsonResponse(202, self._serialize_snapshot(result))
        return _error(404, "not_found", "请求的资源不存在。")

    async def _enter_final(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision"})
        if isinstance(request, JsonResponse):
            return request
        result = await self._service.enter_final_stage(
            expected_revision=_required_revision(request)
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _generate_final(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision"})
        if isinstance(request, JsonResponse):
            return request
        revision = _required_revision(request)
        result = (
            await self._service.execute_director_command(
                DirectorCommand(
                    "final.assemble",
                    revision,
                    f"button:final.assemble:{revision}",
                    {},
                )
            )
        ).document
        return JsonResponse(202, self._serialize_snapshot(result))

    async def _generate_scene_animatic(self, scene_id: str, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision"})
        if isinstance(request, JsonResponse):
            return request
        revision = _required_revision(request)
        result = (
            await self._service.execute_director_command(
                DirectorCommand(
                    "animatic.generate_scene",
                    revision,
                    f"button:animatic.generate_scene:{revision}:{scene_id}",
                    {"scene_id": scene_id},
                )
            )
        ).document
        return JsonResponse(202, self._serialize_snapshot(result))

    async def _generate_scene_final(self, scene_id: str, body: bytes) -> JsonResponse:
        request = _parse_request(
            body,
            required={"expected_revision"},
            optional={"video_audio_volume", "narration_audio_volume"},
        )
        if isinstance(request, JsonResponse):
            return request
        revision = _required_revision(request)
        result = (
            await self._service.execute_director_command(
                DirectorCommand(
                    "final.assemble_scene",
                    revision,
                    f"button:final.assemble_scene:{revision}:{scene_id}",
                    {
                        "scene_id": scene_id,
                        "video_audio_volume": _number(
                            request.get("video_audio_volume", 1.0), "video_audio_volume"
                        ),
                        "narration_audio_volume": _number(
                            request.get("narration_audio_volume", 1.0),
                            "narration_audio_volume",
                        ),
                    },
                )
            )
        ).document
        return JsonResponse(202, self._serialize_snapshot(result))

    async def _select_final(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision", "generation_id"})
        if isinstance(request, JsonResponse):
            return request
        revision = _required_revision(request)
        result = (
            await self._service.execute_director_command(
                DirectorCommand(
                    "final.select_candidate",
                    revision,
                    f"button:final.select_candidate:{revision}",
                    {"generation_id": _id(request["generation_id"], "generation_id")},
                )
            )
        ).document
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _apply_location_operations(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision", "scope", "operations"})
        if isinstance(request, JsonResponse):
            return request
        command = location_operations_command(
            scope=request["scope"],
            operations=request["operations"],
            expected_revision=_required_revision(request),
        )
        result = (await self._service.execute_director_command(command)).document
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _location_action(self, location_id: str, action: str, body: bytes) -> JsonResponse:
        if action == "master/generate":
            return await self._generate_location("location.generate_master", location_id, body)
        if action == "calibrate":
            request = _parse_request(
                body,
                required={"expected_revision", "fixture_azimuths", "key_light_azimuth_deg"},
            )
            if isinstance(request, JsonResponse):
                return request
            command = location_calibration_command(
                location_id=location_id,
                fixture_azimuths=request["fixture_azimuths"],
                key_light_azimuth_deg=request["key_light_azimuth_deg"],
                expected_revision=_required_revision(request),
            )
        else:
            request = _parse_request(body, required={"expected_revision", "asset_id"})
            if isinstance(request, JsonResponse):
                return request
            command = location_selection_command(
                target="master",
                target_id=location_id,
                asset_id=_id(request["asset_id"], "asset_id"),
                expected_revision=_required_revision(request),
            )
        result = (await self._service.execute_director_command(command)).document
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _generate_location(self, name: str, target_id: str, body: bytes) -> JsonResponse:
        """卡片单项生成按钮：与 Agent 的 location.generate_* 同一用例，只提交该目标。"""
        request = _parse_request(body, required={"expected_revision"})
        if isinstance(request, JsonResponse):
            return request
        result = await self._execute_button_command(
            name, _required_revision(request), target_ids=(target_id,)
        )
        return JsonResponse(202, self._serialize_snapshot(result))

    async def _location_view_action(self, view_id: str, action: str, body: bytes) -> JsonResponse:
        if action == "generate":
            return await self._generate_location("location.generate_view", view_id, body)
        request = _parse_request(body, required={"expected_revision", "asset_id"})
        if isinstance(request, JsonResponse):
            return request
        command = location_selection_command(
            target="view",
            target_id=view_id,
            asset_id=_id(request["asset_id"], "asset_id"),
            expected_revision=_required_revision(request),
        )
        result = (await self._service.execute_director_command(command)).document
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _approve_final(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision", "zh_asset_id", "en_asset_id"})
        if isinstance(request, JsonResponse):
            return request
        revision = _required_revision(request)
        result = (
            await self._service.execute_director_command(
                DirectorCommand(
                    "final.approve",
                    revision,
                    f"button:final.approve:{revision}",
                    {
                        "zh_asset_id": _optional_id(request["zh_asset_id"], "zh_asset_id"),
                        "en_asset_id": _optional_id(request["en_asset_id"], "en_asset_id"),
                    },
                )
            )
        ).document
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _clear_final_selection(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision"})
        if isinstance(request, JsonResponse):
            return request
        revision = _required_revision(request)
        result = (
            await self._service.execute_director_command(
                DirectorCommand(
                    "final.clear_selection",
                    revision,
                    f"button:final.clear_selection:{revision}",
                    {},
                )
            )
        ).document
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _reopen_video_production(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision"})
        if isinstance(request, JsonResponse):
            return request
        revision = _required_revision(request)
        result = (
            await self._service.execute_director_command(
                DirectorCommand(
                    "final.reopen_production",
                    revision,
                    f"button:final.reopen_production:{revision}",
                    {},
                )
            )
        ).document
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _add_card(self, kind: str, body: bytes) -> JsonResponse:
        fields = {"expected_revision", "name", "visual_description", "voice_description"}
        request = _parse_request(body, required=fields)
        if isinstance(request, JsonResponse):
            return request
        revision = _parse_revision(request)
        if isinstance(revision, JsonResponse):
            return revision
        result = await self._service.add_character(
            CharacterCardProposal(
                _string(request, "name"),
                None
                if request["visual_description"] is None
                else _string(request, "visual_description"),
                _string(request, "voice_description"),
            ),
            expected_revision=revision,
        )
        return JsonResponse(201, self._serialize_snapshot(result))

    async def _update_card(self, kind: str, card_id: str, body: bytes) -> JsonResponse:
        request = _parse_request(
            body,
            required=_CHARACTER_UPDATE_FIELDS - {"voice_reference_transcript"},
            optional={"voice_reference_transcript"},
        )
        if isinstance(request, JsonResponse):
            return request
        revision = _parse_revision(request)
        if isinstance(revision, JsonResponse):
            return revision
        looks, created_look_ids = _parse_character_looks(request["looks"])
        result = await self._service.update_character(
            CharacterCard(
                id=card_id,
                name=_string(request, "name"),
                visual_description=None
                if request["visual_description"] is None
                else _string(request, "visual_description"),
                voice_description=_string(request, "voice_description"),
                voice_reference_asset_id=_optional_id(
                    request["voice_reference_asset_id"],
                    "voice_reference_asset_id",
                ),
                voice_reference_transcript=(
                    None
                    if request.get("voice_reference_transcript") is None
                    else _string(request, "voice_reference_transcript")
                ),
                looks=looks,
            ),
            expected_revision=revision,
            created_look_ids=created_look_ids,
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _update_narrator(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision", "id", "name", "zh", "en"})
        if isinstance(request, JsonResponse):
            return request
        result = await self._service.update_narrator(
            NarratorProfile(
                id=_id(request["id"], "id"),
                name=_string(request, "name"),
                zh=_narrator_voice(request["zh"], "zh"),
                en=_narrator_voice(request["en"], "en"),
            ),
            expected_revision=_required_revision(request),
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _discard_card(self, kind: str, card_id: str, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision"})
        if isinstance(request, JsonResponse):
            return request
        revision = _parse_revision(request)
        if isinstance(revision, JsonResponse):
            return revision
        result = await self._service.discard_card(card_id, kind=kind, expected_revision=revision)
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _import_image_asset(
        self, body: bytes, *, media_type: str | None, query: str
    ) -> JsonResponse:
        request = _parse_query(
            query,
            required={"expected_revision", "category"},
            optional={"filename"},
        )
        result = await self._service.import_image_asset(
            media_type=_required_media_type(media_type),
            content=body,
            category=ImageAssetCategory(request["category"]),
            filename=_query_filename(request),
            expected_revision=_query_revision(request),
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _import_media_asset(
        self, body: bytes, *, media_type: str | None, query: str
    ) -> JsonResponse:
        request = _parse_query(
            query,
            required={"expected_revision"},
            optional={"filename"},
        )
        result = await self._service.import_media_asset(
            media_type=_required_media_type(media_type),
            content=body,
            filename=_query_filename(request),
            expected_revision=_query_revision(request),
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _delete_asset(self, asset_id: str, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision"})
        if isinstance(request, JsonResponse):
            return request
        result = await self._service.delete_asset(
            asset_id,
            expected_revision=_required_revision(request),
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _delete_assets(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision", "asset_ids"})
        if isinstance(request, JsonResponse):
            return request
        raw_asset_ids = request["asset_ids"]
        if not isinstance(raw_asset_ids, list):
            raise ValueError("asset_ids 必须是数组。")
        asset_ids = tuple(_id(item, "asset_ids") for item in raw_asset_ids)
        result = await self._service.delete_assets(
            asset_ids,
            expected_revision=_required_revision(request),
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _apply_audio_effect(self, asset_id: str, body: bytes) -> JsonResponse:
        parsed = _parse_request(
            body,
            required={"expected_revision", "effect", "preset", "strength", "seed"},
            optional={"parameters", "start_seconds", "end_seconds"},
        )
        if isinstance(parsed, JsonResponse):
            return parsed
        raw_parameters = parsed.get("parameters", {})
        if not isinstance(raw_parameters, dict) or any(
            not isinstance(key, str) or not (value is None or isinstance(value, (bool, int, float)))
            for key, value in raw_parameters.items()
        ):
            raise ValueError("parameters 必须是只包含标量覆盖值的对象。")
        request = AudioEffectRequest(
            effect=_string(parsed, "effect"),
            preset=_string(parsed, "preset"),
            strength=_number(parsed["strength"], "strength"),
            seed=_integer(parsed["seed"], "seed"),
            parameters=dict(raw_parameters),
            start_seconds=(
                None
                if parsed.get("start_seconds") is None
                else _number(parsed["start_seconds"], "start_seconds")
            ),
            end_seconds=(
                None
                if parsed.get("end_seconds") is None
                else _number(parsed["end_seconds"], "end_seconds")
            ),
        )
        result = await self._service.apply_audio_effect(
            source_asset_id=asset_id,
            request=request,
            expected_revision=_required_revision(parsed),
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _trim_audio(self, asset_id: str, body: bytes) -> JsonResponse:
        request = _parse_request(
            body,
            required={"expected_revision", "start_seconds", "end_seconds"},
        )
        if isinstance(request, JsonResponse):
            return request
        result = await self._service.trim_audio(
            source_asset_id=asset_id,
            request=AudioTrimRequest(
                start_seconds=_number(request["start_seconds"], "start_seconds"),
                end_seconds=_number(request["end_seconds"], "end_seconds"),
            ),
            expected_revision=_required_revision(request),
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _transcribe_audio(self, asset_id: str, body: bytes) -> JsonResponse:
        request = _parse_request(body, required=set(), optional={"language"})
        if isinstance(request, JsonResponse):
            return request
        try:
            result = await self._service.transcribe_audio(
                asset_id,
                language=("auto" if "language" not in request else _string(request, "language")),
            )
        except FileNotFoundError:
            return _error(404, "asset_not_found", "Asset 不存在。")
        except RuntimeError as exc:
            return _error(409, "provider_unavailable", str(exc), recoverable=True)
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        return JsonResponse(200, {"transcript": result.text})

    async def _generate_asset_audio(self, body: bytes) -> JsonResponse:
        request = _parse_request(
            body,
            required={"expected_revision", "operation", "text", "seed"},
            optional={
                "voice_description",
                "voice_asset_id",
                "reference_transcript",
                "recipe_params",
            },
        )
        if isinstance(request, JsonResponse):
            return request
        operation = request["operation"]
        if operation == "voice_design":
            clone_fields = ("voice_asset_id", "reference_transcript", "recipe_params")
            if any(key in request for key in clone_fields):
                raise ValueError("Voice Design 只能提交 Voice Description 和要朗读的文本。")
            if "voice_description" not in request:
                raise ValueError("Voice Design 必须提供 Voice Description。")
            voice_description = _string(request, "voice_description")
            voice_asset_id = None
            reference_transcript = None
            recipe_params = RecipeParams()
        elif operation == "synthesize":
            if "voice_description" in request:
                raise ValueError("Voice Clone/Direction 不能提交 Voice Description。")
            voice_description = None
            if "reference_transcript" not in request:
                raise ValueError("Voice Clone/Direction 必须提供参考音频完整文字稿。")
            voice_asset_id = _id(request.get("voice_asset_id"), "voice_asset_id")
            reference_transcript = _string(request, "reference_transcript")
            # 按 recipe 的克隆机制参数（如 Breeze 表演指示）；缺省时用 manifest 默认值。
            recipe_params = RecipeParams.from_json(request.get("recipe_params", {}))
        else:
            raise ValueError("operation 只允许 voice_design 或 synthesize。")
        result = await self._service._media.generate_asset_audio(
            text=_string(request, "text"),
            seed=_integer(request["seed"], "seed"),
            voice_description=voice_description,
            voice_asset_id=voice_asset_id,
            reference_transcript=reference_transcript,
            recipe_params=recipe_params,
            expected_revision=_required_revision(request),
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _separate_video_audio(self, asset_id: str, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision"})
        if isinstance(request, JsonResponse):
            return request
        try:
            result = await self._service.separate_video_audio(
                source_asset_id=asset_id,
                expected_revision=_required_revision(request),
            )
        except RevisionConflictError as exc:
            return _error(409, "revision_conflict", str(exc), recoverable=True)
        except RuntimeError as exc:
            return _error(409, "provider_unavailable", str(exc))
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        return JsonResponse(202, self._serialize_snapshot(result))

    async def _remix_video_audio(self, asset_id: str, body: bytes) -> JsonResponse:
        request = _parse_request(
            body,
            required={
                "expected_revision",
                "voice_asset_id",
                "background_asset_id",
                "voice_gain_db",
                "background_gain_db",
            },
            optional={
                "voice_gain_start_seconds",
                "voice_gain_end_seconds",
                "background_gain_start_seconds",
                "background_gain_end_seconds",
            },
        )
        if isinstance(request, JsonResponse):
            return request
        try:
            result = await self._service.remix_video_audio(
                source_asset_id=asset_id,
                voice_asset_id=_id(request["voice_asset_id"], "voice_asset_id"),
                background_asset_id=_id(request["background_asset_id"], "background_asset_id"),
                voice_gain_db=_number(request["voice_gain_db"], "voice_gain_db"),
                background_gain_db=_number(request["background_gain_db"], "background_gain_db"),
                voice_gain_start_seconds=_optional_number(request, "voice_gain_start_seconds"),
                voice_gain_end_seconds=_optional_number(request, "voice_gain_end_seconds"),
                background_gain_start_seconds=_optional_number(
                    request, "background_gain_start_seconds"
                ),
                background_gain_end_seconds=_optional_number(
                    request, "background_gain_end_seconds"
                ),
                expected_revision=_required_revision(request),
            )
        except RevisionConflictError as exc:
            return _error(409, "revision_conflict", str(exc), recoverable=True)
        except RuntimeError as exc:
            return _error(409, "provider_unavailable", str(exc))
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        return JsonResponse(202, self._serialize_snapshot(result))

    async def _upload_voice(
        self,
        card_id: str,
        body: bytes,
        *,
        media_type: str | None,
        query: str,
    ) -> JsonResponse:
        request = _parse_query(query, required={"expected_revision"}, optional={"filename"})
        result = await self._service.upload_reference_voice(
            card_id=card_id,
            media_type=_required_media_type(media_type),
            content=body,
            filename=_query_filename(request),
            expected_revision=_query_revision(request),
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _upload_narrator_voice(
        self, body: bytes, *, media_type: str | None, query: str
    ) -> JsonResponse:
        request = _parse_query(
            query,
            required={"expected_revision", "narrator_id", "language"},
            optional={"filename"},
        )
        result = await self._service.upload_narrator_voice(
            narrator_id=_id(request["narrator_id"], "narrator_id"),
            language=NarrationLanguage(parse_narration_language(request["language"])),
            media_type=_required_media_type(media_type),
            content=body,
            filename=_query_filename(request),
            expected_revision=_query_revision(request),
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _design_voice(self, card_id: str, body: bytes) -> JsonResponse:
        request = _parse_request(
            body,
            required={"expected_revision", "voice_description", "sample_text", "seed"},
        )
        if isinstance(request, JsonResponse):
            return request
        revision = _parse_revision(request)
        if isinstance(revision, JsonResponse):
            return revision
        try:
            seed = request["seed"]
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise ValueError("seed 必须是整数。")
            result = await self._service._media.design_voice(
                card_id=card_id,
                voice_description=_string(request, "voice_description"),
                sample_text=_string(request, "sample_text"),
                seed=seed,
                expected_revision=revision,
            )
        except StagePrerequisiteError as exc:
            return _stage_error(exc)
        except RevisionConflictError as exc:
            return _error(409, "revision_conflict", str(exc), recoverable=True)
        except RuntimeError as exc:
            return _error(409, "provider_unavailable", str(exc))
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        return JsonResponse(202, self._serialize_snapshot(result))

    async def _design_narrator_voice(self, body: bytes) -> JsonResponse:
        request = _parse_request(
            body,
            required={
                "expected_revision",
                "narrator_id",
                "language",
                "voice_description",
                "sample_text",
                "seed",
            },
        )
        if isinstance(request, JsonResponse):
            return request
        try:
            result = await self._service._media.design_voice(
                card_id=_id(request["narrator_id"], "narrator_id"),
                voice_description=_string(request, "voice_description"),
                sample_text=_string(request, "sample_text"),
                seed=_integer(request["seed"], "seed"),
                expected_revision=_required_revision(request),
                narrator_language=NarrationLanguage(parse_narration_language(request["language"])),
            )
        except StagePrerequisiteError as exc:
            return _stage_error(exc)
        except RevisionConflictError as exc:
            return _error(409, "revision_conflict", str(exc), recoverable=True)
        except RuntimeError as exc:
            return _error(409, "provider_unavailable", str(exc))
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        return JsonResponse(202, self._serialize_snapshot(result))

    async def _attach_narrator_voice(self, body: bytes) -> JsonResponse:
        request = _parse_request(
            body, required={"expected_revision", "narrator_id", "generation_id"}
        )
        if isinstance(request, JsonResponse):
            return request
        result = await self._service.attach_generation_output(
            kind="narrator_voice",
            card_id=_id(request["narrator_id"], "narrator_id"),
            generation_id=_id(request["generation_id"], "generation_id"),
            note="",
            expected_revision=_required_revision(request),
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _look_action(
        self, card_id: str, look_id: str, verb: str, body: bytes
    ) -> JsonResponse:
        owner = self._service.snapshot_required().reference_library.look_owner(look_id)
        if owner is None or owner[0].id != card_id:
            return _error(404, "not_found", "造型不存在。")
        if verb == "sheet-preview":
            preview = _parse_request(body, required={"identity_asset_ids"})
            if isinstance(preview, JsonResponse):
                return preview
            try:
                prompt = self._service.preview_look_sheet(
                    look_id=look_id,
                    identity_asset_ids=_id_list(
                        preview["identity_asset_ids"], "identity_asset_ids"
                    ),
                )
            except ValueError as exc:
                return _error(400, "invalid_request", str(exc))
            return JsonResponse(200, {"prompt_text": prompt})
        fields = {
            "sheet-generations": {"expected_revision", "identity_asset_ids"},
            "select-sheet": {"expected_revision", "generation_id"},
            "select-asset": {"expected_revision", "asset_id"},
        }[verb]
        request = _parse_request(
            body,
            required=fields,
            optional={"prompt_text"} if verb == "sheet-generations" else set(),
        )
        if isinstance(request, JsonResponse):
            return request
        revision = _parse_revision(request)
        if isinstance(revision, JsonResponse):
            return revision
        if verb == "select-asset":
            result = await self._service.select_look_asset(
                card_id=card_id,
                look_id=look_id,
                asset_id=_id(request["asset_id"], "asset_id"),
                expected_revision=revision,
            )
            return JsonResponse(200, self._serialize_snapshot(result))
        if verb == "select-sheet":
            result = await self._service.select_look_sheet(
                card_id=card_id,
                look_id=look_id,
                generation_id=_id(request["generation_id"], "generation_id"),
                expected_revision=revision,
            )
            return JsonResponse(200, self._serialize_snapshot(result))
        try:
            prompt_text = request.get("prompt_text")
            if prompt_text is not None and not isinstance(prompt_text, str):
                raise ValueError("prompt_text 必须是字符串或 null。")
            result = await self._service.generate_look_sheet(
                look_id=look_id,
                identity_asset_ids=_id_list(request["identity_asset_ids"], "identity_asset_ids"),
                expected_revision=revision,
                prompt_text=prompt_text,
            )
        except RevisionConflictError as exc:
            return _error(409, "revision_conflict", str(exc), recoverable=True)
        except RuntimeError as exc:
            return _error(409, "provider_unavailable", str(exc))
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        return JsonResponse(202, self._serialize_snapshot(result))

    async def _attach_output(self, kind: str, card_id: str, body: bytes) -> JsonResponse:
        request = _parse_request(body, required={"expected_revision", "generation_id"})
        if isinstance(request, JsonResponse):
            return request
        revision = _parse_revision(request)
        if isinstance(revision, JsonResponse):
            return revision
        result = await self._service.attach_generation_output(
            kind=kind,
            card_id=card_id,
            generation_id=_id(request["generation_id"], "generation_id"),
            note="",
            expected_revision=revision,
        )
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _generation_action(
        self, generation_id: str, action: str, body: bytes
    ) -> JsonResponse:
        request = _parse_request(
            body,
            required={"expected_revision"} if action != "refresh" else set(),
        )
        if isinstance(request, JsonResponse):
            return request
        if action == "refresh":
            result = await self._service._generation_observer.refresh_generation(generation_id)
        else:
            revision = _parse_revision(request)
            if isinstance(revision, JsonResponse):
                return revision
            execution = await self._service.execute_generation_command(
                DirectorCommand(
                    f"generation.{action}",
                    revision,
                    f"ui-generation-{action}:{revision}:{generation_id}",
                    {"generation_ids": [generation_id]}
                    if action == "wait"
                    else {"generation_id": generation_id},
                )
            )
            result = execution.document
        return JsonResponse(200, self._serialize_snapshot(result))

    async def _refresh_active_generations(self, body: bytes) -> JsonResponse:
        request = _parse_request(body, required=set())
        if isinstance(request, JsonResponse):
            return request
        result = await self._service._generation_observer.refresh_active_generations()
        return JsonResponse(200, self._serialize_snapshot(result))

    def _serialize_snapshot(self, document: StructuredDirectorDocument) -> dict[str, Any]:
        return serialize_snapshot(document, self._service, self.resource_path)


def _optional_number(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    return None if value is None else _number(value, key)


def _stage_error(exc: StagePrerequisiteError) -> JsonResponse:
    return JsonResponse(
        409,
        {
            "error": {
                "code": "stage_prerequisite_not_met",
                "message": str(exc),
                "recoverable": True,
                "origin": "workflow_prerequisite",
                "state_changed": False,
                "retry_policy": "follow_required_next_actions",
                "automatic_retry_allowed": False,
                "reason": exc.reason,
                **exc.workflow,
            }
        },
    )


def _director_run_yielded(active_run: object) -> bool:
    status = getattr(active_run, "status", None)
    return status in {DirectorRunStatus.WAITING_USER, DirectorRunStatus.WAITING_JOBS}


def _keyframe_environment(request: dict[str, Any]) -> dict[str, object]:
    """Keyframe 地点视图三项；none 理由可选，只解释退出原因、不进入提交，空白归一为 null。"""
    mode = KeyframeEnvironmentMode(_string(request, "environment_mode"))
    reason = request["environment_none_reason"]
    if reason is not None:
        reason = normalize_environment_none_reason(_plain_string(reason, "environment_none_reason"))
    return {
        "environment_mode": mode,
        "environment_view_id": _optional_id(request["environment_view_id"], "environment_view_id"),
        "environment_none_reason": reason,
    }


def _reject_location_binding_changes(document, scenes: list[dict[str, Any]]) -> None:
    """脚本整卡回传的地点绑定只读；修改绑定走地点操作。"""
    current = {
        scene.id: (
            scene.location_id,
            scene.state_id,
            {shot.id: shot.view_id for shot in scene.shots},
        )
        for scene in (() if document.director_script is None else document.director_script.scenes)
    }
    for scene in scenes:
        location_id, state_id, views = current.get(scene["id"], (None, None, {}))
        if (scene["location_id"], scene["state_id"]) != (location_id, state_id) or any(
            shot["view_id"] != views.get(shot["id"]) for shot in scene["shots"]
        ):
            raise ValueError("Scene 地点、状态与 Shot 视图绑定请通过地点操作修改。")


def _recovery_path(resource_path: str, active_run: object) -> str | None:
    kind = getattr(active_run, "kind", None)
    status = getattr(active_run, "status", None)
    return {
        DirectorRunKind.REFERENCE_PROPOSAL: f"{resource_path}/reference-proposal",
        DirectorRunKind.SCRIPT_PROPOSAL: f"{resource_path}/script-proposal",
        DirectorRunKind.SCRIPT_EDIT: f"{resource_path}/director-script/recover",
        DirectorRunKind.NARRATION_EDIT: f"{resource_path}/narration/recover",
        DirectorRunKind.KEYFRAME_PLAN: f"{resource_path}/keyframe-proposal",
        DirectorRunKind.LOCATION_PLAN: f"{resource_path}/location-proposal",
        DirectorRunKind.DIRECTOR: (
            f"{resource_path}/director/messages"
            if status is DirectorRunStatus.WAITING_USER
            else f"{resource_path}/director/recover"
        ),
    }.get(kind)


@dataclass(frozen=True, slots=True)
class _ErrorPolicy:
    runtime_code: str = "provider_unavailable"
    runtime_recoverable: bool = True
    value_status: int = 400
    value_code: str = "invalid_request"
    revision_details: bool = False


_Handler = Callable[
    ["StructuredDirectorHttpApi", str, re.Match[str] | None, bytes, str | None, str],
    Awaitable[JsonResponse],
]


@dataclass(frozen=True, slots=True)
class _Route:
    methods: frozenset[str]
    pattern: str | re.Pattern[str]
    invoke: _Handler
    authorization: str
    gate: str = "write"
    error_policy: _ErrorPolicy = _ErrorPolicy()


def _match_route(method: str, suffix: str) -> tuple[_Route | None, re.Match[str] | None]:
    for route in _ROUTES:
        if method not in route.methods:
            continue
        if isinstance(route.pattern, str):
            if suffix == route.pattern:
                return route, None
            continue
        match = route.pattern.fullmatch(suffix)
        if match is not None:
            return route, match
    return None, None


def _body_route(handler_name: str) -> _Handler:
    async def invoke(
        api: StructuredDirectorHttpApi,
        method: str,
        match: re.Match[str] | None,
        body: bytes,
        media_type: str | None,
        query: str,
    ) -> JsonResponse:
        del method, match, media_type, query
        handler = getattr(api, handler_name)
        return await handler(body)

    return invoke


def _body_media_route(handler_name: str) -> _Handler:
    async def invoke(
        api: StructuredDirectorHttpApi,
        method: str,
        match: re.Match[str] | None,
        body: bytes,
        media_type: str | None,
        query: str,
    ) -> JsonResponse:
        del method, match
        handler = getattr(api, handler_name)
        return await handler(body, media_type=media_type, query=query)

    return invoke


def _frame_index(request: dict[str, object]) -> int:
    value = request["frame_index"]
    if type(value) is not int or value < 0:
        raise ValueError("frame_index 必须是非负整数。")
    return value


def _group_route(handler_name: str, *groups: str, include_method: bool = False) -> _Handler:
    async def invoke(
        api: StructuredDirectorHttpApi,
        method: str,
        match: re.Match[str] | None,
        body: bytes,
        media_type: str | None,
        query: str,
    ) -> JsonResponse:
        del media_type, query
        assert match is not None
        arguments: list[object] = []
        if include_method:
            arguments.append(method)
        arguments.extend(match.group(group) or "" for group in groups)
        handler = getattr(api, handler_name)
        return await handler(*arguments, body)

    return invoke


def _group_media_route(handler_name: str, group: str) -> _Handler:
    async def invoke(
        api: StructuredDirectorHttpApi,
        method: str,
        match: re.Match[str] | None,
        body: bytes,
        media_type: str | None,
        query: str,
    ) -> JsonResponse:
        del method
        assert match is not None
        handler = getattr(api, handler_name)
        return await handler(
            match.group(group),
            body,
            media_type=media_type,
            query=query,
        )

    return invoke


def _command_route(*, include_snapshot: bool) -> _Handler:
    async def invoke(
        api: StructuredDirectorHttpApi,
        method: str,
        match: re.Match[str] | None,
        body: bytes,
        media_type: str | None,
        query: str,
    ) -> JsonResponse:
        del method, match, media_type, query
        handler = api._execute_command
        return await handler(body, include_snapshot=include_snapshot)

    return invoke


async def _snapshot_route(
    api: StructuredDirectorHttpApi,
    method: str,
    match: re.Match[str] | None,
    body: bytes,
    media_type: str | None,
    query: str,
) -> JsonResponse:
    del method, match, body, media_type, query
    snapshot = api._service.snapshot()
    if snapshot is None:
        return _error(404, "project_state_missing", "项目权威状态不存在。")
    return JsonResponse(200, api._serialize_snapshot(snapshot))


async def _card_route(
    api: StructuredDirectorHttpApi,
    method: str,
    match: re.Match[str] | None,
    body: bytes,
    media_type: str | None,
    query: str,
) -> JsonResponse:
    assert match is not None
    handler = api._card_action
    return await handler(
        method,
        match.group("kind"),
        match.group("card_id"),
        match.group("action") or "",
        body,
        media_type=media_type,
        query=query,
    )


_ROUTES: tuple[_Route, ...] = (
    _Route(frozenset({"GET"}), "", _snapshot_route, "project.read", gate="none"),
    _Route(
        frozenset({"PUT"}),
        "/director-script",
        _body_route("_save_script"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/director-script/confirm",
        _body_route("_confirm_script"),
        "project.write",
        error_policy=_ErrorPolicy(value_status=409, value_code="action_not_allowed"),
    ),
    _Route(
        frozenset({"POST"}),
        "/narration/generate-batch",
        _body_route("_generate_narration_batch"),
        "project.write",
    ),
    _Route(
        frozenset({"PUT"}),
        "/narrator",
        _body_route("_update_narrator"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/narrator/voice-generations",
        _body_route("_design_narrator_voice"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/narrator/voice-reference/upload",
        _body_media_route("_upload_narrator_voice"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/narrator/voice-reference/attach",
        _body_route("_attach_narrator_voice"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/visual-production/unlock",
        _body_route("_unlock_visual_production"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/locations/operations",
        _body_route("_apply_location_operations"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        _LOCATION_RESOURCE,
        _group_route("_location_action", "location_id", "action"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        _LOCATION_VIEW_RESOURCE,
        _group_route("_location_view_action", "view_id", "action"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/keyframes/generate-batch",
        _body_route("_generate_keyframe_batch"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/generations/refresh",
        _body_route("_refresh_active_generations"),
        "project.write",
        gate="provider_observation",
    ),
    _Route(
        frozenset({"POST"}),
        "/commands",
        _command_route(include_snapshot=True),
        "project.write",
        gate="active_command",
    ),
    _Route(
        frozenset({"POST"}),
        "/application/commands",
        _command_route(include_snapshot=False),
        "project.write",
        gate="active_command",
    ),
    _Route(
        frozenset({"POST"}),
        "/final/enter",
        _body_route("_enter_final"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/final/generate",
        _body_route("_generate_final"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/final/select",
        _body_route("_select_final"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/final/clear-selection",
        _body_route("_clear_final_selection"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/final/approve",
        _body_route("_approve_final"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/final/reopen-videos",
        _body_route("_reopen_video_production"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/assets/images",
        _body_media_route("_import_image_asset"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        "/assets/media",
        _body_media_route("_import_media_asset"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        _GENERATION_RESOURCE,
        _group_route("_generation_action", "generation_id", "action"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        _SCENE_ANIMATIC_RESOURCE,
        _group_route("_generate_scene_animatic", "scene_id"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        _SCENE_FINAL_RESOURCE,
        _group_route("_generate_scene_final", "scene_id"),
        "project.write",
    ),
    _Route(
        frozenset({"PUT", "POST"}),
        _KEYFRAME_RESOURCE,
        _group_route("_keyframe_action", "keyframe_id", "action", include_method=True),
        "project.write",
    ),
    _Route(
        frozenset({"PUT"}),
        _SEGMENT_KEYFRAME_REFERENCE_RESOURCE,
        _group_route("_save_segment_keyframe_references", "segment_id"),
        "project.write",
    ),
    _Route(
        frozenset({"PUT"}),
        _SEGMENT_KEYFRAME_ACTIVATION_RESOURCE,
        _group_route("_save_segment_keyframe_activation", "segment_id"),
        "project.write",
    ),
    _Route(
        frozenset({"PUT"}),
        _SEGMENT_KEYFRAME_BOUNDARY_RESOURCE,
        _group_route("_save_segment_keyframe_boundary", "segment_id"),
        "project.write",
    ),
    _Route(
        frozenset({"POST", "PUT"}),
        _SEGMENT_VIDEO_RESOURCE,
        _group_route("_segment_video_action", "segment_id", "action", include_method=True),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        _AUDIO_GENERATIONS_RESOURCE,
        _body_route("_generate_asset_audio"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        _ASSET_TRANSCRIPTION_RESOURCE,
        _group_route("_transcribe_audio", "asset_id"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        _ASSET_AUDIO_TRIM_RESOURCE,
        _group_route("_trim_audio", "asset_id"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        _ASSET_AUDIO_EFFECT_RESOURCE,
        _group_route("_apply_audio_effect", "asset_id"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        _ASSET_AUDIO_SEPARATION_RESOURCE,
        _group_route("_separate_video_audio", "asset_id"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        _ASSET_AUDIO_REMIX_RESOURCE,
        _group_route("_remix_video_audio", "asset_id"),
        "project.write",
    ),
    _Route(
        frozenset({"POST"}),
        _ASSET_VIDEO_FRAME_RESOURCE,
        _group_route("_extract_asset_video_frame", "asset_id"),
        "project.write",
    ),
    _Route(
        frozenset({"GET"}),
        _ASSET_VIDEO_FRAME_INFO_RESOURCE,
        _group_route("_video_frame_info", "asset_id"),
        "project.read",
        gate="none",
    ),
    _Route(
        frozenset({"DELETE"}),
        _ASSET_BATCH_DELETE_RESOURCE,
        _body_route("_delete_assets"),
        "project.write",
    ),
    _Route(
        frozenset({"DELETE"}),
        _ASSET_RESOURCE,
        _group_route("_delete_asset", "asset_id"),
        "project.write",
    ),
    _Route(
        frozenset({"PUT", "POST"}),
        _NARRATION_CUE_RESOURCE,
        _group_route(
            "_narration_cue_action",
            "scene_id",
            "cue_id",
            "action",
            include_method=True,
        ),
        "project.write",
    ),
    _Route(frozenset({"POST", "PUT", "DELETE"}), _CARD_RESOURCE, _card_route, "project.write"),
)


def _narrator_voice(value: object, field: str) -> NarratorVoice | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "voice_description",
        "voice_reference_asset_id",
        "voice_reference_transcript",
    }:
        raise ValueError(f"{field} 旁白音色字段不完整或包含未知字段。")
    return NarratorVoice(
        voice_description=_string(value, "voice_description"),
        voice_reference_asset_id=_optional_id(
            value["voice_reference_asset_id"], f"{field}.voice_reference_asset_id"
        ),
        voice_reference_transcript=(
            _optional_text(
                value["voice_reference_transcript"], f"{field}.voice_reference_transcript"
            )
            or None
        ),
    )
