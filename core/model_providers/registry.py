"""媒体能力注册表：已安装插件、全局能力绑定与插件设置。

插件以 :class:`PluginInstance` 安装，声明 manifest 以及每个 recipe 的实现。
每个语义能力在全局绑定到一个插件；之后的提交按当前绑定解析，历史 Generation 仍按自己记录的
``plugin_id`` 和版本回到原实现，不跟随后来的绑定。Core 本地确定性工具直接注册，没有可选实现。
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from .image_prompt_skill import image_prompt_skill
from .manifest import (
    CAPABILITY_LABELS,
    TOOL_LABELS,
    Capability,
    PluginManifest,
    ProviderSnapshot,
    Recipe,
    Role,
    Tool,
)
from .recipe import (
    MediaInput,
    RecipeInputs,
    RecipeRequest,
    _validate_slot,
    build_recipe_request,
    default_mechanism_params,
    explicit_slots,
    mechanism_fields,
    parse_recipe_wire,
    recipe_wire_value,
    validate_mechanism_params,
)
from .settings import ProviderSettingsStore

CAPABILITIES = frozenset(tool.value for tool in Tool)


def _plugin_ids(provider: object) -> frozenset[str]:
    """实现对象可能签发的全部句柄 plugin_id。"""
    ids = {str(item) for item in getattr(provider, "plugin_ids", None) or ()}
    for name in ("plugin_id", "generate_plugin_id", "edit_plugin_id"):
        value = getattr(provider, name, None)
        if isinstance(value, str) and value:
            ids.add(value)
    return frozenset(ids)


@dataclass(frozen=True, slots=True)
class PluginInstance:
    """一个已安装、已配置连接的插件：manifest + 实现。

    ``recipes`` 映射 recipe ID 到实现；模型任务提交使用 ``submit_recipe``，
    同步语音转写使用 ``execute_recipe``。``prompt_skills`` 返回随插件发布、供 Agent 写提示词的
    Skill 正文（``[{name, resources: [{name, text}]}]``），由 Core 经专业契约交付。
    """

    manifest: PluginManifest
    endpoint: str | None = None
    recipes: Mapping[str, object] = field(default_factory=dict)
    prompt_formatter: Callable[[dict], dict] | None = None
    prompt_skills: Callable[[], list[dict]] | None = None

    def __post_init__(self) -> None:
        if not self.recipes:
            raise ValueError(f"插件 {self.manifest.plugin_id} 没有任何实现。")
        for recipe_id, provider in self.recipes.items():
            self.manifest.recipe(recipe_id)
            methods = (
                ("execute_recipe",)
                if self.manifest.recipe(recipe_id).capability is Capability.SPEECH_RECOGNIZE
                else ("submit_recipe", "observe", "cancel", "read_artifact")
            )
            for method in methods:
                if not callable(getattr(provider, method, None)):
                    raise ValueError(f"recipe {recipe_id} 的实现缺少 {method}。")

    @property
    def plugin_id(self) -> str:
        return self.manifest.plugin_id

    def implements(self, capability: Capability) -> bool:
        return any(
            self.manifest.recipe(recipe_id).capability is capability for recipe_id in self.recipes
        )

    def default_recipe(
        self, capability: Capability, predicates: frozenset = frozenset()
    ) -> Recipe | None:
        """按 manifest 顺序选择谓词成立的默认规则，否则取首个已实现的 recipe。"""
        rules = dict(self.manifest.defaults).get(capability, ())
        for rule in rules:
            if (rule.when is None or rule.when in predicates) and rule.recipe in self.recipes:
                return self.manifest.recipe(rule.recipe)
        return next(
            (
                self.manifest.recipe(recipe_id)
                for recipe_id in self.recipes
                if self.manifest.recipe(recipe_id).capability is capability
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class PreparedRecipe:
    """一次 recipe 提交解析出的插件、recipe、生效设置与快照。"""

    plugin: PluginInstance
    recipe: Recipe
    settings: dict[str, Any]
    snapshot: ProviderSnapshot

    def submit(self, request: RecipeRequest):
        if request.recipe_id != self.recipe.id:
            raise ValueError("提交的 recipe 与解析结果不一致。")
        return self.plugin.recipes[self.recipe.id].submit_recipe(request)

    def execute(self, request: RecipeRequest):
        if (
            request.recipe_id != self.recipe.id
            or self.recipe.capability is not Capability.SPEECH_RECOGNIZE
        ):
            raise ValueError("当前 recipe 不支持同步转写。")
        return self.plugin.recipes[self.recipe.id].execute_recipe(request)

    def request(
        self,
        *,
        roles: Mapping[Role, Any],
        media: Mapping[Role, Sequence[MediaInput]] | None = None,
        mechanism: Mapping[str, Any] | None = None,
        slot_inputs: Mapping[str, Sequence[MediaInput]] | None = None,
    ) -> tuple[RecipeRequest, dict[str, Any]]:
        """按语义角色填写参数与槽位；机制参数取保存值，缺省时用 manifest 默认值。

        返回已校验的请求与实际提交的机制参数（写进 Generation 供追溯与重试）。
        """
        recipe = self.recipe
        params: dict[str, Any] = {}
        for item in recipe.params:
            if item.role is None:
                continue
            if item.role not in roles:
                # 无项目语言上下文的资产音频使用声明的自动识别；其它领域事实仍必须提供。
                if item.role is Role.LANGUAGE and item.default == "auto":
                    params[item.key] = "auto"
                    continue
                raise ValueError(f"{recipe.label}需要{item.label}，当前上下文无法提供。")
            params[item.key] = roles[item.role]
        submitted = validate_mechanism_params(
            recipe, {**default_mechanism_params(recipe), **dict(mechanism or {})}
        )
        params.update(submitted)
        inputs = {slot.key: tuple((media or {}).get(slot.role, ())) for slot in recipe.slots}
        inputs.update(slot_inputs or {})
        built = build_recipe_request(
            self.plugin.manifest, recipe.id, inputs=inputs, params=params, settings=self.settings
        )
        return built, submitted


@dataclass(frozen=True, slots=True)
class PreparedSubmission:
    """一次提交解析出的实现与快照；Generation 记录的快照与实际提交来自同一次解析。"""

    provider: object
    submit: Callable[[Any], Any]
    snapshot: ProviderSnapshot | None


def prepare_submission(provider: object, method: str) -> PreparedSubmission:
    """按当前绑定解析提交；直接注册的实现（测试替身、确定性工具）没有快照。"""
    return PreparedSubmission(provider, getattr(provider, method), None)


class ProviderRegistry:
    """插件按全局绑定选择 recipe；Core 确定性工具直接注册。"""

    def __init__(self, settings: ProviderSettingsStore | None = None) -> None:
        self._settings = settings or ProviderSettingsStore()
        self._plugins: dict[str, PluginInstance] = {}
        self._direct: dict[str, object] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------ 安装

    def install(self, plugin: PluginInstance) -> None:
        if plugin.plugin_id in self._plugins:
            raise ValueError(f"插件已安装：{plugin.plugin_id}")
        self._plugins[plugin.plugin_id] = plugin

    def register(self, capability: str, provider: object) -> None:
        """直接注册一个端口实现：Core 确定性工具，或测试中的替身。"""
        if capability not in CAPABILITIES:
            raise ValueError(f"媒体能力不受支持：{capability}")
        if provider is None:
            raise ValueError("不能注册空 Provider。")
        if capability in self._direct:
            raise ValueError(f"媒体能力已注册：{capability}")
        if _plugin_ids(provider) and not isinstance(getattr(provider, "plugin_version", None), int):
            raise ValueError("Provider plugin_version 不合法。")
        self._direct[capability] = provider

    # ------------------------------------------------------------ 解析

    def resolve(self, capability: str) -> object | None:
        if capability not in CAPABILITIES:
            raise ValueError(f"媒体能力不受支持：{capability}")
        return self._direct.get(capability)

    def available(self, tool: str) -> bool:
        return tool in self._direct

    def resolve_plugin(
        self,
        plugin_id: str,
        plugin_version: int,
        *,
        capabilities: tuple[str, ...] | None = None,
    ) -> object | None:
        matches = [
            provider
            for port, provider in self._candidates(capabilities)
            if plugin_id in _plugin_ids(provider)
            and getattr(provider, "plugin_version", None) == plugin_version
        ]
        unique = list({id(provider): provider for provider in matches}.values())
        return unique[0] if len(unique) == 1 else None

    def _candidates(self, filters: tuple[str, ...] | None) -> list[tuple[str, object]]:
        """``filters`` 可以是 Core 端口名或语义能力值。"""
        found: list[tuple[str, object]] = []
        for port, provider in self._direct.items():
            if filters is None or port in filters:
                found.append((port, provider))
        for plugin in self._plugins.values():
            for recipe_id, provider in plugin.recipes.items():
                capability = plugin.manifest.recipe(recipe_id).capability.value
                if filters is None or capability in filters:
                    found.append((capability, provider))
        return found

    # ------------------------------------------------------------ recipe 提交

    def capability_available(self, capability: Capability) -> bool:
        return self._effective_plugin(capability) is not None

    def recipe_for(
        self, capability: Capability, predicates: frozenset = frozenset()
    ) -> tuple[PluginInstance, Recipe] | None:
        """当前绑定插件对该能力的默认 recipe；没有可用实现时为 None。"""
        plugin = self._effective_plugin(capability)
        if plugin is None:
            return None
        recipe = plugin.default_recipe(capability, predicates)
        return None if recipe is None else (plugin, recipe)

    def prepare_recipe(
        self,
        capability: Capability,
        *,
        plugin_id: str | None = None,
        recipe_id: str | None = None,
    ) -> PreparedRecipe:
        """按当前绑定（或重试时指定的原插件）解析 recipe 与设置。"""
        with self._lock:
            if plugin_id is None:
                plugin = self._effective_plugin(capability)
                if plugin is None:
                    raise RuntimeError(self._unavailable_message(capability))
            else:
                plugin = self._plugins.get(plugin_id)
                if plugin is None:
                    raise RuntimeError(f"原插件 {plugin_id} 当前未安装，不能按原请求重试。")
            if recipe_id is None:
                recipe = plugin.default_recipe(capability)
            else:
                recipe = plugin.manifest.recipe(recipe_id)
            if (
                recipe is None
                or recipe.capability is not capability
                or recipe.id not in plugin.recipes
            ):
                label = CAPABILITY_LABELS[capability]
                raise RuntimeError(f"插件 {plugin.plugin_id} 不能以 recipe 方式提供{label}。")
            settings = self._plugin_settings(plugin)
            snapshot = ProviderSnapshot.build(plugin.manifest, recipe.id, settings)
        return PreparedRecipe(plugin, recipe, settings, snapshot)

    def recipe_views(self) -> list[dict[str, Any]]:
        """每个可按 recipe 提交的能力当前生效的 recipe：Web 与 Agent 据此渲染与填写机制参数。

        ``editable_params`` 是没有语义角色的机制参数，按 recipe 保存在业务对象的
        ``recipe_params`` 中；带角色的参数由 Core 按领域事实填写。
        """
        views = []
        with self._lock:
            for capability in Capability:
                found = self.recipe_for(capability)
                if found is None:
                    continue
                plugin, _default = found
                for recipe_id in plugin.recipes:
                    recipe = plugin.manifest.recipe(recipe_id)
                    if recipe.capability is not capability:
                        continue
                    views.append(
                        {
                            "capability": capability.value,
                            "plugin_id": plugin.plugin_id,
                            "plugin_label": plugin.manifest.label,
                            "recipe": recipe.to_json(),
                            "editable_params": [
                                item.to_json() for item in mechanism_fields(recipe)
                            ],
                            "settings_summary": plugin.manifest.settings_summary(
                                self._plugin_settings(plugin)
                            ),
                            "hints": dict(plugin.manifest.hints),
                        }
                    )
        return views

    def prompt_skills(self, capability: Capability) -> list[dict]:
        """当前绑定插件随附的提示词 Skill 全文，每个资源带 sha256 与字节数。"""
        found = self.recipe_for(capability)
        if found is None or found[0].prompt_skills is None:
            return []
        return [
            {
                "name": skill["name"],
                "resources": [
                    {
                        **resource,
                        "sha256": hashlib.sha256(resource["text"].encode()).hexdigest(),
                        "bytes": len(resource["text"].encode()),
                    }
                    for resource in skill["resources"]
                ],
            }
            for skill in found[0].prompt_skills()
        ]

    def format_prompt_workset(self, capability, recipe_id, value):
        plugin, _recipe = self.recipe_definition(capability, recipe_id)
        result = value if plugin.prompt_formatter is None else plugin.prompt_formatter(value)
        if capability in {Capability.IMAGE_GENERATE, Capability.IMAGE_EDIT}:
            result = {**result, "global_skills": [image_prompt_skill()]}
        return result

    def recipe_definition(
        self, capability: Capability, recipe_id: str
    ) -> tuple[PluginInstance, Recipe]:
        for plugin in self._plugins.values():
            for recipe in plugin.manifest.recipes:
                if (
                    recipe.id == recipe_id
                    and recipe.capability is capability
                    and recipe_id in plugin.recipes
                ):
                    return plugin, recipe
        raise ValueError(f"recipe {recipe_id} 当前不可用。")

    def validate_recipe_inputs(self, capability: Capability, recipe_id: str, inputs, assets):
        _plugin, recipe = self.recipe_definition(capability, recipe_id)
        explicit = explicit_slots(recipe)
        editable = replace(
            recipe,
            slots=explicit,
            params=mechanism_fields(recipe),
            require_any=(),
            distinct_slots=(),
        )
        unknown = set(dict(inputs.bindings)) - {slot.key for slot in explicit}
        if unknown:
            raise ValueError(f"{recipe.label} 不支持槽位 {', '.join(sorted(unknown))}。")
        value = recipe_wire_value(
            editable,
            dict(inputs.bindings),
            {**default_mechanism_params(recipe), **inputs.to_json()["params"]},
        )
        bindings, _params = parse_recipe_wire(editable, value)
        by_id = {asset.id: asset for asset in assets}
        for slot in explicit:
            media = []
            for binding in bindings[slot.key]:
                asset = by_id.get(binding.asset_id)
                if asset is None:
                    raise ValueError(f"{slot.label}必须引用本项目 Asset。")
                media.append(
                    MediaInput(
                        asset.media_type,
                        asset.id.encode(),
                        binding.description,
                        asset.duration_seconds,
                    )
                )
            _validate_slot(slot, tuple(media))

    def validate_recipe_switch(self, capability: Capability, current, recipe_id: str, assets):
        prepared = self.prepare_recipe(capability, recipe_id=recipe_id)
        self.validate_recipe_inputs(capability, recipe_id, current.recipes.get(recipe_id), assets)
        if not current.recipe_inputs.asset_ids:
            return
        try:
            _old_plugin, old = self.recipe_definition(capability, current.active_recipe)
        except ValueError:
            # 旧插件已卸载，旧 recipe book 仍保留；新 recipe 只使用自己保存的输入。
            return
        target_by_role = {slot.role: slot for slot in prepared.recipe.slots}
        translated = {}
        for slot in old.slots:
            values = current.recipe_inputs.slot(slot.key)
            if not values:
                continue
            target = target_by_role.get(slot.role)
            if target is None:
                raise ValueError(f"请先移除{slot.label}，再切换为 {prepared.recipe.label}。")
            translated[target.key] = values
        self.validate_recipe_inputs(
            capability, recipe_id, RecipeInputs(tuple(sorted(translated.items()))), assets
        )

    def validate_recipe_params(
        self, capability: Capability, recipe_id: str, params: object
    ) -> dict:
        """校验按 recipe 保存的机制参数；recipe 必须属于已安装插件。"""
        for plugin in self._plugins.values():
            if recipe_id in plugin.recipes:
                recipe = plugin.manifest.recipe(recipe_id)
                if recipe.capability is not capability:
                    break
                return validate_mechanism_params(recipe, params)
        label = CAPABILITY_LABELS[capability]
        raise ValueError(f"recipe {recipe_id} 不属于已安装的{label}插件，不能修改其参数。")

    # ------------------------------------------------------------ 绑定与设置

    def installed(self, plugin_id: str) -> bool:
        return plugin_id in self._plugins

    def plugin_settings(self, plugin_id: str) -> dict[str, Any]:
        plugin = self._plugins.get(plugin_id)
        if plugin is None:
            raise ValueError(f"插件未安装：{plugin_id}")
        return self._plugin_settings(plugin)

    def bind(self, capability: str, plugin_id: str) -> None:
        try:
            resolved = Capability(capability)
        except ValueError as exc:
            raise ValueError(f"能力不受支持：{capability}") from exc
        plugin = self._plugins.get(plugin_id)
        if plugin is None or not plugin.implements(resolved):
            raise ValueError(f"插件 {plugin_id} 未安装或不实现{CAPABILITY_LABELS[resolved]}。")
        with self._lock:
            state = self._settings.read()
            self._settings.write(
                replace(state, bindings={**state.bindings, resolved.value: plugin_id})
            )

    def update_plugin_settings(self, plugin_id: str, values: object) -> dict[str, Any]:
        plugin = self._plugins.get(plugin_id)
        if plugin is None:
            raise ValueError(f"插件未安装：{plugin_id}")
        validated = plugin.manifest.validate_settings(values)
        with self._lock:
            state = self._settings.read()
            self._settings.write(replace(state, settings={**state.settings, plugin_id: validated}))
        return validated

    def _effective_plugin(self, capability: Capability) -> PluginInstance | None:
        stored = self._settings.read().bindings.get(capability.value)
        if stored is not None:
            plugin = self._plugins.get(stored)
            return plugin if plugin is not None and plugin.implements(capability) else None
        return next(
            (plugin for plugin in self._plugins.values() if plugin.implements(capability)), None
        )

    def _unavailable_message(self, capability: Capability) -> str:
        stored = self._settings.read().bindings.get(capability.value)
        label = CAPABILITY_LABELS[capability]
        if stored is not None and stored not in self._plugins:
            return f"{label}绑定的插件 {stored} 当前未安装；请在 Provider 设置中重新选择。"
        return f"{label}服务尚未配置。"

    def _plugin_settings(self, plugin: PluginInstance) -> dict[str, Any]:
        stored = self._settings.read().settings.get(plugin.plugin_id)
        if stored is None:
            return plugin.manifest.default_settings()
        try:
            return plugin.manifest.validate_settings(stored)
        except ValueError:
            return plugin.manifest.default_settings()

    def _settings_error(self, plugin: PluginInstance) -> str | None:
        stored = self._settings.read().settings.get(plugin.plugin_id)
        if stored is None:
            return None
        try:
            plugin.manifest.validate_settings(stored)
        except ValueError as exc:
            return f"已保存的设置与当前插件不兼容，暂用默认值：{exc}"
        return None

    # ------------------------------------------------------------ 设置页读模型

    def describe(self) -> dict[str, Any]:
        with self._lock:
            bindings = self._settings.read().bindings
            capabilities = []
            for capability in Capability:
                candidates = [
                    plugin for plugin in self._plugins.values() if plugin.implements(capability)
                ]
                effective = self._effective_plugin(capability)
                capabilities.append(
                    {
                        "id": capability.value,
                        "label": CAPABILITY_LABELS[capability],
                        "bound_plugin_id": None if effective is None else effective.plugin_id,
                        "candidates": [
                            {"plugin_id": plugin.plugin_id, "label": plugin.manifest.label}
                            for plugin in candidates
                        ],
                        "message": (
                            None
                            if effective is not None
                            else self._unavailable_message(capability)
                            if candidates or capability.value in bindings
                            else "没有已安装的插件实现该能力。"
                        ),
                    }
                )
            plugins = []
            for plugin in self._plugins.values():
                values = self._plugin_settings(plugin)
                plugins.append(
                    {
                        "plugin_id": plugin.plugin_id,
                        "plugin_version": plugin.manifest.plugin_version,
                        "label": plugin.manifest.label,
                        "endpoint": plugin.endpoint,
                        "manifest": plugin.manifest.to_json(),
                        "settings": values,
                        "settings_summary": plugin.manifest.settings_summary(values),
                        "settings_error": self._settings_error(plugin),
                    }
                )
            tools = [
                {
                    "id": tool.value,
                    "label": TOOL_LABELS[tool],
                    "available": tool.value in self._direct,
                }
                for tool in Tool
            ]
            return {"capabilities": capabilities, "plugins": plugins, "tools": tools}
