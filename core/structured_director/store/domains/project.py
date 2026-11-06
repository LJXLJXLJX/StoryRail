"""项目级人工设置：只保存仍允许在创建后修改的项目事实。"""

from __future__ import annotations

from dataclasses import replace

from core.structured_director.models import StructuredDirectorDocument
from core.structured_director.store.pipeline import MutationResult, commit_mutation


class _DomainBase:
    def __init__(self, store) -> None:
        object.__setattr__(self, "_store", store)

    def __getattr__(self, name):
        if name == "_store":
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_store"), name)


class ProjectDomain(_DomainBase):
    def update_director_plan(
        self,
        director_plan_markdown: str,
        *,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        plan = director_plan_markdown.strip()
        if not plan:
            raise ValueError("原始导演方案不能为空。")
        if len(plan) > 50_000:
            raise ValueError("原始导演方案不能超过 50000 个字符。")

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            if document.director_plan_markdown == plan:
                return MutationResult(document, None, write=False)
            return MutationResult(
                replace(
                    document,
                    revision=document.revision + 1,
                    director_plan_markdown=plan,
                ),
                None,
            )

        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._unlocked_document(expected_revision),
            mutator=mutate,
        )
        return updated
