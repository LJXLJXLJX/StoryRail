"""固定服务地址的无状态 HTTP 翻译；不导入 Core/Store/Provider。"""

import asyncio
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from storyrail_contracts.errors import error_payload


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CoreBridge:
    def __init__(self, origin: str, token_file: Path):
        target = urlsplit(origin)
        if (
            target.scheme not in {"http", "https"}
            or not target.hostname
            or target.username
            or target.password
            or target.query
            or target.fragment
            or target.path not in {"", "/"}
        ):
            raise ValueError("Core 地址必须是受信服务 origin。")
        self.origin = origin.rstrip("/")
        self.token_file = token_file

    def _token(self):
        if self.token_file.is_symlink() or self.token_file.stat().st_mode & 0o077:
            raise ValueError("token file 不受保护")
        token = self.token_file.read_text().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
            raise ValueError("token 格式错误")
        return token

    @staticmethod
    def _credential_error():
        return 503, error_payload(
            "credential_unavailable",
            "限域凭据不可用。",
            origin="authorization",
            retry_policy="restore_credentials_then_retry",
        )

    def _dispatch(self, url, payload, token):
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        except (TypeError, ValueError):
            return 400, error_payload(
                "connector_serialization_error",
                "连接器无法按公开契约序列化 wire payload。",
                recoverable=True,
                origin="connector_serialization",
                retry_policy="fix_arguments_and_retry",
            )
        request = urllib.request.Request(
            url,
            method="POST",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
            data=encoded,
        )
        try:
            # 不继承宿主代理、不跟随重定向；凭据只发往受信启动配置指定服务。
            with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(
                request, timeout=20
            ) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.load(exc)
            except (ValueError, OSError):
                return exc.code, error_payload(
                    "response_unknown",
                    "Core 返回了无法识别的错误响应；请先检查当前状态。",
                    recoverable=True,
                    origin="connector_transport",
                    state_changed="unknown",
                    retry_policy="inspect_status_before_retry",
                )
        except (OSError, ValueError):
            # 不自动重试，断连不能推断未提交；调用方保留原 revision/key 重放。
            return 503, error_payload(
                "response_unknown",
                "响应未确认，请用原参数、revision 和幂等键重试。",
                recoverable=True,
                origin="connector_transport",
                state_changed="unknown",
                retry_policy="replay_same_request",
                details={"preserve_revision": True, "preserve_idempotency_key": True},
            )

    def _send(self, project_id, name, revision, key, arguments):
        # project_id 从不成为任意 URL/path。
        if not re.fullmatch(r"[0-9a-f]{32}", project_id):
            return 400, error_payload(
                "connector_serialization_error",
                "连接器 project_id 不符合 wire 契约。",
                recoverable=True,
                origin="connector_serialization",
                retry_policy="fix_arguments_and_retry",
            )
        try:
            token = self._token()
        except (OSError, ValueError):
            return self._credential_error()
        url = self.origin + f"/api/projects/{project_id}/structured-director/application/commands"
        payload = {
            "name": name,
            "idempotency_key": key,
            "arguments": arguments,
        }
        if revision is not None:
            payload["expected_revision"] = revision
        return self._dispatch(url, payload, token)

    def _send_playground(self, name, key, arguments):
        try:
            token = self._token()
        except (OSError, ValueError):
            return self._credential_error()
        payload = {
            "name": name,
            "idempotency_key": key,
            "arguments": arguments,
        }
        return self._dispatch(self.origin + "/api/playground/commands", payload, token)

    async def call(self, project_id, name, revision, key, arguments):
        return await asyncio.to_thread(self._send, project_id, name, revision, key, arguments)

    async def call_playground(self, name, key, arguments):
        return await asyncio.to_thread(self._send_playground, name, key, arguments)

    def _read_media(self, project_id, asset_id, revision, key):
        import hashlib

        if not re.fullmatch(r"[0-9a-f]{32}", asset_id):
            return (
                400,
                error_payload(
                    "invalid_asset_id",
                    "asset_id 不符合公开契约。",
                    origin="connector_serialization",
                    retry_policy="fix_arguments_and_retry",
                ),
                None,
            )
        status, value = self._send(
            project_id, "project.get_asset_manifest", revision, key, {"asset_id": asset_id}
        )
        if status != 200:
            return status, value, None
        manifest = {
            **value["data"],
            "content_url": (
                self.origin
                + f"/api/projects/{project_id}/structured-director/assets/{asset_id}/content"
            ),
        }
        if (
            manifest["media_type"]
            not in {"image/png", "image/jpeg", "image/webp", "audio/wav", "audio/mpeg"}
            or manifest["byte_count"] > 8 * 1024 * 1024
        ):
            return (
                400,
                error_payload(
                    "media_limit",
                    "只支持8 MiB以内的图片或音频输入。",
                    origin="response_envelope",
                    retry_policy="narrow_or_continue_read",
                ),
                None,
            )
        try:
            if self.token_file.is_symlink() or self.token_file.stat().st_mode & 0o077:
                raise ValueError("凭据不可用")
            token = self.token_file.read_text().strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
                raise ValueError("凭据不可用")
            request = urllib.request.Request(
                self.origin
                + f"/api/projects/{project_id}/structured-director/assets/{asset_id}/content",
                headers={"Authorization": "Bearer " + token},
                method="GET",
            )
            with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(
                request, timeout=20
            ) as response:
                content = response.read(8 * 1024 * 1024 + 1)
                if (
                    len(content) != manifest["byte_count"]
                    or hashlib.sha256(content).hexdigest() != manifest["sha256"]
                    or response.headers.get_content_type() != manifest["media_type"]
                ):
                    raise ValueError("媒体校验不一致")
                return 200, manifest, content
        except urllib.error.HTTPError as exc:
            return (
                exc.code,
                error_payload(
                    "asset_unavailable",
                    "Core 无法读取请求的媒体资产。",
                    recoverable=True,
                    origin="connector_transport",
                    retry_policy="inspect_status_before_retry",
                ),
                None,
            )
        except (OSError, ValueError):
            return (
                503,
                error_payload(
                    "asset_unavailable",
                    "媒体读取失败或校验不一致。",
                    recoverable=True,
                    origin="connector_transport",
                    state_changed="unknown",
                    retry_policy="inspect_status_before_retry",
                ),
                None,
            )

    async def read_media(self, project_id, asset_id, revision, key):
        return await asyncio.to_thread(self._read_media, project_id, asset_id, revision, key)
