from __future__ import annotations

import asyncio
from hashlib import sha256
from uuid import uuid4

from core.model_providers.manifest import Role
from core.model_providers.recipe import MediaInput, RecipeParams, role_field

from ..character_look_requests import (
    LOOK_SHEET_ASPECT_RATIO,
    look_sheet_plan,
    look_sheet_prompt,
)
from ..generation_lifecycle import (
    _link_generation_retry,
    _next_generation_seed,
    _submission_failure,
)
from ..image_inputs import ImageInputs
from ..image_prompt_style import ImagePromptStyle, image_capability
from ..keyframe_requests import (
    _active_keyframe_ids,
    _find_keyframe,
    _keyframe_effective_prompt,
    _keyframe_existing_result,
    _keyframe_generation_inputs,
)
from ..location_requests import (
    location_image_plan,
    location_image_prompt,
)
from ..models import (
    GenerationOperation,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
    transition_generation,
)
from ..production_context import _TERMINAL_PHASES
from .support import _commit_submission


def _prepare_image(service, operation):
    prepared = service._registry.prepare_recipe(image_capability(operation))
    return prepared, ImagePromptStyle(prepared.plugin.manifest, prepared.recipe.id)


def _image_seed(document, prepared, kind, target_id, retry_of):
    """只有声明 Seed 角色的图片 recipe 才由 Core 分配 seed；重试沿用原 seed。

    每次新提交消耗一个 seed，同一目标重复生成不会得到同一张图。
    """
    if role_field(prepared.recipe, Role.SEED) is None:
        return None
    if retry_of is not None and retry_of.seed is not None:
        return retry_of.seed
    initial = int.from_bytes(sha256(target_id.encode()).digest()[:8], "big") % (2**63)
    return _next_generation_seed(document, kind, target_id, initial)


def _image_recipe(
    service, document, prepared, operation, prompt, asset_ids, seed, aspect_ratio=None
):
    """aspect_ratio 为 None 时使用项目画幅。"""
    images = tuple(
        MediaInput(asset.media_type, content)
        for asset, content in (service._store.read_asset(asset_id) for asset_id in asset_ids)
    )
    media = {Role.REFERENCE_IMAGE: images}
    if operation is GenerationOperation.EDIT:
        media = {Role.EDIT_SOURCE: images[:1], Role.REFERENCE_IMAGE: images[1:]}
    roles = {Role.PROMPT: prompt, Role.ASPECT_RATIO: aspect_ratio or document.aspect_ratio.value}
    if seed is not None:
        roles[Role.SEED] = seed
    request, submitted = prepared.request(roles=roles, media=media)
    params = RecipeParams.from_json({prepared.recipe.id: submitted}) if submitted else None
    return request, params or RecipeParams()


class ImageSubmission:
    async def generate_look_sheet(
        self,
        *,
        look_id: str,
        identity_asset_ids: tuple[str, ...],
        expected_revision: int,
        prompt_text: str | None = None,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        """提交造型设定图候选：固定 2:1；成功只保存候选，由人类选择。

        prompt_text 为 None 时由 Core 编译版式提示词；人类编辑过的完整提示词原样提交，
        重试同样沿用。
        """
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise ValueError("项目已被更新，请重新读取后再生成。")
            plan = look_sheet_plan(document, look_id, identity_asset_ids)
            kind = ReferenceGenerationKind.CHARACTER_LOOK_SHEET
            operation = GenerationOperation.GENERATE
            prepared, style = _prepare_image(self, operation)
            prompt = (
                look_sheet_prompt(plan, style)
                if prompt_text is None
                else _custom_sheet_prompt(prompt_text)
            )
            seed = _image_seed(document, prepared, kind, look_id, _retry_of)
            request, recipe_params = _image_recipe(
                self,
                document,
                prepared,
                operation,
                prompt,
                plan.inputs.asset_ids,
                seed,
                LOOK_SHEET_ASPECT_RATIO,
            )
            generation = _image_generation(
                kind,
                operation,
                look_id,
                prompt,
                plan.inputs.asset_ids,
                seed,
                prepared,
                recipe_params,
                message="正在提交造型设定图任务。",
                aspect_ratio=LOOK_SHEET_ASPECT_RATIO,
            )
            return await _commit_submission(
                self,
                document,
                generation,
                expected_revision=document.revision,
                submit=lambda: prepared.submit(request),
                capability="造型设定图",
                queued_message="造型设定图任务已提交。",
                retry_of=_retry_of,
            )

    async def _submit_ready_keyframe_generations(
        self,
        document: StructuredDirectorDocument,
        *,
        report_blocked: bool = False,
    ) -> StructuredDirectorDocument:
        if document.keyframe_plan is None:
            raise ValueError("Segment Keyframe 计划尚未建立。")
        current = document
        submitted = {
            item.target_id
            for item in current.generations
            if item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
        }
        blocked_errors: list[str] = []
        submitted_count = 0
        active_keyframe_ids = _active_keyframe_ids(current.keyframe_plan)
        for keyframe in current.keyframe_plan.keyframes:
            if keyframe.id not in active_keyframe_ids:
                continue
            if keyframe.id in submitted or _keyframe_existing_result(current, keyframe.id):
                continue
            try:
                inputs = _keyframe_generation_inputs(current, keyframe.id)
            except ValueError as exc:
                blocked_errors.append(str(exc))
                continue
            if inputs is None:
                continue
            current = await self._submit_keyframe_generation(current, keyframe.id, inputs)
            submitted.add(keyframe.id)
            submitted_count += 1
        if report_blocked and submitted_count == 0 and blocked_errors:
            raise ValueError(blocked_errors[0])
        return current

    async def _submit_keyframe_generation(
        self,
        document: StructuredDirectorDocument,
        keyframe_id: str,
        inputs: ImageInputs,
        *,
        retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        keyframe = _find_keyframe(document, keyframe_id)
        if not keyframe.prompt_text.strip():
            raise ValueError("请先填写 Keyframe 静态画面提示词。")
        operation = inputs.operation
        prepared, style = _prepare_image(self, operation)
        effective_prompt = _keyframe_effective_prompt(document, keyframe, inputs, style)
        seed = _image_seed(
            document, prepared, ReferenceGenerationKind.KEYFRAME_IMAGE, keyframe.id, retry_of
        )
        request, recipe_params = _image_recipe(
            self, document, prepared, operation, effective_prompt, inputs.asset_ids, seed
        )
        generation = ReferenceGeneration(
            id=uuid4().hex,
            kind=ReferenceGenerationKind.KEYFRAME_IMAGE,
            operation=operation,
            target_id=keyframe.id,
            phase=ReferenceGenerationPhase.SUBMITTING,
            progress=0.0,
            message="正在提交 Keyframe 图片任务。",
            prompt_text=effective_prompt,
            input_asset_ids=inputs.asset_ids,
            sample_text=None,
            seed=seed,
            plugin_id=None,
            plugin_version=None,
            external_id=None,
            output_asset_id=None,
            error_code=None,
            cancellation_requested=False,
            retry_of=None,
            provider_snapshot=prepared.snapshot,
            recipe_params=recipe_params,
        )
        generation = _link_generation_retry(document, generation, retry_of)
        self._store.create_generation(generation, expected_revision=document.revision)
        try:
            handle = await asyncio.to_thread(prepared.submit, request)
        except Exception as exc:
            return self._store.update_generation(
                _submission_failure(generation, exc, capability="Keyframe 图片")
            )
        queued = transition_generation(
            generation,
            ReferenceGenerationPhase.QUEUED,
            message="Keyframe 图片任务已提交。",
            plugin_id=handle.plugin_id,
            plugin_version=handle.plugin_version,
            external_id=handle.external_id,
        )
        return self._store.update_generation(queued)

    async def generate_location_image(
        self,
        *,
        image_id: str,
        expected_revision: int,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        """提交独立地点图片候选；成功只保存候选，由人类选择。"""
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise ValueError("项目已被更新，请重新读取后再生成。")
            return await self._submit_location_image(
                document, image_id=image_id, retry_of=_retry_of
            )

    async def _submit_location_image(
        self,
        document: StructuredDirectorDocument,
        *,
        image_id: str,
        retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        plan = location_image_plan(document, image_id)
        _reject_active_location_generation(document, image_id, "该地点图片已有进行中的任务。")
        kind = ReferenceGenerationKind.LOCATION_IMAGE
        operation = GenerationOperation.GENERATE
        prepared, style = _prepare_image(self, operation)
        prompt = location_image_prompt(document, plan, style)
        seed = _image_seed(document, prepared, kind, image_id, retry_of)
        request, recipe_params = _image_recipe(
            self,
            document,
            prepared,
            operation,
            prompt,
            plan.inputs.asset_ids,
            seed,
            plan.aspect_ratio,
        )
        generation = _image_generation(
            kind,
            operation,
            image_id,
            prompt,
            plan.inputs.asset_ids,
            seed,
            prepared,
            recipe_params,
            message="正在提交地点图片任务。",
            aspect_ratio=plan.aspect_ratio,
        )
        return await _commit_submission(
            self,
            document,
            generation,
            expected_revision=document.revision,
            submit=lambda: prepared.submit(request),
            capability="地点图片",
            queued_message="地点图片任务已提交。",
            retry_of=retry_of,
        )


def _custom_sheet_prompt(prompt_text: str) -> str:
    prompt = prompt_text.strip()
    if not prompt:
        raise ValueError("请填写设定图提示词。")
    if len(prompt) > 20_000:
        raise ValueError("设定图提示词过长（最多 20000 字）。")
    return prompt


def _reject_active_location_generation(document, target_id: str, message: str) -> None:
    if any(
        item.target_id == target_id
        and item.kind
        in {
            ReferenceGenerationKind.PANORAMA_CAPTURE,
            ReferenceGenerationKind.LOCATION_IMAGE,
        }
        and item.phase not in _TERMINAL_PHASES
        for item in document.generations
    ):
        raise ValueError(message)


def _image_generation(
    kind,
    operation,
    target_id,
    prompt,
    asset_ids,
    seed,
    prepared,
    recipe_params,
    *,
    message: str,
    aspect_ratio: str | None = None,
) -> ReferenceGeneration:
    return ReferenceGeneration(
        id=uuid4().hex,
        kind=kind,
        operation=operation,
        target_id=target_id,
        phase=ReferenceGenerationPhase.SUBMITTING,
        progress=0.0,
        message=message,
        prompt_text=prompt,
        input_asset_ids=asset_ids,
        sample_text=None,
        seed=seed,
        plugin_id=None,
        plugin_version=None,
        external_id=None,
        output_asset_id=None,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
        provider_snapshot=prepared.snapshot,
        recipe_params=recipe_params,
        aspect_ratio=aspect_ratio,
    )
