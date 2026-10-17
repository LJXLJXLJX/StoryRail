"""地点主图与视图生成的依赖检查、实际输入映射与提示词编译。

- 主图：室内固定 2:1 等距柱状全景，室外使用项目画幅；固定陈设有方位时按方位描述。
- 室内视图：没有与当前主图、当前几何一致的裁切时只能先裁切；裁切有效后细化，
  底图 = 裁切图，参考 = 主图 + 参考视图已选图。
- 室外视图：edit 转向，底图 = 主图已选图，Core 写明相对主图的转向角与景别。

“画面中可见”目前只列陈设描述与视图 purpose，不按几何筛选陈设或计算主光相对方向。
输入图指代与是否写画幅句跟随当前图片插件的 `image_prompt` 约定；画幅最多写一次。
"""

from __future__ import annotations

from dataclasses import dataclass

from .image_inputs import ImageInput, ImageInputs, ordered_image_inputs
from .image_prompt_style import DEFAULT_IMAGE_PROMPT_STYLE, ImagePromptStyle
from .models import (
    GenerationOperation,
    Location,
    LocationCropRequest,
    LocationKind,
    LocationView,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
)

INTERIOR_MASTER_ASPECT_RATIO = "2:1"

_DIRECTIONS = ("正前方", "右前方", "右侧", "右后方", "身后", "左后方", "左侧", "左前方")


@dataclass(frozen=True, slots=True)
class LocationMasterPlan:
    location: Location
    inputs: ImageInputs
    # None 表示跟随项目画幅（室外）。
    aspect_ratio: str | None


@dataclass(frozen=True, slots=True)
class LocationViewPlan:
    """生成视图的下一步：`crop` 非空表示必须先裁切；否则 `inputs` 是细化或转向的实际输入。"""

    location: Location
    view: LocationView
    crop: LocationCropRequest | None
    inputs: ImageInputs | None


def find_location(document: StructuredDirectorDocument, location_id: str) -> Location:
    location = document.location_library.location(location_id)
    if location is None:
        raise ValueError("地点不存在。")
    return location


def find_location_view(
    document: StructuredDirectorDocument, view_id: str
) -> tuple[Location, LocationView]:
    owner = document.location_library.view_owner(view_id)
    if owner is None:
        raise ValueError("地点视图不存在。")
    return owner


def location_master_plan(
    document: StructuredDirectorDocument, location_id: str
) -> LocationMasterPlan:
    location = find_location(document, location_id)
    if not location.master.prompt_text.strip():
        raise ValueError(f"请先填写地点「{location.name}」的主图提示词。")
    assets = {item.id: item for item in document.assets}
    entries: list[ImageInput] = []
    for asset_id in location.master.reference_asset_ids:
        asset = assets.get(asset_id)
        if asset is None or not asset.media_type.startswith("image/"):
            raise ValueError("地点主图参考必须是项目内图片 Asset。")
        entries.append(
            ImageInput(
                asset_id,
                "主图参考",
                "主图参考；只参考风格、材质与陈设外观，不复制其构图或投影方式。",
            )
        )
    interior = location.kind is LocationKind.INTERIOR
    return LocationMasterPlan(
        location,
        ordered_image_inputs(
            document, entries, operation=GenerationOperation.GENERATE, label="地点主图的参考图"
        ),
        INTERIOR_MASTER_ASPECT_RATIO if interior else None,
    )


def location_view_plan(document: StructuredDirectorDocument, view_id: str) -> LocationViewPlan:
    """校验前置并决定下一步；前置不满足时抛出可展示的中文原因。"""
    location, view = find_location_view(document, view_id)
    master = location.master.selected_asset_id
    if master is None:
        raise ValueError(f"请先选择地点「{location.name}」的主图，再生成视图。")
    if location.view_yaw(view) is None:
        fixture = location.fixture(view.look_at_fixture_id or "")
        raise ValueError(
            f"视图「{view.name}」朝向陈设「{fixture.name if fixture else '未知'}」，"
            "该陈设尚未在当前主图上标定方位，暂不能生成。"
        )
    references: list[ImageInput] = []
    for reference_id in view.reference_view_ids:
        reference = location.view(reference_id)
        if reference is None or reference.selected_asset_id is None:
            name = reference.name if reference is not None else reference_id
            raise ValueError(f"参考视图「{name}」尚未选择图片，请先完成它再生成「{view.name}」。")
        references.append(
            ImageInput(
                reference.selected_asset_id,
                f"参考视图「{reference.name}」",
                f"同一地点已选定的视图「{reference.name}」；保持材质、陈设外观与光线一致，"
                "不复制其构图。",
            )
        )
    if location.kind is LocationKind.INTERIOR:
        crop = location.crop_request(view, document.aspect_ratio.value)
        assert crop is not None
        if not crop_is_current(document, location, view):
            return LocationViewPlan(location, view, crop, None)
        assert view.crop_asset_id is not None
        source = view.crop_asset_id
        entries = [
            ImageInput(
                view.crop_asset_id,
                "裁切底图",
                f"视图「{view.name}」的底图；本次只对它做空间扭曲与清晰度修复，取景意图以它为准。",
            ),
        ]
    else:
        source = master
        entries = [
            ImageInput(
                master,
                "主图底图",
                f"地点「{location.name}」的主图；这是本次图片编辑的底图，机位转向以它为基准。",
            )
        ]
    inputs = ordered_image_inputs(
        document,
        [*entries, *references],
        operation=GenerationOperation.EDIT,
        label=f"视图「{view.name}」",
        source_asset_id=source,
    )
    return LocationViewPlan(location, view, None, inputs)


def crop_is_current(
    document: StructuredDirectorDocument, location: Location, view: LocationView
) -> bool:
    """视图已有裁切，且产出它的裁切任务仍对应当前主图与当前几何。"""
    if view.crop_asset_id is None:
        return False
    source = _crop_generation(document, view.id, view.crop_asset_id)
    return source is not None and source.location_crop_request == location.crop_request(
        view, document.aspect_ratio.value
    )


def _crop_generation(
    document: StructuredDirectorDocument, view_id: str, asset_id: str
) -> ReferenceGeneration | None:
    return next(
        (
            item
            for item in reversed(document.generations)
            if item.kind is ReferenceGenerationKind.LOCATION_VIEW_CROP
            and item.target_id == view_id
            and item.phase is ReferenceGenerationPhase.SUCCEEDED
            and item.output_asset_id == asset_id
        ),
        None,
    )


# ---------------------------------------------------------------------------
# 提示词编译
# ---------------------------------------------------------------------------


def location_master_prompt(
    document: StructuredDirectorDocument,
    plan: LocationMasterPlan,
    style: ImagePromptStyle = DEFAULT_IMAGE_PROMPT_STYLE,
) -> str:
    location = plan.location
    if location.kind is LocationKind.INTERIOR:
        rule = (
            "地点主图硬约束：生成一张 360°×180° 等距柱状投影（equirectangular）室内全景；"
            "画面中不得出现任何人物、文字或水印；全景左右边缘必须无缝衔接；"
            "地平线位于画面垂直正中，方位 0° 位于画面水平正中，向右为顺时针。"
        )
    else:
        rule = (
            "地点主图硬约束：生成一张外景地点的单一静态画面；画面中不得出现任何人物、文字或水印；"
            "本画面是后续机位转向的基准，方位 0° 即本画面正前方。"
        )
    aspect = plan.aspect_ratio or document.aspect_ratio.value
    return (
        _mapping_block(plan.inputs, style)
        + _aspect_sentence(aspect, style)
        + rule
        + "\n\n"
        + _space_block(location, with_azimuth=True)
        + "\n\n主图创作正文：\n"
        + location.master.prompt_text.strip()
    )


def location_view_prompt(
    document: StructuredDirectorDocument,
    plan: LocationViewPlan,
    style: ImagePromptStyle = DEFAULT_IMAGE_PROMPT_STYLE,
) -> str:
    location, view = plan.location, plan.view
    assert plan.inputs is not None
    state = next((item for item in location.states if item.id == view.state_id), None)
    if location.kind is LocationKind.INTERIOR:
        # 细化修复全景投影产生的空间扭曲与清晰度问题；不附空间描述、陈设清单或正文，
        # 避免编辑模型借机重画整个空间。
        prompt = (
            _mapping_block(plan.inputs, style)
            + _aspect_sentence(document.aspect_ratio.value, style)
            + "修复全景裁切底图，不是重新创作：保持取景中心、镜头朝向、景别、主体层次，以及"
            "每个物体的身份、数量和相互位置关系；重点解决等距柱状全景转为透视图后产生的空间扭曲，"
            "包括建筑结构或直线弯曲、画面边缘拉伸、物体比例失衡和不自然透视，使水平线、垂直线、"
            "平面和纵深关系恢复为可信的单一透视；为修正这些问题，允许对物体轮廓、局部尺度和边缘位置"
            "作必要调整，但不得改变空间布局、把主体移动到别处、增删物体或改换机位；同时去除模糊并"
            "补足材质纹理与细节；画面中不得出现任何人物、文字或水印。"
        )
        if state is not None:
            prompt += (
                f"\n\n本视图状态「{state.name}」：{state.description.strip()}"
                "（只在底图上叠加该状态的可见差量，构图不变）"
            )
        return prompt
    rule = (
        "视图转向硬约束：保持同一地点的建筑、地形、材质、天气与光线一致；"
        "画面中不得出现任何人物、文字或水印。"
    )
    camera = "\n" + _turn_sentence(location, view)
    lines = [f"视图用途：{view.purpose.strip()}"]
    if view.look_at_fixture_id is not None:
        fixture = location.fixture(view.look_at_fixture_id)
        if fixture is not None:
            lines.append(f"机位朝向：陈设「{fixture.name}」，偏转 {view.yaw_offset_deg:+g}°。")
    if location.fixtures:
        lines.append(
            "可能出现在画面中的固定陈设（以底图实际可见为准，不得挪动）：\n"
            + "\n".join(_fixture_line(item, with_azimuth=False) for item in location.fixtures)
        )
    if location.key_light is not None:
        lines.append(f"主光：{location.key_light.description.strip()}")
    if state is not None:
        lines.append(
            f"本视图状态「{state.name}」：{state.description.strip()}"
            "（只叠加该状态的可见差量，固定结构不变）"
        )
    body = (
        "\n\n视图转向正文：\n" + view.refine_prompt_text.strip()
        if view.refine_prompt_text.strip()
        else ""
    )
    return (
        _mapping_block(plan.inputs, style)
        + _aspect_sentence(document.aspect_ratio.value, style)
        + rule
        + camera
        + "\n\n"
        + _space_block(location, with_azimuth=False, with_fixtures=False)
        + "\n"
        + "\n".join(lines)
        + body
    )


def crop_prompt_text(crop: LocationCropRequest) -> str:
    """裁切 Generation 的说明正文；只含几何，参与重试签名。"""
    return (
        f"从地点主图全景裁切：yaw {crop.yaw_deg:g}°、pitch {crop.pitch_deg:g}°、"
        f"水平视场角 {crop.hfov_deg:g}°、画幅 {crop.aspect_ratio}。"
    )


def _mapping_block(inputs: ImageInputs, style: ImagePromptStyle) -> str:
    lines = inputs.lines(style)
    if not lines:
        return ""
    return "输入图对应关系（按实际传入顺序）：\n" + "\n".join(lines) + "\n\n"


def _aspect_sentence(aspect_ratio: str, style: ImagePromptStyle) -> str:
    # 画幅由插件画布保证时不写画幅句，避免提示词与画布形成两个来源。
    return f"固定画幅：{aspect_ratio}。" if style.aspect_ratio_in_prompt else ""


def _space_block(location: Location, *, with_azimuth: bool, with_fixtures: bool = True) -> str:
    lines = [f"地点「{location.name}」固定空间：{location.description.strip() or '（未描述）'}"]
    if with_fixtures and location.fixtures:
        heading = (
            "固定陈设（方位以主图正中为 0°，顺时针）："
            if with_azimuth and any(item.azimuth_deg is not None for item in location.fixtures)
            else "固定陈设："
        )
        lines.append(
            heading
            + "\n"
            + "\n".join(
                _fixture_line(item, with_azimuth=with_azimuth) for item in location.fixtures
            )
        )
    if with_azimuth and location.key_light is not None:
        light = location.key_light
        where = "" if light.azimuth_deg is None else f"（来自{_direction(light.azimuth_deg)}）"
        lines.append(f"主光：{light.description.strip()}{where}")
    return "\n".join(lines)


def _fixture_line(fixture, *, with_azimuth: bool) -> str:
    where = (
        f"：{_direction(fixture.azimuth_deg)}"
        if with_azimuth and fixture.azimuth_deg is not None
        else ""
    )
    description = f"；{fixture.description.strip()}" if fixture.description.strip() else ""
    return f"- {fixture.name}{where}{description}"


def _direction(azimuth_deg: float) -> str:
    return f"{_DIRECTIONS[round(azimuth_deg / 45) % 8]}，方位 {azimuth_deg:g}°"


def _turn_sentence(location: Location, view: LocationView) -> str:
    yaw = location.view_yaw(view)
    assert yaw is not None
    if yaw == 0:
        turn = "保持主图朝向"
    elif yaw <= 180:
        turn = f"水平向右转 {yaw:g}°"
    else:
        turn = f"水平向左转 {360 - yaw:g}°"
    pitch = view.pitch_deg
    tilt = "平视" if pitch == 0 else f"抬头 {pitch:g}°" if pitch > 0 else f"低头 {-pitch:g}°"
    size = _shot_size(view.hfov_deg)
    return f"机位相对主图：{turn}，{tilt}；景别：{size}（水平视场角约 {view.hfov_deg:g}°）。"


def _shot_size(hfov_deg: float) -> str:
    if hfov_deg >= 90:
        return "广角远景"
    if hfov_deg >= 60:
        return "远景"
    if hfov_deg >= 40:
        return "中景"
    return "近景"


# ---------------------------------------------------------------------------
# 成套批次（location.generate_set）的单轮分类
# ---------------------------------------------------------------------------
#
# 纯读模型：批次波次提交与批次观察共用同一份分类，避免两处各自判断。
# status 取值：
#   ready                本轮可提交（step 指明提交 master / crop / view）
#   in_progress          同一目标已有非终态地点任务（进行中）
#   submission_uncertain 此前提交结果不确定，需要先核查
#   awaiting_selection   已有成功、未隐藏、未选择的候选，等待人类选择
#   awaiting_master      视图等待所在地点的主图选定
#   awaiting_calibration 相对陈设的视图尚未在当前主图上标定方位
#   awaiting_reference_view  参考视图尚未选定
#   failed / cancelled   此前任务失败或已取消，不自动重试
#   blocked              其它前置不满足（原因在 reason）
#   already_selected     已选定，成套完成
#   target_missing       地点已被删除

LOCATION_SET_TERMINAL = frozenset({"already_selected", "target_missing", "failed", "cancelled"})


@dataclass(frozen=True, slots=True)
class LocationSetItem:
    """成套批次的一个生成单元：地点主图（view_id 为 None）或单个视图。"""

    location_id: str
    view_id: str | None
    label: str
    status: str
    reason: str | None
    step: str | None

    @property
    def target_id(self) -> str:
        """Generation 目标：主图 = 地点 ID，裁切/细化/转向 = 视图 ID（与 05 冲突检测一致）。"""
        return self.view_id if self.view_id is not None else self.location_id


_LOCATION_VIEW_KINDS = {
    ReferenceGenerationKind.LOCATION_VIEW_CROP,
    ReferenceGenerationKind.LOCATION_VIEW_IMAGE,
}

# SUBMISSION_UNCERTAIN 不算终态：先单独报告，不落到 in_progress。
_SET_TERMINAL_PHASES = {
    ReferenceGenerationPhase.SUCCEEDED,
    ReferenceGenerationPhase.FAILED,
    ReferenceGenerationPhase.CANCELLED,
}


def location_set_items(
    document: StructuredDirectorDocument,
    location_ids: tuple[str, ...],
    *,
    generations_by_target=None,
    asset_ids=None,
) -> tuple[LocationSetItem, ...]:
    """按固定地点范围分类每个生成单元的当前状态；地点已删除时报告 target_missing。"""
    if generations_by_target is None:
        generations_by_target = {}
        for generation in document.generations:
            generations_by_target.setdefault(generation.target_id, []).append(generation)
    if asset_ids is None:
        asset_ids = {asset.id for asset in document.assets}
    items: list[LocationSetItem] = []
    for location_id in location_ids:
        location = document.location_library.location(location_id)
        if location is None:
            items.append(
                LocationSetItem(location_id, None, "", "target_missing", "地点已不存在。", None)
            )
            continue
        items.append(_master_set_item(document, location, generations_by_target, asset_ids))
        master_selected = location.master.selected_asset_id is not None
        for view in location.views:
            items.append(
                _view_set_item(
                    document, location, view, master_selected, generations_by_target, asset_ids
                )
            )
    return tuple(items)


def _location_generation_status(
    document: StructuredDirectorDocument,
    kinds: set[ReferenceGenerationKind],
    target_id: str,
    *,
    candidate_kinds: set[ReferenceGenerationKind],
    selection_done: bool,
    generations_by_target,
    asset_ids,
) -> str | None:
    """Generation 维度的状态；返回 None 表示没有进行中/历史任务需要优先报告。"""
    generations = [item for item in generations_by_target.get(target_id, ()) if item.kind in kinds]
    if any(item.phase not in _SET_TERMINAL_PHASES for item in generations):
        if any(item.phase is ReferenceGenerationPhase.SUBMISSION_UNCERTAIN for item in generations):
            return "submission_uncertain"
        return "in_progress"
    if not selection_done and any(
        item.kind in candidate_kinds
        and item.phase is ReferenceGenerationPhase.SUCCEEDED
        and not item.dismissed
        and item.output_asset_id in asset_ids
        for item in generations
    ):
        return "awaiting_selection"
    latest_failed = next(
        (
            item
            for item in reversed(generations)
            if not item.dismissed
            and item.phase in {ReferenceGenerationPhase.FAILED, ReferenceGenerationPhase.CANCELLED}
        ),
        None,
    )
    if latest_failed is not None:
        return latest_failed.phase.value
    return None


def _master_set_item(
    document: StructuredDirectorDocument, location: Location, generations_by_target, asset_ids
) -> LocationSetItem:
    label = f"地点「{location.name}」主图"
    if location.master.selected_asset_id is not None:
        return LocationSetItem(location.id, None, label, "already_selected", None, None)
    generation_status = _location_generation_status(
        document,
        {ReferenceGenerationKind.LOCATION_MASTER_IMAGE},
        location.id,
        candidate_kinds={ReferenceGenerationKind.LOCATION_MASTER_IMAGE},
        selection_done=False,
        generations_by_target=generations_by_target,
        asset_ids=asset_ids,
    )
    if generation_status is not None:
        reasons = {
            "in_progress": "已有进行中的主图任务。",
            "submission_uncertain": "此前提交状态不确定，需要先核查原任务。",
            "awaiting_selection": "已有成功候选，等待选择主图。",
            "failed": "此前主图任务失败，未自动重试；请明确重试对应 Generation。",
            "cancelled": "此前主图任务已取消，未自动重试；请明确重试对应 Generation。",
        }
        return LocationSetItem(
            location.id, None, label, generation_status, reasons[generation_status], None
        )
    try:
        location_master_plan(document, location.id)
    except ValueError as exc:
        return LocationSetItem(location.id, None, label, "blocked", str(exc), None)
    return LocationSetItem(location.id, None, label, "ready", None, "master")


def _view_set_item(
    document: StructuredDirectorDocument,
    location: Location,
    view: LocationView,
    master_selected: bool,
    generations_by_target,
    asset_ids,
) -> LocationSetItem:
    label = f"地点「{location.name}」视图「{view.name}」"
    if view.selected_asset_id is not None:
        return LocationSetItem(location.id, view.id, label, "already_selected", None, None)
    if not master_selected:
        return LocationSetItem(
            location.id, view.id, label, "awaiting_master", "主图尚未选定。", None
        )
    generation_status = _location_generation_status(
        document,
        _LOCATION_VIEW_KINDS,
        view.id,
        candidate_kinds={ReferenceGenerationKind.LOCATION_VIEW_IMAGE},
        selection_done=False,
        generations_by_target=generations_by_target,
        asset_ids=asset_ids,
    )
    if generation_status is not None:
        reasons = {
            "in_progress": "已有进行中的生成任务。",
            "submission_uncertain": "此前提交状态不确定，需要先核查原任务。",
            "awaiting_selection": "已有成功候选，等待选择视图图片。",
            "failed": "此前任务失败，未自动重试；请明确重试对应 Generation。",
            "cancelled": "此前任务已取消，未自动重试；请明确重试对应 Generation。",
        }
        return LocationSetItem(
            location.id, view.id, label, generation_status, reasons[generation_status], None
        )
    if location.view_yaw(view) is None:
        fixture = location.fixture(view.look_at_fixture_id or "")
        return LocationSetItem(
            location.id,
            view.id,
            label,
            "awaiting_calibration",
            f"朝向陈设「{fixture.name if fixture else '未知'}」尚未在当前主图上标定方位。",
            None,
        )
    unselected = [
        reference.name
        for reference_id in view.reference_view_ids
        if (reference := location.view(reference_id)) is None or reference.selected_asset_id is None
    ]
    if unselected:
        return LocationSetItem(
            location.id,
            view.id,
            label,
            "awaiting_reference_view",
            "等待参考视图选择：" + "、".join(f"「{name}」" for name in unselected) + "。",
            None,
        )
    try:
        plan = location_view_plan(document, view.id)
    except ValueError as exc:
        return LocationSetItem(location.id, view.id, label, "blocked", str(exc), None)
    step = "crop" if plan.crop is not None else "view"
    return LocationSetItem(location.id, view.id, label, "ready", None, step)
