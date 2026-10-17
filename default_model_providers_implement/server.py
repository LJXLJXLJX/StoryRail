from __future__ import annotations

import argparse
import dataclasses
import hmac
import json
import os
import re
import signal
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .controller_lease import ControllerLease
from .lane_dispatcher import LaneDispatcher, LaneSpec
from .request_builders import (
    prepare_breeze_tts2,
    prepare_codex,
    prepare_demucs_audio_separation,
    prepare_ffmpeg_animatic,
    prepare_ffmpeg_audio_remix,
    prepare_ffmpeg_final_assembly,
    prepare_ffmpeg_pano_view,
    prepare_ffmpeg_video_frame,
    prepare_h3_fl2va,
    prepare_h3_ref2va,
    prepare_indextts2,
    prepare_mock,
    prepare_qwen_image,
    prepare_seedvr2_7b_sharp_fp8,
    prepare_stable_audio_3,
)
from .resource_manager import ResourceLeaseRequiredError
from .runners import (
    agy_runner,
    codex_runner,
    create_breeze_resident_runner,
    create_h3_fl2va_comfy_core_runner,
    create_h3_ref2va_comfy_core_runner,
    create_indextts2_resident_runner,
    create_qwen_image_comfy_core_runner,
    create_seedvr2_resident_runner,
    demucs_audio_separation_runner,
    ffmpeg_animatic_runner,
    ffmpeg_audio_remix_runner,
    ffmpeg_final_assembly_runner,
    ffmpeg_pano_view_runner,
    ffmpeg_video_frame_runner,
    mock_runner,
    stable_audio_3_runner,
)
from .strict_json import RequestError
from .task_store import TaskRecord, TaskStore

MAX_REQUEST_BYTES = 700 * 1024 * 1024
TASK_ID = re.compile(r"^[0-9a-f]{32}$")


class DisabledServiceError(LookupError):
    pass


class ModelApiServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows 的 SO_REUSEADDR 允许两个无关进程争用同一端口；模型服务必须拒绝这种歧义。
    allow_reuse_address = False

    def __init__(
        self,
        address: tuple[str, int],
        root: Path,
        *,
        enabled_services: set[str] | None = None,
        resource_name: str = "exclusive_gpu",
        auth_token: str | None = None,
        controller_lease_timeout_seconds: float | None = None,
        max_concurrent_tasks: int = 1,
        lanes: tuple[LaneSpec, ...] | None = None,
    ) -> None:
        self.enabled_services = enabled_services or {
            "mock",
            "codex_image_generate",
            "codex_image_edit",
            "agy_image_generate",
            "agy_image_edit",
            "h3_fl2va",
            "h3_ref2va",
            "breeze_tts_2",
            "indextts2",
            "seedvr2_7b_sharp_fp8",
            "ffmpeg_final_assembly",
            "ffmpeg_animatic",
            "ffmpeg_video_frame",
            "ffmpeg_pano_view",
            "demucs_audio_separation",
            "ffmpeg_audio_remix",
            "stable_audio_3",
            "qwen_image",
        }
        self.auth_token = auth_token
        self.store = TaskStore(root)
        h3_fl2va_runtime = create_h3_fl2va_comfy_core_runner(root / "resident-runtimes")
        h3_ref2va_runtime = create_h3_ref2va_comfy_core_runner(root / "resident-runtimes")
        breeze_runtime = create_breeze_resident_runner(root / "resident-runtimes")
        indextts2_runtime = create_indextts2_resident_runner(root / "resident-runtimes")
        seedvr2_runtime = create_seedvr2_resident_runner(root / "resident-runtimes")
        qwen_image_runtime = create_qwen_image_comfy_core_runner(root / "resident-runtimes")
        all_runners = {
            "mock": mock_runner,
            "codex_image_generate": codex_runner,
            "codex_image_edit": codex_runner,
            "agy_image_generate": agy_runner,
            "agy_image_edit": agy_runner,
            "h3_fl2va": h3_fl2va_runtime,
            "h3_ref2va": h3_ref2va_runtime,
            "breeze_tts_2": breeze_runtime,
            "indextts2": indextts2_runtime,
            "seedvr2_7b_sharp_fp8": seedvr2_runtime,
            "ffmpeg_final_assembly": ffmpeg_final_assembly_runner,
            "ffmpeg_animatic": ffmpeg_animatic_runner,
            "ffmpeg_video_frame": ffmpeg_video_frame_runner,
            "ffmpeg_pano_view": ffmpeg_pano_view_runner,
            "demucs_audio_separation": demucs_audio_separation_runner,
            "ffmpeg_audio_remix": ffmpeg_audio_remix_runner,
            "stable_audio_3": stable_audio_3_runner,
            "qwen_image": qwen_image_runtime,
        }
        self.manager = LaneDispatcher(
            self.store,
            {name: all_runners[name] for name in self.enabled_services},
            (
                lanes
                if lanes is not None
                else (
                    LaneSpec(
                        name=resource_name,
                        services=frozenset(self.enabled_services),
                        max_concurrent_tasks=max_concurrent_tasks,
                    ),
                )
            ),
            initially_accepting=controller_lease_timeout_seconds is None,
        )
        self.controller_lease = (
            ControllerLease(
                self.manager,
                timeout_seconds=controller_lease_timeout_seconds,
            )
            if controller_lease_timeout_seconds is not None
            else None
        )
        super().__init__(address, ModelApiHandler)


class ModelApiHandler(BaseHTTPRequestHandler):
    server: ModelApiServer
    protocol_version = "HTTP/1.1"
    server_version = "StoryRailDefaultModels/0.1"

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorize():
            return
        path = urlsplit(self.path).path
        try:
            if path == "/control/controller-lease/acquire":
                controller = self.server.controller_lease
                if controller is None:
                    raise DisabledServiceError
                session_id = self._controller_session_id()
                if not controller.acquire(session_id):
                    self._json(409, {"message": "另一个 Mac Core 租约仍然有效。"})
                    return
                self._json(201, {"state": "active"})
                return
            if path == "/control/controller-lease/heartbeat":
                controller = self.server.controller_lease
                if controller is None:
                    raise DisabledServiceError
                session_id = self._controller_session_id()
                if not controller.heartbeat(session_id):
                    self._json(409, {"message": "Mac Core 租约不存在或已经失效。"})
                    return
                self._json(200, {"state": "active"})
                return
            if path == "/mock/generate":
                self._require_enabled("mock")
                record = self.server.manager.submit("mock", prepare_mock(self._read_json()))
                self._json(202, {"ticket": record.task_id})
                return
            if path == "/codex/image-generations":
                self._require_enabled("codex_image_generate")
                record = self.server.manager.submit(
                    "codex_image_generate", prepare_codex(self._read_json(), operation="generate")
                )
                self._json(202, {"request_id": record.task_id, "accepted_at": "persisted"})
                return
            if path == "/codex/image-edits":
                self._require_enabled("codex_image_edit")
                record = self.server.manager.submit(
                    "codex_image_edit", prepare_codex(self._read_json(), operation="edit")
                )
                self._json(202, {"request_id": record.task_id, "accepted_at": "persisted"})
                return
            if path == "/agy/image-generations":
                self._require_enabled("agy_image_generate")
                record = self.server.manager.submit(
                    "agy_image_generate", prepare_codex(self._read_json(), operation="generate")
                )
                self._json(202, {"request_id": record.task_id, "accepted_at": "persisted"})
                return
            if path == "/agy/image-edits":
                self._require_enabled("agy_image_edit")
                record = self.server.manager.submit(
                    "agy_image_edit", prepare_codex(self._read_json(), operation="edit")
                )
                self._json(202, {"request_id": record.task_id, "accepted_at": "persisted"})
                return
            if path == "/minimax-h3/ref2va/renders":
                self._require_enabled("h3_ref2va")
                record = self.server.manager.submit(
                    "h3_ref2va", prepare_h3_ref2va(self._read_json())
                )
                self._json(
                    202,
                    {
                        "render_id": record.task_id,
                        "status_uri": f"/minimax-h3/ref2va/renders/{record.task_id}",
                    },
                )
                return
            if path == "/minimax-h3/fl2va/clips":
                self._require_enabled("h3_fl2va")
                record = self.server.manager.submit("h3_fl2va", prepare_h3_fl2va(self._read_json()))
                self._json(202, {"job_token": record.task_id, "queue_position": 1})
                return
            if path == "/indextts2/speech":
                self._require_enabled("indextts2")
                record = self.server.manager.submit(
                    "indextts2", prepare_indextts2(self._read_json())
                )
                self._json(202, {"speech_id": record.task_id})
                return
            if path == "/breeze-tts2/speech":
                self._require_enabled("breeze_tts_2")
                record = self.server.manager.submit(
                    "breeze_tts_2", prepare_breeze_tts2(self._read_json())
                )
                self._json(202, {"speech_id": record.task_id})
                return
            if path == "/qwen-image/renders":
                self._require_enabled("qwen_image")
                record = self.server.manager.submit(
                    "qwen_image", prepare_qwen_image(self._read_json())
                )
                self._json(202, {"render_id": record.task_id})
                return
            cancel_id = _match(path, r"/qwen-image/renders/([0-9a-f]{32})/cancel")
            if cancel_id:
                self._cancel(cancel_id, "qwen_image")
                return
            if path == "/stable-audio-3/generations":
                self._require_enabled("stable_audio_3")
                record = self.server.manager.submit(
                    "stable_audio_3", prepare_stable_audio_3(self._read_json())
                )
                self._json(202, {"generation_id": record.task_id})
                return
            if path == "/seedvr2/7b-sharp-fp8/upscales":
                self._require_enabled("seedvr2_7b_sharp_fp8")
                record = self.server.manager.submit(
                    "seedvr2_7b_sharp_fp8",
                    prepare_seedvr2_7b_sharp_fp8(self._read_json()),
                )
                self._json(202, {"job_token": record.task_id, "queue_position": 1})
                return
            if path == "/ffmpeg/final-assemblies":
                self._require_enabled("ffmpeg_final_assembly")
                record = self.server.manager.submit(
                    "ffmpeg_final_assembly", prepare_ffmpeg_final_assembly(self._read_json())
                )
                self._json(202, {"assembly_id": record.task_id})
                return
            if path == "/ffmpeg/video-frames":
                self._require_enabled("ffmpeg_video_frame")
                record = self.server.manager.submit(
                    "ffmpeg_video_frame", prepare_ffmpeg_video_frame(self._read_json())
                )
                self._json(202, {"frame_id": record.task_id})
                return
            if path == "/ffmpeg/pano-views":
                self._require_enabled("ffmpeg_pano_view")
                record = self.server.manager.submit(
                    "ffmpeg_pano_view", prepare_ffmpeg_pano_view(self._read_json())
                )
                self._json(202, {"view_id": record.task_id})
                return
            if path == "/ffmpeg/animatics":
                self._require_enabled("ffmpeg_animatic")
                record = self.server.manager.submit(
                    "ffmpeg_animatic", prepare_ffmpeg_animatic(self._read_json())
                )
                self._json(202, {"animatic_id": record.task_id})
                return
            if path == "/demucs/audio-separations":
                self._require_enabled("demucs_audio_separation")
                record = self.server.manager.submit(
                    "demucs_audio_separation",
                    prepare_demucs_audio_separation(self._read_json()),
                )
                self._json(202, {"separation_id": record.task_id})
                return
            if path == "/ffmpeg/audio-remixes":
                self._require_enabled("ffmpeg_audio_remix")
                record = self.server.manager.submit(
                    "ffmpeg_audio_remix", prepare_ffmpeg_audio_remix(self._read_json())
                )
                self._json(202, {"remix_id": record.task_id})
                return
            for route, kind in (
                ("image-generations", "codex_image_generate"),
                ("image-edits", "codex_image_edit"),
            ):
                stop_id = _match(path, rf"/codex/{route}/([0-9a-f]{{32}})/stop")
                if stop_id:
                    self._cancel(stop_id, kind)
                    return
            for route, kind in (
                ("image-generations", "agy_image_generate"),
                ("image-edits", "agy_image_edit"),
            ):
                stop_id = _match(path, rf"/agy/{route}/([0-9a-f]{{32}})/stop")
                if stop_id:
                    self._cancel(stop_id, kind)
                    return
        except RequestError as exc:
            self._json(422, {"message": str(exc)})
            return
        except DisabledServiceError:
            self._json(404, {"message": "接口不存在。"})
            return
        except ResourceLeaseRequiredError as exc:
            self._json(503, {"message": str(exc)})
            return
        except (ValueError, OSError) as exc:
            self._json(400, {"message": str(exc)})
            return
        self._json(404, {"message": "接口不存在。"})

    def do_PUT(self) -> None:  # noqa: N802
        if not self._authorize():
            return
        task_id = _match(urlsplit(self.path).path, r"/ffmpeg/video-frames/([0-9a-f]{32})/abort")
        if task_id:
            self._cancel(task_id, "ffmpeg_video_frame")
            return
        task_id = _match(urlsplit(self.path).path, r"/ffmpeg/pano-views/([0-9a-f]{32})/abort")
        if task_id:
            self._cancel(task_id, "ffmpeg_pano_view")
            return
        task_id = _match(urlsplit(self.path).path, r"/minimax-h3/fl2va/clips/([0-9a-f]{32})/abort")
        if task_id:
            self._cancel(task_id, "h3_fl2va")
            return
        task_id = _match(
            urlsplit(self.path).path,
            r"/seedvr2/7b-sharp-fp8/upscales/([0-9a-f]{32})/abort",
        )
        if task_id:
            self._cancel(task_id, "seedvr2_7b_sharp_fp8")
            return
        task_id = _match(
            urlsplit(self.path).path,
            r"/ffmpeg/final-assemblies/([0-9a-f]{32})/abort",
        )
        if task_id:
            self._cancel(task_id, "ffmpeg_final_assembly")
            return
        task_id = _match(
            urlsplit(self.path).path,
            r"/ffmpeg/animatics/([0-9a-f]{32})/abort",
        )
        if task_id:
            self._cancel(task_id, "ffmpeg_animatic")
            return
        task_id = _match(
            urlsplit(self.path).path,
            r"/demucs/audio-separations/([0-9a-f]{32})/abort",
        )
        if task_id:
            self._cancel(task_id, "demucs_audio_separation")
            return
        task_id = _match(
            urlsplit(self.path).path,
            r"/ffmpeg/audio-remixes/([0-9a-f]{32})/abort",
        )
        if task_id:
            self._cancel(task_id, "ffmpeg_audio_remix")
            return
        task_id = _match(
            urlsplit(self.path).path,
            r"/stable-audio-3/generations/([0-9a-f]{32})/abort",
        )
        if task_id:
            self._cancel(task_id, "stable_audio_3")
            return
        self._json(404, {"message": "接口不存在。"})

    def do_PATCH(self) -> None:  # noqa: N802
        if not self._authorize():
            return
        task_id = _match(urlsplit(self.path).path, r"/indextts2/speech/([0-9a-f]{32})")
        if task_id:
            try:
                payload = self._read_json()
                if not isinstance(payload, dict) or payload != {"cancel": True}:
                    raise RequestError('只接受 {"cancel": true}。')
                self._cancel(task_id, "indextts2")
            except RequestError as exc:
                self._json(422, {"message": str(exc)})
            return
        task_id = _match(urlsplit(self.path).path, r"/breeze-tts2/speech/([0-9a-f]{32})")
        if task_id:
            try:
                payload = self._read_json()
                if not isinstance(payload, dict) or payload != {"cancel": True}:
                    raise RequestError('只接受 {"cancel": true}。')
                self._cancel(task_id, "breeze_tts_2")
            except RequestError as exc:
                self._json(422, {"message": str(exc)})
            return
        self._json(404, {"message": "接口不存在。"})

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._authorize():
            return
        path = urlsplit(self.path).path
        controller_session_id = _match(path, r"/control/controller-leases/([0-9a-f]{32})")
        if controller_session_id:
            controller = self.server.controller_lease
            if controller is None:
                self._json(404, {"message": "接口不存在。"})
                return
            completed = controller.release(controller_session_id)
            if completed is None:
                self._json(409, {"message": "Mac Core 租约不存在或已经失效。"})
                return
            self._json(202, {"state": "releasing"})
            return
        routes = (
            (r"/mock/tickets/([0-9a-f]{32})", "mock"),
            (r"/minimax-h3/ref2va/renders/([0-9a-f]{32})", "h3_ref2va"),
        )
        for pattern, kind in routes:
            task_id = _match(path, pattern)
            if task_id:
                self._cancel(task_id, kind)
                return
        self._json(404, {"message": "接口不存在。"})

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorize():
            return
        path = urlsplit(self.path).path
        routes = (
            (r"/mock/tickets/([0-9a-f]{32})", "mock", self._mock_status),
            (
                r"/codex/image-generations/([0-9a-f]{32})",
                "codex_image_generate",
                self._codex_status,
            ),
            (
                r"/codex/image-edits/([0-9a-f]{32})",
                "codex_image_edit",
                self._codex_status,
            ),
            (
                r"/agy/image-generations/([0-9a-f]{32})",
                "agy_image_generate",
                self._codex_status,
            ),
            (
                r"/agy/image-edits/([0-9a-f]{32})",
                "agy_image_edit",
                self._codex_status,
            ),
            (
                r"/ffmpeg/video-frames/([0-9a-f]{32})",
                "ffmpeg_video_frame",
                self._video_frame_status,
            ),
            (
                r"/ffmpeg/pano-views/([0-9a-f]{32})",
                "ffmpeg_pano_view",
                self._pano_view_status,
            ),
            (r"/minimax-h3/fl2va/clips/([0-9a-f]{32})", "h3_fl2va", self._fl2va_status),
            (r"/minimax-h3/ref2va/renders/([0-9a-f]{32})", "h3_ref2va", self._ref2va_status),
            (r"/indextts2/speech/([0-9a-f]{32})", "indextts2", self._tts_status),
            (r"/breeze-tts2/speech/([0-9a-f]{32})", "breeze_tts_2", self._tts_status),
            (
                r"/seedvr2/7b-sharp-fp8/upscales/([0-9a-f]{32})",
                "seedvr2_7b_sharp_fp8",
                self._fl2va_status,
            ),
            (
                r"/ffmpeg/final-assemblies/([0-9a-f]{32})",
                "ffmpeg_final_assembly",
                self._final_assembly_status,
            ),
            (
                r"/ffmpeg/animatics/([0-9a-f]{32})",
                "ffmpeg_animatic",
                self._animatic_status,
            ),
            (
                r"/demucs/audio-separations/([0-9a-f]{32})",
                "demucs_audio_separation",
                self._audio_separation_status,
            ),
            (
                r"/ffmpeg/audio-remixes/([0-9a-f]{32})",
                "ffmpeg_audio_remix",
                self._audio_remix_status,
            ),
            (
                r"/stable-audio-3/generations/([0-9a-f]{32})",
                "stable_audio_3",
                self._stable_audio_status,
            ),
            (
                r"/qwen-image/renders/([0-9a-f]{32})",
                "qwen_image",
                self._qwen_image_status,
            ),
        )
        for pattern, kind, formatter in routes:
            task_id = _match(path, pattern)
            if task_id:
                record = self._record(task_id, kind)
                if record:
                    self._json(200, formatter(record))
                return

        artifact_routes = (
            (r"/mock/outputs/([0-9a-f]{32})", "mock"),
            (
                r"/codex/image-generations/([0-9a-f]{32})/content/([0-9a-f]{32})",
                "codex_image_generate",
            ),
            (
                r"/codex/image-edits/([0-9a-f]{32})/content/([0-9a-f]{32})",
                "codex_image_edit",
            ),
            (
                r"/agy/image-generations/([0-9a-f]{32})/content/([0-9a-f]{32})",
                "agy_image_generate",
            ),
            (
                r"/agy/image-edits/([0-9a-f]{32})/content/([0-9a-f]{32})",
                "agy_image_edit",
            ),
            (r"/minimax-h3/fl2va/clips/([0-9a-f]{32})/movie/([0-9a-f]{32})", "h3_fl2va"),
            (
                r"/minimax-h3/ref2va/renders/([0-9a-f]{32})/video/([0-9a-f]{32})",
                "h3_ref2va",
            ),
            (r"/indextts2/speech/([0-9a-f]{32})/audio/([0-9a-f]{32})", "indextts2"),
            (r"/breeze-tts2/speech/([0-9a-f]{32})/audio/([0-9a-f]{32})", "breeze_tts_2"),
            (
                r"/seedvr2/7b-sharp-fp8/upscales/([0-9a-f]{32})/movie/([0-9a-f]{32})",
                "seedvr2_7b_sharp_fp8",
            ),
            (
                r"/ffmpeg/final-assemblies/([0-9a-f]{32})/movie/([0-9a-f]{32})",
                "ffmpeg_final_assembly",
            ),
            (r"/ffmpeg/video-frames/([0-9a-f]{32})/movie/([0-9a-f]{32})", "ffmpeg_video_frame"),
            (r"/ffmpeg/pano-views/([0-9a-f]{32})/image/([0-9a-f]{32})", "ffmpeg_pano_view"),
            (
                r"/ffmpeg/animatics/([0-9a-f]{32})/movie/([0-9a-f]{32})",
                "ffmpeg_animatic",
            ),
            (
                r"/demucs/audio-separations/([0-9a-f]{32})/audio/([0-9a-f]{32})",
                "demucs_audio_separation",
            ),
            (
                r"/ffmpeg/audio-remixes/([0-9a-f]{32})/movie/([0-9a-f]{32})",
                "ffmpeg_audio_remix",
            ),
            (
                r"/stable-audio-3/generations/([0-9a-f]{32})/audio/([0-9a-f]{32})",
                "stable_audio_3",
            ),
            (r"/qwen-image/renders/([0-9a-f]{32})/image/([0-9a-f]{32})", "qwen_image"),
        )
        for pattern, kind in artifact_routes:
            match = re.fullmatch(pattern, path)
            if match:
                ids = match.groups()
                if len(ids) == 2 and ids[0] != ids[1]:
                    self._json(404, {"message": "Artifact 不属于该调用。"})
                    return
                self._artifact(ids[0], kind)
                return
        self._json(404, {"message": "接口不存在。"})

    def log_message(self, format: str, *args: object) -> None:
        # 不记录请求 body、token 或输入素材。
        super().log_message(format, *args)

    def _record(self, task_id: str, kind: str) -> TaskRecord | None:
        if kind not in self.server.enabled_services:
            self._json(404, {"message": "接口不存在。"})
            return None
        record = self.server.store.get(task_id)
        if record is None or record.kind != kind:
            self._json(404, {"message": "调用不存在。"})
            return None
        message = self.server.manager.queue_message(record)
        if message is not None:
            # 只用于本次状态响应，不写回 TaskStore。
            record = dataclasses.replace(record, message=message)
        return record

    def _authorize(self) -> bool:
        expected = self.server.auth_token
        if expected is None:
            return True
        supplied = self.headers.get("Authorization", "")
        valid = hmac.compare_digest(supplied, "Bearer " + expected)
        if not valid:
            self._json(401, {"message": "认证失败。"})
        return valid

    def _require_enabled(self, kind: str) -> None:
        if kind not in self.server.enabled_services:
            raise DisabledServiceError

    def _cancel(self, task_id: str, kind: str) -> None:
        record = self.server.store.get(task_id)
        if kind not in self.server.enabled_services or record is None or record.kind != kind:
            self._json(404, {"message": "调用不存在。"})
            return
        record = self.server.manager.cancel(task_id)
        assert record is not None
        if record.state in {"succeeded", "failed", "cancelled"}:
            self._json(409, {"message": "调用已处于终态。"})
        else:
            self._json(202, {"message": "取消请求已记录。"})

    def _artifact(self, task_id: str, kind: str) -> None:
        record = self.server.store.get(task_id)
        if (
            kind not in self.server.enabled_services
            or record is None
            or record.kind != kind
            or record.state != "succeeded"
        ):
            self._json(404, {"message": "Artifact 不可用。"})
            return
        path = self.server.store.artifact_path(record)
        if path is None:
            self._json(410, {"message": "Artifact 文件缺失。"})
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", record.artifact_media_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _read_json(self) -> Any:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise RequestError("Content-Type 必须是 application/json。")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise RequestError("缺少 Content-Length。")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise RequestError("Content-Length 不合法。") from exc
        if not 0 < length <= MAX_REQUEST_BYTES:
            raise RequestError("请求 body 大小不合法。")
        try:
            return json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestError("请求 body 不是合法 UTF-8 JSON。") from exc

    def _controller_session_id(self) -> str:
        payload = self._read_json()
        if (
            not isinstance(payload, dict)
            or set(payload) != {"session_id"}
            or not isinstance(payload["session_id"], str)
        ):
            raise RequestError("只接受字符串字段 session_id。")
        session_id = payload["session_id"]
        if re.fullmatch(r"[0-9a-f]{32}", session_id) is None:
            raise RequestError("session_id 必须是 32 位小写十六进制字符串。")
        return session_id

    def _json(self, status: int, value: dict[str, Any]) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    @staticmethod
    def _mock_status(record: TaskRecord) -> dict[str, Any]:
        phase = {
            "queued": "waiting",
            "running": "drawing",
            "succeeded": "ready",
            "failed": "broken",
            "cancelled": "aborted",
        }[record.state]
        result: dict[str, Any] = {
            "phase": phase,
            "percent": round(record.progress * 100),
            "note": record.message,
        }
        if record.state == "succeeded":
            result.update(
                output_key=record.task_id, bytes=record.artifact_size, sha256=record.artifact_sha256
            )
        elif record.state == "failed":
            result["problem"] = record.error_code
        return result

    @staticmethod
    def _codex_status(record: TaskRecord) -> dict[str, Any]:
        state = {
            "queued": "accepted",
            "running": "working",
            "succeeded": "complete",
            "failed": "failed",
            "cancelled": "cancelled",
        }[record.state]
        result: dict[str, Any] = {
            "state": state,
            "completion": record.progress,
            "detail": record.message,
        }
        if record.state == "succeeded":
            result["image"] = {
                "id": record.task_id,
                "content_type": record.artifact_media_type,
                "size": record.artifact_size,
                "sha256": record.artifact_sha256,
            }
        elif record.state == "failed":
            result["failure"] = record.error_code
        return result

    @staticmethod
    def _fl2va_status(record: TaskRecord) -> dict[str, Any]:
        stage = {
            "queued": "queued",
            "running": "generating",
            "succeeded": "done",
            "failed": "error",
            "cancelled": "stopped",
        }[record.state]
        result: dict[str, Any] = {
            "stage": stage,
            "ratio": record.progress,
            "description": record.message,
        }
        if record.state == "succeeded":
            result["movie"] = {
                "key": record.task_id,
                "mime": record.artifact_media_type,
                "length": record.artifact_size,
                "digest": record.artifact_sha256,
                "duration_seconds": _video_duration_seconds(record),
            }
        elif record.state == "failed":
            result.update(error_tag=record.error_code, can_retry=record.retryable)
        return result

    @staticmethod
    def _ref2va_status(record: TaskRecord) -> dict[str, Any]:
        status = {
            "queued": "pending",
            "running": "processing",
            "succeeded": "rendered",
            "failed": "failed",
            "cancelled": "cancelled",
        }[record.state]
        result: dict[str, Any] = {
            "status": status,
            "progress_0_100": round(record.progress * 100, 2),
            "message": record.message,
        }
        if record.state == "succeeded":
            result["result"] = {
                "artifact_id": record.task_id,
                "media_type": record.artifact_media_type,
                "byte_count": record.artifact_size,
                "sha256": record.artifact_sha256,
                "duration_seconds": _video_duration_seconds(record),
            }
        elif record.state == "failed":
            result.update(error=record.error_code, retry_suggested=record.retryable)
        return result

    @staticmethod
    def _tts_status(record: TaskRecord) -> dict[str, Any]:
        condition = {
            "queued": "waiting_for_gpu",
            "running": "speaking",
            "succeeded": "available",
            "failed": "fault",
            "cancelled": "cancelled",
        }[record.state]
        result: dict[str, Any] = {
            "condition": condition,
            "progress_fraction": record.progress,
            "status_text": record.message,
        }
        if record.state == "succeeded":
            result["audio_file"] = {
                "name": record.task_id,
                "format": record.artifact_media_type,
                "bytes": record.artifact_size,
                "hash": record.artifact_sha256,
            }
        elif record.state == "failed":
            result["reason"] = record.error_code
        return result

    @staticmethod
    def _final_assembly_status(record: TaskRecord) -> dict[str, Any]:
        stage = {
            "queued": "queued",
            "running": "assembling",
            "succeeded": "done",
            "failed": "failed",
            "cancelled": "cancelled",
        }[record.state]
        result: dict[str, Any] = {
            "stage": stage,
            "progress": record.progress,
            "message": record.message,
        }
        if record.state == "succeeded":
            result["movie"] = {
                "id": record.task_id,
                "mime": record.artifact_media_type,
                "bytes": record.artifact_size,
                "sha256": record.artifact_sha256,
                "duration_seconds": _video_duration_seconds(record),
            }
        elif record.state == "failed":
            result.update(error_code=record.error_code, retryable=record.retryable)
        return result

    @staticmethod
    def _pano_view_status(record: TaskRecord) -> dict[str, Any]:
        result = {
            "stage": {
                "queued": "queued",
                "running": "rendering",
                "succeeded": "done",
                "failed": "failed",
                "cancelled": "cancelled",
            }[record.state],
            "progress": record.progress,
            "message": record.message,
        }
        if record.state == "succeeded":
            result["image"] = {
                "id": record.task_id,
                "mime": record.artifact_media_type,
                "bytes": record.artifact_size,
                "sha256": record.artifact_sha256,
            }
        elif record.state == "failed":
            result.update(error_code=record.error_code, retryable=record.retryable)
        return result

    @staticmethod
    def _video_frame_status(record):
        result = {
            "stage": {
                "queued": "queued",
                "running": "assembling",
                "succeeded": "done",
                "failed": "failed",
                "cancelled": "cancelled",
            }[record.state],
            "progress": record.progress,
            "message": record.message,
        }
        if record.state == "succeeded":
            result["movie"] = {
                "id": record.task_id,
                "mime": record.artifact_media_type,
                "bytes": record.artifact_size,
                "sha256": record.artifact_sha256,
            }
        elif record.state == "failed":
            result.update(error_code=record.error_code, retryable=record.retryable)
        return result

    @staticmethod
    def _animatic_status(record: TaskRecord) -> dict[str, Any]:
        stage = {
            "queued": "queued",
            "running": "assembling",
            "succeeded": "done",
            "failed": "failed",
            "cancelled": "cancelled",
        }[record.state]
        result: dict[str, Any] = {
            "stage": stage,
            "progress": record.progress,
            "message": record.message,
        }
        if record.state == "succeeded":
            result["movie"] = {
                "id": record.task_id,
                "mime": record.artifact_media_type,
                "bytes": record.artifact_size,
                "sha256": record.artifact_sha256,
                "duration_seconds": _video_duration_seconds(record),
            }
        elif record.state == "failed":
            result.update(error_code=record.error_code, retryable=record.retryable)
        return result

    @staticmethod
    def _audio_separation_status(record: TaskRecord) -> dict[str, Any]:
        stage = {
            "queued": "queued",
            "running": "separating",
            "succeeded": "done",
            "failed": "failed",
            "cancelled": "cancelled",
        }[record.state]
        result: dict[str, Any] = {
            "stage": stage,
            "progress": record.progress,
            "message": record.message,
        }
        if record.state == "succeeded":
            result["audio"] = {
                "id": record.task_id,
                "mime": record.artifact_media_type,
                "bytes": record.artifact_size,
                "sha256": record.artifact_sha256,
            }
        elif record.state == "failed":
            result.update(error_code=record.error_code, retryable=record.retryable)
        return result

    @staticmethod
    def _stable_audio_status(record: TaskRecord) -> dict[str, Any]:
        stage = {
            "queued": "queued",
            "running": "generating",
            "succeeded": "done",
            "failed": "failed",
            "cancelled": "cancelled",
        }[record.state]
        result: dict[str, Any] = {
            "stage": stage,
            "progress": record.progress,
            "message": record.message,
        }
        if record.state == "succeeded":
            result["audio"] = {
                "id": record.task_id,
                "mime": record.artifact_media_type,
                "bytes": record.artifact_size,
                "sha256": record.artifact_sha256,
                "duration_seconds": _wav_duration_seconds(record),
            }
        elif record.state == "failed":
            result.update(error_code=record.error_code, retryable=record.retryable)
        return result

    @staticmethod
    def _qwen_image_status(record: TaskRecord) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": record.state,
            "progress": record.progress,
            "message": record.message,
        }
        if record.state == "succeeded":
            result["image"] = {
                "id": record.task_id,
                "media_type": record.artifact_media_type,
                "bytes": record.artifact_size,
                "sha256": record.artifact_sha256,
            }
        elif record.state == "failed":
            result.update(error_code=record.error_code, retryable=record.retryable)
        return result

    @staticmethod
    def _audio_remix_status(record: TaskRecord) -> dict[str, Any]:
        result = ModelApiHandler._final_assembly_status(record)
        if result["stage"] == "assembling":
            result["stage"] = "remixing"
        return result


def _wav_duration_seconds(record: TaskRecord) -> float:
    import wave

    if record.artifact_name is None or record.artifact_media_type != "audio/wav":
        raise RuntimeError("成功的文生音频任务缺少 WAV Artifact。")
    root = Path(record.task_dir).resolve(strict=True)
    artifact = (root / record.artifact_name).resolve(strict=True)
    with wave.open(str(artifact), "rb") as handle:
        rate = handle.getframerate()
        frames = handle.getnframes()
    if rate <= 0 or frames <= 0:
        raise RuntimeError("文生音频 WAV 没有可读取的时长。")
    return frames / rate


def _match(path: str, pattern: str) -> str | None:
    match = re.fullmatch(pattern, unquote(path))
    return match.group(1) if match else None


def _video_duration_seconds(record: TaskRecord) -> float:
    if record.artifact_name is None or record.artifact_media_type != "video/mp4":
        raise RuntimeError("成功的视频任务缺少 MP4 Artifact。")
    root = Path(record.task_dir).resolve(strict=True)
    artifact = (root / record.artifact_name).resolve(strict=True)
    artifact.relative_to(root)
    result = subprocess.run(
        [
            os.environ.get("STORYRAIL_FFPROBE", "ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(artifact),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    duration = float(result.stdout.strip())
    if duration <= 0:
        raise RuntimeError("视频 Artifact 的实际时长无效。")
    return duration


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="StoryRail 私有默认模型 HTTP 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument(
        "--services",
        required=True,
        help=(
            "逗号分隔的显式服务集合：mock,codex_image_generate,codex_image_edit,"
            "agy_image_generate,agy_image_edit,h3_fl2va,h3_ref2va,"
            "seedvr2_7b_sharp_fp8,ffmpeg_final_assembly,ffmpeg_animatic,ffmpeg_video_frame,"
            "ffmpeg_pano_view,"
            "demucs_audio_separation,ffmpeg_audio_remix,breeze_tts_2,indextts2,stable_audio_3,"
            "qwen_image"
        ),
    )
    parser.add_argument("--resource-name")
    parser.add_argument(
        "--max-concurrent-tasks",
        type=int,
        help="仅供无驻留状态的模型调用使用；Windows 常驻 runtime 必须保持为 1。",
    )
    parser.add_argument(
        "--lane",
        action="append",
        metavar="NAME:MAX:svc1,svc2",
        help=(
            "可重复的进程内调度 lane，格式 NAME:MAX:svc1,svc2；"
            "给出后所有 lane 的服务并集必须等于 --services，"
            "且不能再给 --resource-name 或 --max-concurrent-tasks。"
        ),
    )
    parser.add_argument(
        "--auth-token-env",
        help="从指定环境变量读取 Bearer Token；不允许在命令行直接传 Token。",
    )
    parser.add_argument(
        "--controller-lease-timeout-seconds",
        type=float,
        help="启用私有 Mac Core 活性租约，并在超时后取消任务、释放驻留 GPU runtime。",
    )
    return parser


def _parse_lanes(values: list[str], services: set[str]) -> tuple[LaneSpec, ...]:
    """解析 `--lane NAME:MAX:svc1,svc2`；任何布局错误都以中文说明退出。"""

    lanes: list[LaneSpec] = []
    claimed: set[str] = set()
    for value in values:
        parts = value.split(":")
        if len(parts) != 3 or not all(parts):
            raise SystemExit(f"--lane 格式必须是 NAME:MAX:svc1,svc2：{value}")
        name, raw_concurrency, raw_services = parts
        try:
            concurrency = int(raw_concurrency)
        except ValueError as exc:
            raise SystemExit(f"--lane 的并发数必须是整数：{value}") from exc
        lane_services = frozenset(item.strip() for item in raw_services.split(",") if item.strip())
        unknown = lane_services - services
        if unknown:
            raise SystemExit(
                "--lane 包含未在 --services 中启用的服务：" + "、".join(sorted(unknown))
            )
        try:
            lane = LaneSpec(
                name=name,
                services=lane_services,
                max_concurrent_tasks=concurrency,
            )
        except ValueError as exc:
            raise SystemExit(f"--lane 定义不合法：{exc}") from exc
        lanes.append(lane)
        claimed |= lane_services
    missing = services - claimed
    if missing:
        raise SystemExit(
            "--lane 的服务并集必须等于 --services，缺少：" + "、".join(sorted(missing))
        )
    return tuple(lanes)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    allowed = {
        "mock",
        "codex_image_generate",
        "codex_image_edit",
        "agy_image_generate",
        "agy_image_edit",
        "h3_fl2va",
        "h3_ref2va",
        "breeze_tts_2",
        "indextts2",
        "seedvr2_7b_sharp_fp8",
        "ffmpeg_final_assembly",
        "ffmpeg_animatic",
        "ffmpeg_video_frame",
        "ffmpeg_pano_view",
        "demucs_audio_separation",
        "ffmpeg_audio_remix",
        "stable_audio_3",
        "qwen_image",
    }
    services = {item.strip() for item in args.services.split(",") if item.strip()}
    if not services or not services <= allowed:
        raise SystemExit("--services 包含未知服务或为空。")
    if args.lane:
        if args.max_concurrent_tasks is not None or args.resource_name is not None:
            raise SystemExit("--lane 不能与 --max-concurrent-tasks 或 --resource-name 同时使用。")
        lanes: tuple[LaneSpec, ...] | None = _parse_lanes(args.lane, services)
    else:
        lanes = None
    resource_name = args.resource_name if args.resource_name is not None else "exclusive_gpu"
    max_concurrent_tasks = args.max_concurrent_tasks if args.max_concurrent_tasks is not None else 1
    auth_token = None
    if args.auth_token_env:
        auth_token = os.environ.get(args.auth_token_env)
        if auth_token is None or not 32 <= len(auth_token) <= 512:
            raise SystemExit("Bearer Token 环境变量缺失或长度不合法。")
    if args.controller_lease_timeout_seconds is not None:
        if not 5 <= args.controller_lease_timeout_seconds <= 300:
            raise SystemExit("Controller 租约超时必须在 5 到 300 秒之间。")
        if auth_token is None:
            raise SystemExit("Controller 租约只能在启用 Bearer Token 时使用。")
    if not 1 <= max_concurrent_tasks <= 8:
        raise SystemExit("--max-concurrent-tasks 必须在 1 到 8 之间。")
    server = ModelApiServer(
        (args.host, args.port),
        args.state_root,
        enabled_services=services,
        resource_name=resource_name,
        auth_token=auth_token,
        controller_lease_timeout_seconds=args.controller_lease_timeout_seconds,
        max_concurrent_tasks=max_concurrent_tasks,
        lanes=lanes,
    )
    pid_file = args.state_root.resolve() / "service.pid"
    temporary_pid = pid_file.with_suffix(".pid.tmp")
    temporary_pid.write_text(str(os.getpid()), encoding="ascii")
    os.replace(temporary_pid, pid_file)
    server.manager.start()
    if server.controller_lease is not None:
        server.controller_lease.start()

    def stop(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        if server.controller_lease is not None:
            server.controller_lease.shutdown()
        server.manager.shutdown()
        server.server_close()
        try:
            if pid_file.read_text(encoding="ascii").strip() == str(os.getpid()):
                pid_file.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
