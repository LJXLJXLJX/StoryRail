"""统一 mutation commit pipeline（02 号文档 §3.1，P2-C1）。

所有写操作收敛为同一骨架：

1. ``loader()`` 读 document 并完成 revision CAS 与编辑期前置校验
   （``_editable_document`` / ``_unlocked_document`` 等，由调用方闭包绑定）；
2. ``mutator(document)`` 执行 L2 纯函数与域内回执组装，返回 ``MutationResult``
   （scope/状态校验在 mutator 内失败即抛错，pipeline 不会写入）；
3. ``write=True`` 时经 ``store._atomic_write`` 原子落盘（全仓库唯一写入点在此收敛）；
4. 返回 ``(document, receipt)``。

noop 路径由 mutator 以 ``write=False`` 标记，pipeline 跳过写入。
本模块零运行时 core 依赖（store 为鸭子类型参数，receipt/document 仅类型标注）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.director_commands import CommandReceipt

    from ..models import StructuredDirectorDocument


@dataclass(frozen=True, slots=True)
class MutationResult:
    """mutator 的返回：变更后的 document、完整回执与可选域附加产物。

    ``write=False`` 表示 noop（或已由 mutator 自行处理），pipeline 跳过
    ``_atomic_write``。``aux`` 为域附加产物（如 repair 的 RepairReceipt 原料），
    由调用方在 pipeline 返回后取用。
    """

    document: StructuredDirectorDocument
    receipt: CommandReceipt
    write: bool = True
    aux: object | None = None


def commit_mutation(
    store,
    *,
    loader: Callable[[], StructuredDirectorDocument],
    mutator: Callable[[StructuredDirectorDocument], MutationResult],
) -> tuple[StructuredDirectorDocument, CommandReceipt]:
    """读 → 变更 → 原子写 → 回执；全部写操作的唯一 commit 骨架。"""
    document = loader()
    outcome = mutator(document)
    if outcome.write:
        outcome = replace(
            outcome, document=store._bind_new_video_recipes(document, outcome.document)
        )
        store._atomic_write(outcome.document)
    return outcome.document, outcome.receipt
