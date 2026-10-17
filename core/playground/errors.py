"""Playground 领域的可映射错误；HTTP 层按 code/status 转成错误信封。"""

from __future__ import annotations


class PlaygroundError(Exception):
    code: str = "invalid_request"
    status: int = 400
    recoverable: bool = False


class ProviderUnavailableError(PlaygroundError):
    code = "provider_unavailable"
    status = 409
    recoverable = True


class RunNotFoundError(PlaygroundError):
    code = "run_not_found"
    status = 404


class AssetNotFoundError(PlaygroundError):
    code = "asset_not_found"
    status = 404


class RunStateConflictError(PlaygroundError):
    code = "run_state_conflict"
    status = 409


class AssetInUseError(PlaygroundError):
    code = "asset_in_use"
    status = 409

    def __init__(self, message: str, asset_ids: tuple[str, ...]) -> None:
        super().__init__(message)
        self.asset_ids = asset_ids


class IdempotencyConflictError(PlaygroundError):
    code = "idempotency_conflict"
    status = 409
