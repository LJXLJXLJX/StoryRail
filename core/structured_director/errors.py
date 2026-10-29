"""Domain errors shared by commands, persistence and HTTP translation."""

from core.director_commands.models import InvalidArgumentsError as InvalidArgumentsError


class RevisionConflictError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        expected_revision: int | None = None,
        current_revision: int | None = None,
        conflict_reason: str | None = None,
        conflicts: tuple[dict[str, str], ...] = (),
    ) -> None:
        super().__init__(message)
        if (expected_revision is None) != (current_revision is None):
            raise ValueError("revision 冲突元数据必须同时提供 expected/current。")
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        # entities_changed / journal_unavailable / exact_grant；conflicts 列出相交实体。
        self.conflict_reason = conflict_reason
        self.conflicts = conflicts
