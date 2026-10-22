"""pytest 公共工厂：oracle 套件与各领域测试共享的搭建设施。

新测试一律使用这里的 fixture；修改旧测试文件时顺手迁移到这些工厂。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError

import pytest
from provider_factory import make_service, provider_registry
from structured_director_fixtures import RecordingProvider
from structured_director_fixtures import wav_bytes as _wav_bytes
from video_recipes import video_wire_dict

from core.model_providers.boundary import (
    ArtifactDescriptor,
    GenerationObservation,
    GenerationPhase,
    ProviderHandle,
)
from core.model_providers.registry import ProviderRegistry
from core.project_settings import ProjectAspectRatio
from core.project_workspaces import ProjectWorkspaceStore
from core.structured_director import StructuredDirectorService, StructuredDirectorStore
from core.structured_director.models import NarrationLanguage
from server.api import StoryRailApi
from server.http import StoryRailHttpServer

# 固定测试 canary，绝不是部署凭据。
HUMAN_TOKEN = "fixture_human_" + "b" * 32
AGENT_TOKEN = "fixture_agent_" + "a" * 32

__all__ = ["make_service", "provider_registry"]


def _png_bytes() -> bytes:
    """合成 PNG 魔数 + 确定性填充；足以通过媒体类型嗅探，不是真实图像。"""
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def mp4_bytes(marker: bytes = b"fixture") -> bytes:
    """合成 ftyp mp4 头 + 确定性填充。"""
    return b"\x00\x00\x00\x18ftypmp42" + marker


class SyntheticProvider(RecordingProvider):
    """可编排 phase 序列的确定性合成 Provider。

    - ``phases`` 给出 observe 应答序列（如 ``[RUNNING, SUCCEEDED]``）；序列最后一个
      phase 会重复应答，保证多轮提交都有确定性观察。
    - 每个 SUCCEEDED 应答都返回构造时给定的确定性内容字节与描述符。
    """

    def __init__(
        self,
        *,
        media_type: str,
        content: bytes,
        duration_seconds: float | None = None,
        phases: tuple[GenerationPhase, ...] | list[GenerationPhase] | None = None,
        contents: tuple[bytes, ...] | list[bytes] | None = None,
        plugin_id: str = "test.voice",
    ) -> None:
        super().__init__(media_type=media_type, content=content, duration_seconds=duration_seconds)
        # 每个槽位实例必须有唯一 plugin_id：Core 的 _provider_for 按
        # (plugin_id, plugin_version) 在 fl2va/ref2va 候选中找回观察实例。
        self.plugin_id = plugin_id
        if phases:
            self.observations = list(phases)
        # contents 给出时按提交顺序循环取用，让多次提交产出可区分的确定性字节。
        self._contents = list(contents) if contents else None
        self._submission_count = 0
        self._content_by_handle: dict[str, bytes] = {}

    def _next_content(self) -> bytes:
        if not self._contents:
            return self.content
        value = self._contents[self._submission_count % len(self._contents)]
        self._submission_count += 1
        return value

    def _next_handle_id(self) -> str:
        self._submission_count_for_handle = getattr(self, "_submission_count_for_handle", 0) + 1
        return f"external-{self._submission_count_for_handle}"

    def _record(self, handle: ProviderHandle) -> ProviderHandle:
        self._content_by_handle[handle.external_id] = self._next_content()
        return handle

    def submit(self, request: object) -> ProviderHandle:
        self.requests.append(request)
        return self._record(
            ProviderHandle(self.plugin_id, self.plugin_version, self._next_handle_id())
        )

    def submit_generate(self, request: object) -> ProviderHandle:
        self.requests.append(request)
        return self._record(
            ProviderHandle(self.generate_plugin_id, self.plugin_version, self._next_handle_id())
        )

    def submit_edit(self, request: object) -> ProviderHandle:
        self.requests.append(request)
        return self._record(
            ProviderHandle(self.edit_plugin_id, self.plugin_version, self._next_handle_id())
        )

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        phase = self.observations.pop(0) if len(self.observations) > 1 else self.observations[0]
        content = self._content_by_handle.get(handle.external_id, self.content)
        if phase is GenerationPhase.SUCCEEDED:
            descriptor = ArtifactDescriptor(
                "artifact-1",
                self.media_type,
                len(content),
                hashlib.sha256(content).hexdigest(),
                self.duration_seconds,
            )
            return GenerationObservation(phase, 1.0, "完成", descriptor)
        return GenerationObservation(phase, 0.5, "生成中")

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        del artifact_id
        return self._content_by_handle.get(handle.external_id, self.content)


@dataclass
class ProviderSet:
    """按 Core Service 构造槽位分组的默认合成 Provider。"""

    image: SyntheticProvider
    speech: SyntheticProvider
    fl2va: SyntheticProvider
    ref2va: SyntheticProvider
    final_assembly: SyntheticProvider
    animatic: SyntheticProvider
    upscale: SyntheticProvider

    def as_registry(self) -> ProviderRegistry:
        return provider_registry(
            image_provider=self.image,
            voice_provider=self.speech,
            speech_provider=self.speech,
            fl2va_provider=self.fl2va,
            ref2va_provider=self.ref2va,
            final_assembly_provider=self.final_assembly,
            animatic_provider=self.animatic,
            upscale_provider=self.upscale,
        )


def default_providers() -> ProviderSet:
    return ProviderSet(
        image=SyntheticProvider(
            media_type="image/png", content=_png_bytes(), plugin_id="test.image"
        ),
        speech=SyntheticProvider(
            media_type="audio/wav",
            content=_wav_bytes(duration_seconds=1.0),
            plugin_id="test.speech",
        ),
        fl2va=SyntheticProvider(
            media_type="video/mp4",
            content=mp4_bytes(b"fl2va"),
            duration_seconds=8,
            plugin_id="test.fl2va",
        ),
        ref2va=SyntheticProvider(
            media_type="video/mp4",
            content=mp4_bytes(b"ref2va"),
            duration_seconds=8,
            plugin_id="test.ref2va",
        ),
        final_assembly=SyntheticProvider(
            media_type="video/mp4",
            content=mp4_bytes(b"final"),
            duration_seconds=22,
            plugin_id="test.final",
        ),
        animatic=SyntheticProvider(
            media_type="video/mp4",
            content=mp4_bytes(b"animatic"),
            duration_seconds=8,
            plugin_id="test.animatic",
        ),
        upscale=SyntheticProvider(
            media_type="video/mp4",
            content=mp4_bytes(b"upscale"),
            duration_seconds=8,
            plugin_id="test.upscale",
        ),
    )


@pytest.fixture
def stories_root(tmp_path: Path) -> Path:
    """每测试独立的受控 .stories 根目录。"""
    root = tmp_path / ".stories"
    root.mkdir()
    return root


@pytest.fixture
def wav_bytes() -> bytes:
    """1 秒单声道 8kHz 静音 WAV。"""
    return _wav_bytes(duration_seconds=1.0)


@pytest.fixture
def png_bytes() -> bytes:
    return _png_bytes()


@pytest.fixture
def synthetic_provider() -> type[SyntheticProvider]:
    """SyntheticProvider 类本身，调用方按槽位自行构造（可编排 phases）。"""
    return SyntheticProvider


@pytest.fixture
def store_factory(stories_root: Path):
    """StructuredDirectorStore + create_project 一步。

    返回工厂：``store_factory(project_id="a"*32, title=..., aspect_ratio=..., plan=...)``。
    """

    def build(
        project_id: str = "a" * 32,
        *,
        title: str = "测试项目",
        aspect_ratio: ProjectAspectRatio = ProjectAspectRatio.LANDSCAPE,
        plan: str = "# 完整导演方案\n\n小满带着红色行李箱等候末班车。",
    ) -> StructuredDirectorStore:
        project_dir = stories_root / f"{title}-{project_id}"
        project_dir.mkdir()
        store = StructuredDirectorStore(project_dir, project_id)
        store.create_project(
            title=title,
            aspect_ratio=aspect_ratio,
            director_plan_markdown=plan,
            narration_languages=tuple(NarrationLanguage),
        )
        return store

    return build


@pytest.fixture
def playground_factory(tmp_path):
    """PlaygroundStore + ProviderRegistry 装配的 PlaygroundService。

    槽位名同 ``tests/provider_factory.py::PROVIDER_SLOT_CAPABILITIES``。
    """
    from core.playground.service import PlaygroundService
    from core.playground.store import PlaygroundStore

    def make(**providers) -> PlaygroundService:
        store = PlaygroundStore(tmp_path / ".stories" / ".playground")
        return PlaygroundService(store, provider_registry(**providers))

    (tmp_path / ".stories").mkdir(exist_ok=True)
    return make


@pytest.fixture
def service_factory(store_factory):
    """Store + 默认合成 Provider 装配的 Service。

    返回工厂：``service_factory(providers=None, **store_kwargs)``；
    ``providers`` 可传 ProviderSet 或自定义 mapping 覆盖默认槽位。
    """
    from core.structured_director import StructuredDirectorService

    def build(providers: ProviderSet | None = None, **store_kwargs) -> StructuredDirectorService:
        store = store_factory(**store_kwargs)
        selected = providers or default_providers()
        registry = (
            selected.as_registry()
            if isinstance(selected, ProviderSet)
            else provider_registry(**dict(providers))
        )
        return StructuredDirectorService(store, registry=registry)

    return build


def _policy_bytes(project_ids: list[str]) -> bytes:
    return json.dumps(
        {
            "version": 2,
            "external_mutations": True,
            "callers": [
                {
                    "id": "oracle-human",
                    "grants": [],
                    "role": "human",
                    "project_ids": project_ids,
                    "capabilities": ["project.read", "human.write", "workspace.manage"],
                    "expires_at": 4102444800,
                    "token_sha256": hashlib.sha256(HUMAN_TOKEN.encode()).hexdigest(),
                },
                {
                    "id": "oracle-agent",
                    "grants": [],
                    "role": "agent",
                    "project_ids": project_ids,
                    "capabilities": [
                        "project.read",
                        "project.mutate",
                        "project.propose",
                        "project.execute",
                    ],
                    "expires_at": 4102444800,
                    "token_sha256": hashlib.sha256(AGENT_TOKEN.encode()).hexdigest(),
                },
            ],
        }
    ).encode()


class OracleHttpServer:
    """真实 loopback HTTP  harness：StoryRailApi + 访问策略 + 线程内事件循环。

    - ``request(...)`` 走真实 HTTP；``role`` 决定携带 human/agent bearer。
    - ``authorize_project(project_id)`` 把项目写进访问策略（服务每请求重读策略文件）。
    - provider 实例在 service 重建（模拟重启）时保持共享，便于编排确定性 phase。
    """

    def __init__(self, root: Path, policy_path: Path) -> None:
        self.stories_root = root
        self.policy_path = policy_path
        self.policy_path.write_bytes(_policy_bytes([]))
        self.policy_path.chmod(0o600)
        self.workspaces = ProjectWorkspaceStore(root)
        self.providers = default_providers()
        self._authorized: list[str] = []
        self.event_loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self.event_loop.run_forever, daemon=True)
        api = StoryRailApi(
            self.workspaces,
            self._service_factory,
            playground_service=self._playground_service(),
        )
        self._server = StoryRailHttpServer(
            ("127.0.0.1", 0), api, self.event_loop, access_policy_file=policy_path
        )
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> OracleHttpServer:
        self._loop_thread.start()
        self._server_thread.start()
        host, port = self._server.server_address
        self.base_url = f"http://{host}:{port}"
        return self

    def _service_factory(self, project_id: str) -> StructuredDirectorService:
        store = self.workspaces.structured_director_store(project_id)
        return StructuredDirectorService(store, registry=self.providers.as_registry())

    def _playground_service(self):
        """与项目共用同一批 Provider 实例的 Playground 服务。"""
        from core.playground.service import PlaygroundService
        from core.playground.store import PlaygroundStore

        return PlaygroundService(
            PlaygroundStore(self.stories_root / ".playground"),
            self.providers.as_registry(),
        )

    def authorize_project(self, project_id: str) -> None:
        if project_id not in self._authorized:
            self._authorized.append(project_id)
        self.policy_path.write_bytes(_policy_bytes(list(self._authorized)))
        self.policy_path.chmod(0o600)

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        role: str | None = "human",
    ) -> tuple[int, Any]:
        """发真实 HTTP 请求；返回 (status, 解析后的 JSON 体)。"""
        token = {"human": HUMAN_TOKEN, "agent": AGENT_TOKEN}.get(role or "")
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        http_request = urlrequest.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
        )
        try:
            with urlrequest.urlopen(http_request, timeout=10) as response:
                return response.status, json.loads(response.read().decode())
        except HTTPError as exc:
            raw = exc.read().decode()
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, {"raw": raw}

    def upload(
        self,
        path: str,
        content: bytes,
        media_type: str,
        *,
        role: str | None = "human",
    ) -> tuple[int, Any]:
        """上传原始媒体字节（Content-Type 为媒体类型，path 可带查询串）。"""
        token = {"human": HUMAN_TOKEN, "agent": AGENT_TOKEN}.get(role or "")
        http_request = urlrequest.Request(
            f"{self.base_url}{path}",
            data=content,
            method="POST",
            headers={
                "Content-Type": media_type,
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
        )
        try:
            with urlrequest.urlopen(http_request, timeout=10) as response:
                return response.status, json.loads(response.read().decode())
        except HTTPError as exc:
            raw = exc.read().decode()
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, {"raw": raw}

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._server_thread.join(timeout=5)
        self.event_loop.call_soon_threadsafe(self.event_loop.stop)
        self._loop_thread.join(timeout=5)
        self.event_loop.close()

    def restart(self) -> None:
        """模拟进程死并重建：保留 stories_root/workspaces/providers/policy。

        停掉 server/loop 线程后整体重建 StoryRailApi 与其 service 缓存
        （新端口）；service 构造时运行 recover_interrupted_submissions。
        providers 实例共享，调用方可在重启前后调整 observations/失败开关。
        """
        self._server.shutdown()
        self._server.server_close()
        self._server_thread.join(timeout=5)
        self.event_loop.call_soon_threadsafe(self.event_loop.stop)
        self._loop_thread.join(timeout=5)
        self.event_loop.close()
        self.event_loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self.event_loop.run_forever, daemon=True)
        api = StoryRailApi(
            self.workspaces,
            self._service_factory,
            playground_service=self._playground_service(),
        )
        self._server = StoryRailHttpServer(
            ("127.0.0.1", 0), api, self.event_loop, access_policy_file=self.policy_path
        )
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._loop_thread.start()
        self._server_thread.start()
        host, port = self._server.server_address
        self.base_url = f"http://{host}:{port}"


@pytest.fixture
def http_server(stories_root: Path, tmp_path: Path) -> OracleHttpServer:
    """真实 loopback server（端口 0）；返回 base_url、双角色请求助手与清理。"""
    server = OracleHttpServer(stories_root, tmp_path / "access_policy.json").start()
    try:
        yield server
    finally:
        server.stop()


class JourneyStepError(RuntimeError):
    """旅程某一步收到非 2xx 响应；携带状态码与错误体便于定位。"""

    def __init__(self, step: str, status: int, body: Any) -> None:
        super().__init__(f"journey.{step} 收到 HTTP {status}: {body}")
        self.step, self.status, self.body = step, status, body


_DEFAULT_PLAN = "# 完整导演方案\n\n小满带着红色行李箱等候末班车。"


class Journey:
    """旅程驱动器（P1-T2 实现）：声明式把项目从创建推进到任意阶段。

    全部走真实 HTTP（经 ``OracleHttpServer``），本身零断言逻辑；
    每步返回响应 JSON，断言写在场景测试里。非 2xx 响应抛
    ``JourneyStepError`` 让驱动失败立即显形，不构成业务断言。
    """

    def __init__(self, server: OracleHttpServer, project_id: str | None = None) -> None:
        self._server = server
        self.project_id = project_id

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    @property
    def resource(self) -> str:
        return f"/api/projects/{self.project_id}/structured-director"

    def snapshot(self) -> dict:
        """GET 项目资源，返回当前 snapshot JSON。"""
        _, body = self._server.request("GET", self.resource, role="human")
        return body

    def document(self) -> dict:
        """直接读取 stories_root 下的权威 project.json（供断言）。"""
        directory = next(self._server.stories_root.glob(f"*-{self.project_id}"))
        return json.loads((directory / "project.json").read_text())

    def _revision(self) -> int:
        return self.snapshot()["revision"]

    def _command(
        self,
        name: str,
        arguments: dict | None = None,
        *,
        role: str,
        step: str | None = None,
    ) -> dict:
        """发 typed command；写命令自动带当前 revision，读命令不带（服务端回填）。"""
        body: dict[str, Any] = {
            "name": name,
            "idempotency_key": f"journey-{name}-{self._revision()}",
            "arguments": arguments or {},
        }
        if not name.endswith(".get_proposal"):
            body["expected_revision"] = self._revision()
        path = self.resource + ("/commands" if role == "human" else "/application/commands")
        status, response = self._server.request("POST", path, body, role=role)
        if status >= 400:
            raise JourneyStepError(step or name, status, response)
        return response

    def _post(self, step: str, path: str, body: dict) -> dict:
        """发 Web 相同入口的 POST；非 2xx 抛 JourneyStepError。"""
        status, response = self._server.request("POST", path, body, role="human")
        if status >= 400:
            raise JourneyStepError(step, status, response)
        return response

    def _put(self, step: str, path: str, body: dict) -> dict:
        status, response = self._server.request("PUT", path, body, role="human")
        if status >= 400:
            raise JourneyStepError(step, status, response)
        return response

    def wait_generations(
        self,
        *,
        kind: str | None = None,
        target_ids: set[str] | None = None,
        phases: set[str] = frozenset({"succeeded"}),
        timeout: float = 10.0,
        interval: float = 0.05,
    ) -> dict:
        """轮询 snapshot 并主动刷新观察，直到匹配 Generation 全部进入目标 phase。

        Core 的 GenerationObserver 只在被调用时观察；这里经真实 HTTP
        ``POST /generations/refresh`` 驱动 Queued→Running→Succeeded 流转。
        超时抛 ``TimeoutError``（等待辅助的失败信号，不是业务断言）。
        """
        deadline = time.monotonic() + timeout
        while True:
            snap = self.snapshot()
            matched = [
                generation
                for generation in snap["generations"]
                if (kind is None or generation["kind"] == kind)
                and (target_ids is None or generation["target_id"] in target_ids)
            ]
            pending = [
                generation
                for generation in matched
                if generation["phase"] not in phases and not generation["dismissed"]
            ]
            if not pending:
                return snap
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"等待 Generation 超时：{[(g['id'], g['kind'], g['phase']) for g in pending]}"
                )
            self._post("wait_generations", f"{self.resource}/generations/refresh", {})
            time.sleep(interval)

    # ------------------------------------------------------------------
    # 最小合法 payload 默认值（调用方可整包覆盖）
    # ------------------------------------------------------------------

    @staticmethod
    def default_character_card(**overrides: Any) -> dict:
        card = {
            "name": "小满",
            "visual_description": "短发，蓝色外套，一直带着红色行李箱",
            "voice_description": "年轻、克制、语速偏慢",
            # 通用旅程不生成角色图；造型为空时 Keyframe 不提交角色图。
            "looks": [],
        }
        card.update(overrides)
        return card

    @staticmethod
    def default_narrator(**overrides: Any) -> dict:
        narrator = {
            "name": "旁白",
            "zh_voice_description": "克制、温和、纪录片式表达",
            "en_voice_description": "Calm, warm documentary narrator.",
        }
        narrator.update(overrides)
        return narrator

    @staticmethod
    def drama_scene(character_id: str, **overrides: Any) -> dict:
        """单个 drama Scene：一个 Shot、一个带对白 Segment。"""
        scene = {
            "driver": "drama",
            "title": "末班车",
            "summary": "小满在停用前的车站等最后一班车。",
            "setting": "傍晚，空旷站台，冷蓝色天光。",
            "shots": [
                {
                    "visible_character_ids": [character_id],
                    "composition": "中远景，人物位于画面右侧。",
                    "camera_movement": "缓慢推近。",
                    "action": "小满握住行李箱拉杆，抬头看向站牌。",
                    "audio_direction": "远处风声和站内电流声。",
                    "transition_in": None,
                }
            ],
            "segments": [
                {
                    "shot_indexes": [0],
                    "duration_estimate_seconds": 6.0,
                    "action": "小满抬头看向站牌。",
                    "dialogue_lines": [
                        {
                            "character_id": character_id,
                            "text": "还会来吗？",
                            "delivery": "轻声，带一点迟疑",
                        }
                    ],
                    "boundary_from_previous": None,
                }
            ],
            "narration_cues": [],
        }
        scene.update(overrides)
        return scene

    @staticmethod
    def narration_scene(**overrides: Any) -> dict:
        """单个 narration Scene：一个语义原子 Cue，先不规划 Shot。"""
        scene = {
            "driver": "narration",
            "title": "安静的站台",
            "summary": "画外旁白描述小满等待末班车的安静时刻。",
            "setting": "傍晚，空旷站台，冷蓝色天光。",
            "shots": [],
            "segments": [],
            "narration_cues": [
                {
                    "zh": {"text": "末班车到来以前，站台仍旧保持着漫长的安静。", "seed": 42},
                    "en": {
                        "text": "Before the last train arrives, the platform stays quiet.",
                        "seed": 42,
                    },
                }
            ],
        }
        scene.update(overrides)
        return scene

    # ------------------------------------------------------------------
    # 旅程步骤
    # ------------------------------------------------------------------

    def create_project(
        self,
        title: str = "旅程项目",
        aspect: str = "16:9",
        plan: str = _DEFAULT_PLAN,
    ) -> dict:
        """POST /api/projects（human）→ 201 后授权项目访问，记录 project_id。"""
        status, body = self._server.request(
            "POST",
            "/api/projects",
            {
                "title": title,
                "aspect_ratio": aspect,
                "director_plan_markdown": plan,
                "narration_languages": ["zh", "en"],
            },
            role="human",
        )
        if status >= 400:
            raise JourneyStepError("create_project", status, body)
        self.project_id = body["project"]["id"]
        self._server.authorize_project(self.project_id)
        return body

    def propose_references(
        self,
        cards: list[dict] | None = None,
        narrator: dict | None = None,
        instruction: str = "严格按完整导演方案整理引用库",
    ) -> dict:
        """agent：reference.request_proposal → reference.submit_proposal。"""
        proposal = {
            "characters": cards or [self.default_character_card()],
            "narrator": narrator if narrator is not None else self.default_narrator(),
        }
        requested = self._command(
            "reference.request_proposal",
            {"raw_user_instruction": instruction},
            role="agent",
            step="propose_references.request",
        )
        return self._command(
            "reference.submit_proposal",
            {"request_id": requested["data"]["request_id"], "proposal": proposal},
            role="agent",
            step="propose_references.submit",
        )

    def approve_references(self) -> dict:
        """human：reference.confirm_review（空 arguments）。"""
        return self._command("reference.confirm_review", {}, role="human")

    def apply_script(
        self,
        scenes: list[dict] | None = None,
        instruction: str = "按已审核引用库与完整导演方案生成结构化导演脚本",
    ) -> dict:
        """agent 提交脚本 proposal，human 显式确认（script.confirm）。"""
        if scenes is None:
            character_id = self.snapshot()["reference_library"]["characters"][0]["id"]
            scenes = [self.drama_scene(character_id)]
        requested = self._command(
            "script.request_proposal",
            {"raw_user_instruction": instruction},
            role="agent",
            step="apply_script.request",
        )
        self._command(
            "script.submit_proposal",
            {"request_id": requested["data"]["request_id"], "proposal": {"scenes": scenes}},
            role="agent",
            step="apply_script.submit",
        )
        return self._command("script.confirm", {}, role="human", step="apply_script.confirm")

    def _first_pending_cue(self) -> tuple[str, dict, str] | None:
        for scene in self.snapshot()["director_script"]["scenes"]:
            for cue in scene["narration_cues"]:
                for language in ("zh", "en"):
                    if cue[language]["selected_audio_asset_id"] is None:
                        return scene["id"], cue, language
        return None

    def select_narrator_voice(
        self, content: bytes | None = None, media_type: str = "audio/wav"
    ) -> dict:
        """为独立旁白身份的中英两套音色上传并选择参考音色（TTS 的前置条件）。"""
        narrator_id = self.snapshot()["reference_library"]["narrator"]["id"]
        for language in ("zh", "en"):
            path = (
                f"{self.resource}/narrator/voice-reference/upload"
                f"?expected_revision={self._revision()}&narrator_id={narrator_id}"
                f"&language={language}"
            )
            status, body = self._server.upload(
                path, content or _wav_bytes(duration_seconds=1.0), media_type
            )
            if status >= 400:
                raise JourneyStepError("select_narrator_voice", status, body)
        # Breeze 声音克隆必须附带参考音频完整文字稿；上传只登记音频，文字稿由人工补齐。
        narrator = body["reference_library"]["narrator"]
        return self._put(
            "select_narrator_voice.transcript",
            f"{self.resource}/narrator",
            {
                "expected_revision": body["revision"],
                "id": narrator["id"],
                "name": narrator["name"],
                **{
                    language: {
                        **narrator[language],
                        "voice_reference_transcript": "旁白参考音频的完整文字稿。",
                    }
                    for language in ("zh", "en")
                },
            },
        )

    def select_narration_audio(
        self,
        cue_id: str | None = None,
        scene_id: str | None = None,
        generation_id: str | None = None,
        language: str | None = None,
    ) -> dict:
        """为旁白 Cue 生成 TTS（202）并选择真实音频。

        缺省时依次处理所有待选的 Cue × 语言（中英双语都要选择）；指定 cue_id 时只处理
        该 Cue 的 language（缺省中文）。
        """
        if cue_id is None:
            snap = self.snapshot()
            while (pending := self._first_pending_cue()) is not None:
                pending_scene_id, cue, pending_language = pending
                snap = self.select_narration_audio(
                    cue["id"], pending_scene_id, language=pending_language
                )
            return snap
        language = language or "zh"
        if generation_id is None:
            self._post(
                "select_narration_audio.generate",
                f"{self.resource}/scenes/{scene_id}/narration-cues/{cue_id}/generate",
                {"expected_revision": self._revision(), "language": language},
            )
            snap = self.wait_generations(kind="narration_audio", target_ids={cue_id})
            candidates = [
                generation
                for generation in snap["generations"]
                if generation["kind"] == "narration_audio"
                and generation["target_id"] == cue_id
                and generation["language"] == language
                and generation["phase"] == "succeeded"
                and not generation["dismissed"]
            ]
            generation_id = candidates[-1]["id"]
        return self._post(
            "select_narration_audio.select",
            f"{self.resource}/scenes/{scene_id}/narration-cues/{cue_id}/select",
            {"expected_revision": self._revision(), "generation_id": generation_id},
        )

    def plan_narration_shots(self) -> dict:
        """为尚无 Shot 的 narration Scene 插入覆盖真实音频时长的 Shot；Core 随写入建立基线。"""
        snap = self.snapshot()
        assets = {asset["id"]: asset for asset in snap["assets"]}
        for scene in snap["director_script"]["scenes"]:
            if scene["driver"] != "narration" or scene["shots"]:
                continue
            for cue in scene["narration_cues"]:
                durations = [
                    assets[asset_id]["duration_seconds"]
                    for language in ("zh", "en")
                    if (asset_id := cue[language]["selected_audio_asset_id"]) in assets
                ]
                duration = max(durations) if durations else 1.0
                segment_count = max(1, math.ceil(duration / 10.0))
                segment_duration = round(duration / segment_count, 3)
                shot = {
                    "visible_character_ids": [],
                    "composition": "全景，固定机位观察。",
                    "camera_movement": "缓慢推进。",
                    "action": "同一镜头连续观察站台环境。",
                    "audio_direction": "远处风声和站内电流声。",
                    "transition_in": None,
                }
                first_segment = {
                    "shot_indexes": [0],
                    **self._narration_segment_payload(segment_duration, 0),
                }
                self._command(
                    "script.apply_operations",
                    {
                        "scope": {"scene_ids": [scene["id"]]},
                        "operations": [
                            {
                                "op": "insert_shot",
                                "scene_id": scene["id"],
                                "after_shot_id": None,
                                "shot": shot,
                                "new_segment": first_segment,
                            }
                        ],
                    },
                    role="agent",
                    step="plan_narration_shots",
                )
                snap = self.snapshot()
                planned = next(
                    item for item in snap["director_script"]["scenes"] if item["id"] == scene["id"]
                )
                shot_id = planned["shots"][0]["id"]
                remaining = [
                    {
                        "op": "insert_segment",
                        "scene_id": scene["id"],
                        "after_segment_id": planned["segments"][-1]["id"],
                        "segment": {
                            "shot_ids": [shot_id],
                            "duration_estimate_seconds": duration,
                            **self._narration_segment_payload(duration, index),
                        },
                    }
                    for index in range(1, segment_count)
                ]
                if remaining:
                    # 同批补段：Core 只在写入后校准一次总长，各段按总长填写后最终均分。
                    self._command(
                        "script.apply_operations",
                        {"scope": {"scene_ids": [scene["id"]]}, "operations": remaining},
                        role="agent",
                        step="plan_narration_shots",
                    )
                    snap = self.snapshot()
        snap = self.snapshot()
        script = snap["director_script"]
        if script["production_baseline_revision"] != script["revision"]:
            raise JourneyStepError("plan_narration_shots", 409, snap["workflow"])
        return snap

    @staticmethod
    def _narration_segment_payload(segment_duration: float, index: int) -> dict:
        return {
            "duration_estimate_seconds": segment_duration,
            "action": ("连续观察的前半程。" if index == 0 else "从同一静态交接时刻继续。"),
            "dialogue_lines": [],
            "boundary_from_previous": (
                None
                if index == 0
                else {
                    "reason": "model_constraint",
                    "continuity_instruction": "从同一静态交接时刻继续",
                }
            ),
        }

    def unlock_visual_production(self) -> dict:
        """POST /visual-production/unlock（visual_production.unlock）。"""
        return self._post(
            "unlock_visual_production",
            f"{self.resource}/visual-production/unlock",
            {"expected_revision": self._revision()},
        )

    @staticmethod
    def _default_keyframe_proposal(workset: dict, prompt_text: str | None) -> dict:
        """按请求工作集构造覆盖全部授权 Segment 的最小合法 KeyframePlanProposal。"""
        segments = []
        for scene in workset["core_facts"]["scenes"]:
            previous_end = None
            for segment in scene["segments"]:
                continues = (
                    previous_end is not None and segment["start_keyframe_id"] == previous_end
                )
                if not segment.get("planning_enabled", True):
                    previous_end = segment["end_keyframe_id"]
                    continue
                character_ids = [character["id"] for character in segment["visible_characters"]]
                segments.append(
                    {
                        "segment_id": segment["id"],
                        "continues_from_previous": continues,
                        "frame_strategy": "both",
                        "start_prompt_text": (
                            "" if continues else prompt_text or f"{scene['title']}的静态首帧。"
                        ),
                        "start_visible_character_ids": [] if continues else character_ids,
                        "start_character_references": [],
                        "end_prompt_text": prompt_text or f"{scene['title']}的静态尾帧。",
                        "end_visible_character_ids": character_ids,
                        "end_character_references": [],
                    }
                )
                previous_end = segment["end_keyframe_id"]
        return {"segments": segments}

    def plan_keyframes(
        self,
        proposal: dict | None = None,
        prompt_text: str | None = None,
        instruction: str = "按当前生产基线为全部 Segment 规划关键帧",
    ) -> dict:
        """agent 走 keyframe proposal 规划并提交（不生成），返回 submit 响应。"""
        snap = self.snapshot()
        scene_ids = [scene["id"] for scene in snap["director_script"]["scenes"]]
        segment_ids = [
            segment["id"]
            for scene in snap["director_script"]["scenes"]
            for segment in scene["segments"]
        ]
        requested = self._command(
            "keyframe.request_proposal",
            {
                "raw_user_instruction": instruction,
                "scope": {"scene_ids": scene_ids},
                "target_ids": segment_ids,
            },
            role="agent",
            step="plan_keyframes.request",
        )
        workset = requested["data"]
        return self._command(
            "keyframe.submit_proposal",
            {
                "request_id": workset["request_id"],
                "proposal": proposal or self._default_keyframe_proposal(workset, prompt_text),
            },
            role="agent",
            step="plan_keyframes.submit",
        )

    @staticmethod
    def _pending_keyframe_ids(snap: dict) -> list[str]:
        """没有已选图片且没有未作废成功候选的激活帧。"""
        return [
            frame["id"]
            for frame in snap["keyframe_plan"]["keyframes"]
            if frame["selected_asset_id"] is None
            and not any(
                generation["kind"] == "keyframe_image"
                and generation["target_id"] == frame["id"]
                and generation["phase"] == "succeeded"
                and not generation["dismissed"]
                for generation in snap["generations"]
            )
        ]

    def generate_keyframe_candidates(
        self,
        *,
        phases: set[str] = frozenset({"succeeded"}),
        timeout: float = 10.0,
    ) -> dict:
        """多轮批量提交并等待，直到每个激活帧都有处于目标 phase 的候选。

        每轮批量只提交前置依赖已满足的 Keyframe；前置完成后需要新的显式
        批量动作继续下一轮（如 O2 中断恢复后的继续）。无进展时抛
        ``TimeoutError`` 而非死等。
        """
        remaining: set[str] | None = None
        while True:
            snap = self.wait_generations(kind="keyframe_image", phases=phases, timeout=timeout)
            pending = self._pending_keyframe_ids(snap)
            if not pending:
                return snap
            if pending == remaining:
                raise TimeoutError(f"关键帧批量生成无进展，仍待生成：{pending}")
            remaining = pending
            self._post(
                "generate_keyframe_candidates.batch",
                f"{self.resource}/keyframes/generate-batch",
                {"expected_revision": self._revision()},
            )

    def select_keyframe_candidates(self) -> dict:
        """为每个激活帧选择最近一个未作废的成功候选，返回最后一个响应。"""
        snap = self.snapshot()
        responses = []
        for frame in snap["keyframe_plan"]["keyframes"]:
            candidates = [
                generation
                for generation in snap["generations"]
                if generation["kind"] == "keyframe_image"
                and generation["target_id"] == frame["id"]
                and generation["phase"] == "succeeded"
                and not generation["dismissed"]
            ]
            responses.append(
                self._post(
                    "select_keyframe_candidates",
                    f"{self.resource}/keyframes/{frame['id']}/select",
                    {
                        "expected_revision": self._revision(),
                        "asset_id": candidates[-1]["output_asset_id"],
                    },
                )
            )
        return responses[-1]

    def generate_keyframes(
        self,
        proposal: dict | None = None,
        prompt_text: str | None = None,
        instruction: str = "按当前生产基线为全部 Segment 规划关键帧",
        select: bool = True,
    ) -> dict:
        """agent 走 keyframe proposal 规划 → human 批量生成 → 逐个选择候选。"""
        self.plan_keyframes(proposal=proposal, prompt_text=prompt_text, instruction=instruction)
        snap = self.generate_keyframe_candidates()
        if not select:
            return snap
        return self.select_keyframe_candidates()

    def generate_videos(
        self,
        prompt_text: str | None = None,
        select: bool = True,
    ) -> dict:
        """为每个未选 Segment 保存 H3 提示词并逐个生成，等待成功后选择。"""
        self.prepare_dialogue_tts()
        snap = self.snapshot()
        for segment in snap["video_plan"]["segments"]:
            if segment["selected_asset_id"] is None:
                self._put(
                    "generate_videos.plan",
                    f"{self.resource}/segments/{segment['segment_id']}/videos/inputs",
                    video_wire_dict(
                        {
                            "expected_revision": self._revision(),
                            "prompt_text": prompt_text or "固定机位观察站台，人物停在画面右侧。",
                            "additional_image_references": [],
                            "audio_references": (
                                segment["recipe_state"]["dialogue_audio"]["bindings"]
                                if segment["recipe_state"]["dialogue_audio"] is not None
                                else []
                            ),
                            "video_references": [],
                        }
                    ),
                )
                self._post(
                    "generate_videos.generate",
                    f"{self.resource}/segments/{segment['segment_id']}/videos/generate",
                    {"expected_revision": self._revision()},
                )
        snap = self.wait_generations(kind="segment_video")
        if not select:
            return snap
        responses = []
        for segment in snap["video_plan"]["segments"]:
            candidates = [
                generation
                for generation in snap["generations"]
                if generation["kind"] == "segment_video"
                and generation["target_id"] == segment["segment_id"]
                and generation["phase"] == "succeeded"
                and not generation["dismissed"]
            ]
            responses.append(
                self._post(
                    "generate_videos.select",
                    f"{self.resource}/segments/{segment['segment_id']}/videos/select",
                    {
                        "expected_revision": self._revision(),
                        "asset_id": candidates[-1]["output_asset_id"],
                    },
                )
            )
        return responses[-1]

    def prepare_dialogue_tts(self) -> dict:
        """按 v34 正式流程生成、人工选择对白 TTS，并按真实 WAV 时长校准 Segment。"""
        snap = self.snapshot()
        plan = snap.get("dialogue_plan")
        if not plan or not plan["items"]:
            return snap
        pending = [item for item in plan["items"] if item["selected_audio_asset_id"] is None]
        if pending:
            self._post(
                "prepare_dialogue_tts.generate",
                f"{self.resource}/dialogue/generate-batch",
                {"expected_revision": self._revision()},
            )
            snap = self.wait_generations(kind="dialogue_audio")
            for item in pending:
                candidates = [
                    generation
                    for generation in snap["generations"]
                    if generation["kind"] == "dialogue_audio"
                    and generation["target_id"] == item["dialogue_line_id"]
                    and generation["phase"] == "succeeded"
                    and not generation["dismissed"]
                ]
                self._post(
                    "prepare_dialogue_tts.select",
                    f"{self.resource}/dialogue-lines/{item['dialogue_line_id']}/select",
                    {
                        "expected_revision": self._revision(),
                        "generation_id": candidates[-1]["id"],
                    },
                )
        self._post(
            "prepare_dialogue_tts.timing",
            f"{self.resource}/dialogue/auto-calibrate-timing",
            {"expected_revision": self._revision()},
        )
        return self.snapshot()

    def assemble_scene_finals(self) -> dict:
        """逐 Scene 提交 Scene 成片装配（202），等待全部 succeeded。"""
        responses = []
        for scene in self.snapshot()["director_script"]["scenes"]:
            responses.append(
                self._post(
                    "assemble_scene_finals",
                    f"{self.resource}/scenes/{scene['id']}/final",
                    {"expected_revision": self._revision()},
                )
            )
        self.wait_generations(kind="scene_final_video")
        return responses[-1]

    def assemble_final(self, select: bool = True) -> dict:
        """进入最终装配 → final.assemble（202）→ 等待成功 → 选择成片候选。"""
        self._post(
            "assemble_final.enter",
            f"{self.resource}/final/enter",
            {"expected_revision": self._revision()},
        )
        self._post(
            "assemble_final.generate",
            f"{self.resource}/final/generate",
            {"expected_revision": self._revision()},
        )
        snap = self.wait_generations(kind="final_video")
        if not select:
            return snap
        # 中英两个单语成片各自选择最新成功候选。
        for language in ("zh", "en"):
            generation = next(
                generation
                for generation in reversed(snap["generations"])
                if generation["kind"] == "final_video"
                and generation["language"] == language
                and generation["phase"] == "succeeded"
                and not generation["dismissed"]
            )
            snap = self._post(
                f"assemble_final.select.{language}",
                f"{self.resource}/final/select",
                {"expected_revision": self._revision(), "generation_id": generation["id"]},
            )
        return snap

    def approve_final(self, zh_asset_id: str | None = None, en_asset_id: str | None = None) -> dict:
        """选择后的中英成片仍需单独 Approval；一次 Approval 同时批准两版。"""
        plan = self.snapshot()["final_assembly"]
        return self._post(
            "approve_final",
            f"{self.resource}/final/approve",
            {
                "expected_revision": self._revision(),
                "zh_asset_id": zh_asset_id or plan["selected_zh_asset_id"],
                "en_asset_id": en_asset_id or plan["selected_en_asset_id"],
            },
        )


@pytest.fixture
def journey(http_server: OracleHttpServer) -> Journey:
    return Journey(http_server)
