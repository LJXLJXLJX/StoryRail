"""Provider 插件 manifest：Core 拥有的语义词汇与插件声明的机制。

Core 只理解封闭的语义能力（:class:`Capability`）、语义角色（:class:`Role`）与 Widget 词汇
（:class:`Widget`）。插件用 :class:`PluginManifest` 声明自己实现哪些 recipe、每个 recipe 使用
哪些语义角色槽位，以及对 Core 不透明的参数和实例级设置。Core 负责校验、持久化与下发，
不解释机制字段的含义。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class Capability(StrEnum):
    """业务流程需要、可由用户在全局绑定到某个插件的生产动作。"""

    IMAGE_GENERATE = "image.generate"
    IMAGE_EDIT = "image.edit"
    VOICE_DESIGN = "voice.design"
    SPEECH_SYNTHESIZE = "speech.synthesize"
    SPEECH_RECOGNIZE = "speech.recognize"
    VIDEO_GENERATE = "video.generate"
    VIDEO_UPSCALE = "video.upscale"
    AUDIO_GENERATE = "audio.generate"
    AUDIO_SEPARATE = "audio.separate"


CAPABILITY_LABELS: dict[Capability, str] = {
    Capability.IMAGE_GENERATE: "生图",
    Capability.IMAGE_EDIT: "改图",
    Capability.VOICE_DESIGN: "音色设计",
    Capability.SPEECH_SYNTHESIZE: "声音克隆",
    Capability.SPEECH_RECOGNIZE: "语音转写",
    Capability.VIDEO_GENERATE: "视频生成",
    Capability.VIDEO_UPSCALE: "视频超分",
    Capability.AUDIO_GENERATE: "文生音频",
    Capability.AUDIO_SEPARATE: "音轨分离",
}


class Tool(StrEnum):
    """Core 本地确定性工具：没有可选实现，设置页只显示状态。"""

    FINAL_ASSEMBLY = "final_assembly"
    ANIMATIC = "animatic"
    VIDEO_FRAME = "video_frame"
    PANO_VIEW = "pano_view"
    AUDIO_REMIX = "audio_remix"


TOOL_LABELS: dict[Tool, str] = {
    Tool.FINAL_ASSEMBLY: "成片装配",
    Tool.ANIMATIC: "动态分镜",
    Tool.VIDEO_FRAME: "视频抽帧",
    Tool.PANO_VIEW: "全景裁切",
    Tool.AUDIO_REMIX: "重新混音",
}


class Role(StrEnum):
    """Core 需要理解的输入语义；插件只能从这里选择，不能发明新角色。"""

    FIRST_FRAME = "first_frame"
    LAST_FRAME = "last_frame"
    REFERENCE_IMAGE = "reference_image"
    REFERENCE_AUDIO = "reference_audio"
    REFERENCE_VIDEO = "reference_video"
    VOICE_REFERENCE = "voice_reference"
    VOICE_TRANSCRIPT = "voice_transcript"
    EDIT_SOURCE = "edit_source"
    # 被处理（超分、分离、转写）的来源媒体，不是参考。
    SOURCE_VIDEO = "source_video"
    SOURCE_AUDIO = "source_audio"
    PROMPT = "prompt"
    SPEECH_TEXT = "speech_text"
    LANGUAGE = "language"
    DURATION = "duration"
    ASPECT_RATIO = "aspect_ratio"
    SEED = "seed"
    AUDIO_STEM = "audio_stem"


class Widget(StrEnum):
    """Core/Web 拥有的渲染词汇；不够用时扩展词汇表，而不是让插件携带前端代码。"""

    TEXT = "text"
    PROMPT = "prompt"
    NUMBER = "number"
    SLIDER = "slider"
    ENUM = "enum"
    PRESET = "preset"
    TOGGLE = "toggle"
    SEED = "seed"
    AUDIO_STEM = "audio_stem"
    VECTOR = "vector"
    ASSET_SLOT = "asset_slot"
    ASSET_LIST = "asset_list"


class DomainPredicate(StrEnum):
    """manifest 默认规则可引用的少量领域谓词；不能执行任意表达式。"""

    SEGMENT_HAS_DIALOGUE = "segment.has_dialogue"


_SCALAR_WIDGETS = frozenset(
    {Widget.TEXT, Widget.PROMPT, Widget.NUMBER, Widget.SLIDER, Widget.ENUM, Widget.PRESET}
    | {Widget.TOGGLE, Widget.SEED, Widget.VECTOR}
)

JsonScalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class Option:
    id: str
    label: str

    def __post_init__(self) -> None:
        if not self.id or not self.label:
            raise ValueError("manifest 选项必须有 id 与 label。")


@dataclass(frozen=True, slots=True)
class Field:
    """设置或参数的一个字段：类型由 widget 决定，约束由下面的可选项声明。"""

    key: str
    widget: Widget
    label: str
    default: Any = None
    options: tuple[Option, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    max_length: int | None = None
    # 文本去掉首尾空白后的最小长度；1 表示不能为空白。
    min_length: int | None = None
    dimension: int | None = None
    component_labels: tuple[str, ...] = ()
    nullable: bool = False
    role: Role | None = None
    help: str = ""
    advanced: bool = False
    # 设置摘要里展示该字段：enum/preset 显示选项 label，toggle 为真时显示 summary_label。
    summary: bool = False
    summary_label: str | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.label:
            raise ValueError("manifest 字段必须有 key 与 label。")
        if self.widget not in _SCALAR_WIDGETS:
            raise ValueError(f"字段 {self.key} 不能使用 {self.widget.value} widget。")
        if self.widget in {Widget.ENUM, Widget.PRESET}:
            ids = [item.id for item in self.options]
            if not ids or len(ids) != len(set(ids)):
                raise ValueError(f"字段 {self.key} 的选项必须非空且不重复。")
        elif self.options:
            raise ValueError(f"字段 {self.key} 只有 enum/preset 可以声明选项。")
        if self.widget is Widget.VECTOR and (
            self.dimension is None
            or self.dimension < 1
            or (self.component_labels and len(self.component_labels) != self.dimension)
        ):
            raise ValueError(f"字段 {self.key} 的向量维度不合法。")
        # default 为 None 且不可空表示必填、没有默认值。
        if self.default is not None:
            self.validate(self.default)

    def validate(self, value: Any) -> Any:
        if value is None:
            if self.nullable:
                return None
            raise ValueError(f"{self.label}不能为空。")
        if self.widget in {Widget.ENUM, Widget.PRESET}:
            if not isinstance(value, str) or value not in {item.id for item in self.options}:
                raise ValueError(f"{self.label}的取值不受支持。")
            return value
        if self.widget is Widget.TOGGLE:
            if not isinstance(value, bool):
                raise ValueError(f"{self.label}必须是布尔值。")
            return value
        if self.widget in {Widget.TEXT, Widget.PROMPT}:
            if not isinstance(value, str) or (
                self.max_length is not None and len(value) > self.max_length
            ):
                raise ValueError(f"{self.label}必须是不超过 {self.max_length} 字的文本。")
            if self.min_length is not None and len(value.strip()) < self.min_length:
                raise ValueError(f"{self.label}不能为空。")
            return value
        if self.widget is Widget.SEED:
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**63:
                raise ValueError(f"{self.label}必须是 0 到 2^63-1 的整数。")
            return value
        if self.widget is Widget.VECTOR:
            if not isinstance(value, list) or len(value) != self.dimension:
                raise ValueError(f"{self.label}必须是 {self.dimension} 维数组。")
            return [self._number(item) for item in value]
        return self._number(value)

    def _number(self, value: Any) -> float | int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise ValueError(f"{self.label}必须是有限数值。")
        if (self.minimum is not None and value < self.minimum) or (
            self.maximum is not None and value > self.maximum
        ):
            raise ValueError(f"{self.label}超出允许范围。")
        return value

    def option_label(self, value: str) -> str:
        return next(item.label for item in self.options if item.id == value)

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "widget": self.widget.value,
            "label": self.label,
            "default": self.default,
            "nullable": self.nullable,
            "advanced": self.advanced,
            "options": [{"id": item.id, "label": item.label} for item in self.options],
            "minimum": self.minimum,
            "maximum": self.maximum,
            "max_length": self.max_length,
            "min_length": self.min_length,
            "dimension": self.dimension,
            "component_labels": list(self.component_labels),
            "role": None if self.role is None else self.role.value,
            "help": self.help,
        }


Describe = Literal["required", "optional", "none"]


@dataclass(frozen=True, slots=True)
class Slot:
    """recipe 的一个媒体输入槽：引用一个语义角色，并声明数量、媒体与说明约束。"""

    key: str
    role: Role
    label: str
    minimum: int = 0
    maximum: int = 1
    media_types: tuple[str, ...] = ()
    duration_seconds: tuple[float, float] | None = None
    describe: Describe = "none"
    unique: bool = True
    namespace: str | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.label:
            raise ValueError("manifest 槽位必须有 key 与 label。")
        if not 0 <= self.minimum <= self.maximum:
            raise ValueError(f"槽位 {self.key} 的数量范围不合法。")
        if self.duration_seconds is not None and not (
            0 < self.duration_seconds[0] <= self.duration_seconds[1]
        ):
            raise ValueError(f"槽位 {self.key} 的时长范围不合法。")

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "role": self.role.value,
            "label": self.label,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "media_types": list(self.media_types),
            "duration_seconds": (
                None if self.duration_seconds is None else list(self.duration_seconds)
            ),
            "describe": self.describe,
            "unique": self.unique,
            "namespace": self.namespace,
        }


@dataclass(frozen=True, slots=True)
class Recipe:
    """插件对某个 capability 的一种具体用法。"""

    id: str
    capability: Capability
    label: str
    slots: tuple[Slot, ...] = ()
    params: tuple[Field, ...] = ()
    require_any: tuple[str, ...] = ()
    label_namespaces: tuple[tuple[str, str], ...] = ()
    skills: tuple[str, ...] = ()
    distinct_slots: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        keys = [slot.key for slot in self.slots] + [item.key for item in self.params]
        if not self.id or len(keys) != len(set(keys)):
            raise ValueError(f"recipe {self.id} 的槽位与参数键必须唯一。")
        slot_keys = {slot.key for slot in self.slots}
        if any(key not in slot_keys for key in self.require_any):
            raise ValueError(f"recipe {self.id} 的 require_any 引用了未知槽位。")
        if any(key not in slot_keys for key in self.distinct_slots) or len(
            set(self.distinct_slots)
        ) != len(self.distinct_slots):
            raise ValueError(f"recipe {self.id} 的 distinct_slots 不合法。")
        object.__setattr__(self, "label_namespaces", tuple(sorted(self.label_namespaces)))
        namespaces = {name for name, _template in self.label_namespaces}
        if any(slot.namespace not in namespaces for slot in self.slots if slot.namespace):
            raise ValueError(f"recipe {self.id} 的槽位引用了未声明的标签命名空间。")

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capability": self.capability.value,
            "label": self.label,
            "slots": [slot.to_json() for slot in self.slots],
            "params": [item.to_json() for item in self.params],
            "require_any": list(self.require_any),
            "label_namespaces": dict(self.label_namespaces),
            "skills": list(self.skills),
            "distinct_slots": list(self.distinct_slots),
        }


@dataclass(frozen=True, slots=True)
class DefaultRule:
    """为 capability 选默认 recipe：第一条谓词成立（或无谓词）的规则生效。"""

    recipe: str
    when: DomainPredicate | None = None


_IMAGE_CAPABILITIES = frozenset({Capability.IMAGE_GENERATE, Capability.IMAGE_EDIT})


@dataclass(frozen=True, slots=True)
class ImagePromptConvention:
    """图片插件要求 Core 怎样编译输入图对应关系与画幅句；插件不改写 Core 文本。

    ``namespace`` 指向各图片 recipe 的 ``label_namespaces``，输入图按传入顺序编号；
    ``single_image_label`` 非空时，只有一张输入图就改用这个自然指代而不加标签；
    ``aspect_ratio_in_prompt`` 为 False 表示画幅由插件画布保证，Core 不在提示词里写画幅。
    未声明约定的图片插件使用 Core 默认中文编号与画幅句。
    """

    namespace: str
    single_image_label: str | None = None
    aspect_ratio_in_prompt: bool = True

    def __post_init__(self) -> None:
        if not self.namespace or self.single_image_label == "":
            raise ValueError("图片提示词约定不完整。")

    def to_json(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "single_image_label": self.single_image_label,
            "aspect_ratio_in_prompt": self.aspect_ratio_in_prompt,
        }


@dataclass(frozen=True, slots=True)
class PluginManifest:
    plugin_id: str
    plugin_version: int
    label: str
    recipes: tuple[Recipe, ...]
    settings: tuple[Field, ...] = ()
    hints: tuple[tuple[str, JsonScalar], ...] = ()
    defaults: tuple[tuple[Capability, tuple[DefaultRule, ...]], ...] = ()
    image_prompt: ImagePromptConvention | None = None

    def __post_init__(self) -> None:
        if not self.plugin_id or self.plugin_version < 1 or not self.label:
            raise ValueError("manifest 插件身份不完整。")
        recipe_ids = [recipe.id for recipe in self.recipes]
        if not recipe_ids or len(recipe_ids) != len(set(recipe_ids)):
            raise ValueError(f"插件 {self.plugin_id} 的 recipe 必须非空且不重复。")
        setting_keys = [item.key for item in self.settings]
        if len(setting_keys) != len(set(setting_keys)):
            raise ValueError(f"插件 {self.plugin_id} 的设置键必须唯一。")
        if any(item.default is None and not item.nullable for item in self.settings):
            raise ValueError(f"插件 {self.plugin_id} 的设置必须都有默认值。")
        for capability, rules in self.defaults:
            for rule in rules:
                recipe = self.recipe(rule.recipe)
                if recipe.capability is not capability:
                    raise ValueError(f"默认规则引用的 recipe {rule.recipe} 不实现 {capability}。")
        if self.image_prompt is not None:
            image_recipes = [
                item for item in self.recipes if item.capability in _IMAGE_CAPABILITIES
            ]
            if not image_recipes or any(
                self.image_prompt.namespace not in dict(recipe.label_namespaces)
                or any(slot.namespace != self.image_prompt.namespace for slot in recipe.slots)
                for recipe in image_recipes
            ):
                raise ValueError(
                    f"插件 {self.plugin_id} 的图片提示词约定必须覆盖每个图片 recipe 的全部槽位。"
                )

    def image_input_label(self, recipe_id: str, index: int, total: int) -> str | None:
        """按约定给第 index 张（从 1 起）输入图的指代；未声明约定时为 None，由 Core 用默认写法。"""
        convention = self.image_prompt
        if convention is None:
            return None
        if total == 1 and convention.single_image_label is not None:
            return convention.single_image_label
        template = dict(self.recipe(recipe_id).label_namespaces)[convention.namespace]
        return template.format(n=index)

    @property
    def capabilities(self) -> tuple[Capability, ...]:
        return tuple(dict.fromkeys(recipe.capability for recipe in self.recipes))

    def recipe(self, recipe_id: str) -> Recipe:
        for recipe in self.recipes:
            if recipe.id == recipe_id:
                return recipe
        raise ValueError(f"插件 {self.plugin_id} 没有 recipe {recipe_id}。")

    def hint(self, key: str) -> JsonScalar:
        return dict(self.hints).get(key)

    def default_settings(self) -> dict[str, Any]:
        return {item.key: item.default for item in self.settings}

    def validate_settings(self, value: object) -> dict[str, Any]:
        """完整设置对象：缺键、多键或取值不合法都拒绝。"""
        if not isinstance(value, dict):
            raise ValueError("插件设置必须是 JSON 对象。")
        expected = {item.key for item in self.settings}
        if set(value) != expected:
            missing = sorted(expected - set(value))
            extra = sorted(set(value) - expected)
            detail = "；".join(
                part
                for part in (
                    f"缺少 {', '.join(missing)}" if missing else "",
                    f"多出 {', '.join(extra)}" if extra else "",
                )
                if part
            )
            raise ValueError(f"{self.label} 设置字段不匹配：{detail}。")
        return {item.key: item.validate(value[item.key]) for item in self.settings}

    def settings_summary(self, values: dict[str, Any]) -> str:
        parts = []
        for item in self.settings:
            if not item.summary:
                continue
            value = values.get(item.key)
            if item.widget in {Widget.ENUM, Widget.PRESET} and isinstance(value, str):
                parts.append(item.option_label(value))
            elif item.widget is Widget.TOGGLE and value is True:
                parts.append(item.summary_label or item.label)
        return " · ".join(parts)

    def to_json(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "label": self.label,
            "settings": [item.to_json() for item in self.settings],
            "hints": dict(self.hints),
            "recipes": [recipe.to_json() for recipe in self.recipes],
            "defaults": {
                capability.value: [
                    {"recipe": rule.recipe, "when": None if rule.when is None else rule.when.value}
                    for rule in rules
                ]
                for capability, rules in self.defaults
            },
            "image_prompt": None if self.image_prompt is None else self.image_prompt.to_json(),
        }


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    """提交时实际使用的插件、recipe 与生效设置；写进 Generation 供追溯，不参与失效判断。"""

    plugin_id: str
    recipe_id: str
    settings: tuple[tuple[str, JsonScalar], ...] = field(default=())
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.plugin_id or not self.recipe_id:
            raise ValueError("provider_snapshot 必须有 plugin_id 与 recipe_id。")
        keys = [key for key, _value in self.settings]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("provider_snapshot.settings 必须按键排序且不重复。")
        for _key, value in self.settings:
            if value is not None and not isinstance(value, str | int | float | bool):
                raise ValueError("provider_snapshot.settings 只能保存 JSON 标量。")
        if len(self.summary) > 500:
            raise ValueError("provider_snapshot.summary 过长。")

    @classmethod
    def build(
        cls, manifest: PluginManifest, recipe_id: str, values: dict[str, Any]
    ) -> ProviderSnapshot:
        manifest.recipe(recipe_id)
        return cls(
            manifest.plugin_id,
            recipe_id,
            tuple(sorted(values.items())),
            manifest.settings_summary(values),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "recipe_id": self.recipe_id,
            "settings": dict(self.settings),
            "summary": self.summary,
        }

    @classmethod
    def from_json(cls, value: object) -> ProviderSnapshot:
        if not isinstance(value, dict) or set(value) != {
            "plugin_id",
            "recipe_id",
            "settings",
            "summary",
        }:
            raise ValueError("provider_snapshot 字段不合法。")
        settings = value["settings"]
        if (
            not isinstance(value["plugin_id"], str)
            or not isinstance(value["recipe_id"], str)
            or not isinstance(settings, dict)
            or not isinstance(value["summary"], str)
        ):
            raise ValueError("provider_snapshot 字段类型不合法。")
        return cls(
            value["plugin_id"],
            value["recipe_id"],
            tuple(sorted(settings.items())),
            value["summary"],
        )


# ---------------------------------------------------------------------------
# 常用字段：同一语义角色在不同插件里保持同样的 key 与 widget。
# ---------------------------------------------------------------------------

IMAGE_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp")


def prompt_field(max_length: int, label: str = "提示词") -> Field:
    return Field(
        "prompt", Widget.PROMPT, label, min_length=1, max_length=max_length, role=Role.PROMPT
    )


def seed_field() -> Field:
    return Field("seed", Widget.SEED, "Seed", default=42, role=Role.SEED)


# 图片比例词汇（与 Qwen 官方提示词模板一致）：项目画幅之外，角色参考图可选这些比例；
# 地点全景图固定为 2:1。
IMAGE_ASPECT_RATIOS = (
    "16:9",
    "9:16",
    "2:1",
    "1:2",
    "1:1",
    "3:2",
    "2:3",
    "4:3",
    "3:4",
    "5:4",
    "4:5",
    "21:9",
    "9:21",
    "3:1",
    "1:3",
)


def image_aspect_ratio_field() -> Field:
    return Field(
        "aspect_ratio",
        Widget.ENUM,
        "画面比例",
        default="16:9",
        options=tuple(Option(value, value) for value in IMAGE_ASPECT_RATIOS),
        role=Role.ASPECT_RATIO,
    )


def aspect_ratio_field() -> Field:
    return Field(
        "aspect_ratio",
        Widget.ENUM,
        "画面比例",
        default="16:9",
        options=(Option("16:9", "16:9"), Option("9:16", "9:16"), Option("2:1", "2:1")),
        role=Role.ASPECT_RATIO,
    )


def recipe_from_json(value):
    if not isinstance(value, dict) or set(value) != {
        "id",
        "capability",
        "label",
        "slots",
        "params",
        "require_any",
        "label_namespaces",
        "skills",
        "distinct_slots",
    }:
        raise ValueError("recipe 声明缺少字段或包含未声明字段。")
    for item in value["params"]:
        if not isinstance(item, dict) or set(item) != set(
            Field("contract", Widget.TEXT, "契约").to_json()
        ):
            raise ValueError("recipe 参数声明不合法。")
    for item in value["slots"]:
        if not isinstance(item, dict) or set(item) != set(
            Slot("contract", Role.FIRST_FRAME, "契约").to_json()
        ):
            raise ValueError("recipe 槽位声明不合法。")
    fields = tuple(
        Field(
            item["key"],
            Widget(item["widget"]),
            item["label"],
            default=item["default"],
            nullable=item["nullable"],
            role=None if item["role"] is None else Role(item["role"]),
            minimum=item["minimum"],
            maximum=item["maximum"],
            max_length=item["max_length"],
            min_length=item["min_length"],
            options=tuple(Option(option["id"], option["label"]) for option in item["options"]),
            dimension=item["dimension"],
            component_labels=tuple(item["component_labels"]),
            help=item["help"],
            advanced=item["advanced"],
        )
        for item in value["params"]
    )
    slots = tuple(
        Slot(
            item["key"],
            Role(item["role"]),
            item["label"],
            minimum=item["minimum"],
            maximum=item["maximum"],
            media_types=tuple(item["media_types"]),
            duration_seconds=None
            if item["duration_seconds"] is None
            else tuple(item["duration_seconds"]),
            describe=item["describe"],
            unique=item["unique"],
            namespace=item["namespace"],
        )
        for item in value["slots"]
    )
    return Recipe(
        value["id"],
        Capability(value["capability"]),
        value["label"],
        slots=slots,
        params=fields,
        require_any=tuple(value["require_any"]),
        label_namespaces=tuple(sorted(value["label_namespaces"].items())),
        skills=tuple(value["skills"]),
        distinct_slots=tuple(value["distinct_slots"]),
    )
