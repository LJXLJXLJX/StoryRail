"""独立地点图片的生成、全景取景与批次分类。"""

from __future__ import annotations

from dataclasses import dataclass

from .image_inputs import ImageInput, ImageInputs, ordered_image_inputs
from .image_prompt_style import DEFAULT_IMAGE_PROMPT_STYLE, ImagePromptStyle
from .models import (
    GenerationOperation,
    Location,
    LocationImage,
    LocationImageKind,
    PanoramaCaptureRequest,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
)

PANORAMA_ASPECT_RATIO = "2:1"


@dataclass(frozen=True, slots=True)
class LocationImagePlan:
    location: Location
    image: LocationImage
    inputs: ImageInputs
    aspect_ratio: str | None


def find_location(document: StructuredDirectorDocument, location_id: str) -> Location:
    location = document.location_library.location(location_id)
    if location is None:
        raise ValueError("地点不存在。")
    return location


def find_location_image(
    document: StructuredDirectorDocument, image_id: str
) -> tuple[Location, LocationImage]:
    owner = document.location_library.image_owner(image_id)
    if owner is None:
        raise ValueError("地点图片不存在。")
    return owner


def location_image_plan(document: StructuredDirectorDocument, image_id: str) -> LocationImagePlan:
    location, image = find_location_image(document, image_id)
    if image.source is not None:
        raise ValueError("全景取景图片请使用确定性的取景入口，不能提交图片模型。")
    if not image.prompt_text.strip():
        raise ValueError(f"请先填写地点图片「{image.name}」的生成提示词。")
    assets = {item.id: item for item in document.assets}
    descriptions = {
        item.selected_asset_id: (owner.name, item.name, item.description)
        for owner in document.location_library.locations
        for item in owner.images
        if item.selected_asset_id is not None
    }
    entries: list[ImageInput] = []
    for asset_id in image.reference_asset_ids:
        asset = assets.get(asset_id)
        if asset is None or not asset.media_type.startswith("image/"):
            raise ValueError("地点图片参考必须是项目内图片 Asset。")
        described = descriptions.get(asset_id)
        entries.append(
            ImageInput(
                asset_id,
                "地点参考" if described is not None else "图片参考",
                (
                    f"地点「{described[0]}」图片「{described[1]}」：{described[2]}"
                    if described is not None
                    else "用户显式选择的图片参考；仅使用与本次创作目标相关的视觉信息。"
                ),
            )
        )
    return LocationImagePlan(
        location,
        image,
        ordered_image_inputs(
            document,
            entries,
            operation=GenerationOperation.GENERATE,
            label=f"地点图片「{image.name}」的显式参考图",
        ),
        (
            PANORAMA_ASPECT_RATIO
            if image.kind is LocationImageKind.PANORAMA
            else document.aspect_ratio.value
        ),
    )


def panorama_capture_request(
    document: StructuredDirectorDocument, image_id: str
) -> PanoramaCaptureRequest:
    location, image = find_location_image(document, image_id)
    source = image.source
    if source is None:
        raise ValueError("该地点图片没有全景取景来源。")
    panorama = location.image(source.panorama_image_id)
    if panorama is None or panorama.kind is not LocationImageKind.PANORAMA:
        raise ValueError("全景来源不属于当前地点或已不存在。")
    if panorama.selected_asset_id is None:
        raise ValueError(f"全景图「{panorama.name}」尚未选择图片。")
    return PanoramaCaptureRequest(
        panorama.selected_asset_id,
        source.yaw_deg,
        source.pitch_deg,
        source.hfov_deg,
        document.aspect_ratio.value,
    )


def location_image_prompt(
    document: StructuredDirectorDocument,
    plan: LocationImagePlan,
    style: ImagePromptStyle = DEFAULT_IMAGE_PROMPT_STYLE,
) -> str:
    location, image = plan.location, plan.image
    mapping = plan.inputs.lines(style)
    prefix = "输入图对应关系（按实际传入顺序）：\n" + "\n".join(mapping) + "\n\n" if mapping else ""
    aspect = plan.aspect_ratio or document.aspect_ratio.value
    aspect_sentence = f"固定画幅：{aspect}。" if style.aspect_ratio_in_prompt else ""
    if image.kind is LocationImageKind.PANORAMA:
        rule = (
            "地点全景图硬约束：生成一张 360°×180° 等距柱状投影（equirectangular）全景；"
            "左右边缘必须无缝衔接，地平线位于画面垂直正中；不得出现文字或水印。"
        )
    else:
        rule = "地点图片硬约束：生成一张单一静态画面，不得生成拼图、文字或水印。"
    fixtures = ""
    if location.fixtures:
        fixtures = "\n固定陈设：\n" + "\n".join(
            f"- {item.name}" + (f"：{item.description}" if item.description else "")
            for item in location.fixtures
        )
    light = "" if location.key_light is None else f"\n主光：{location.key_light.description}"
    return (
        prefix
        + aspect_sentence
        + rule
        + f"\n地点「{location.name}」：{location.description or '（未补充总体说明）'}"
        + fixtures
        + light
        + f"\n本图片实际内容说明目标：{image.description}"
        + "\n\n图片创作正文：\n"
        + image.prompt_text.strip()
    )


def capture_prompt_text(capture: PanoramaCaptureRequest) -> str:
    return (
        f"从地点全景图截取当前视角：yaw {capture.yaw_deg:g}°、"
        f"pitch {capture.pitch_deg:g}°、水平视场角 {capture.hfov_deg:g}°、"
        f"画幅 {capture.aspect_ratio}。"
    )


LOCATION_SET_TERMINAL = frozenset({"already_selected", "target_missing", "failed", "cancelled"})


@dataclass(frozen=True, slots=True)
class LocationSetItem:
    location_id: str
    image_id: str | None
    label: str
    status: str
    reason: str | None
    step: str | None

    @property
    def target_id(self) -> str:
        return self.image_id if self.image_id is not None else self.location_id


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
        for image in location.images:
            items.append(
                _image_set_item(
                    document,
                    location,
                    image,
                    generations_by_target,
                    asset_ids,
                )
            )
    return tuple(items)


def _image_set_item(
    document: StructuredDirectorDocument,
    location: Location,
    image: LocationImage,
    generations_by_target,
    asset_ids,
) -> LocationSetItem:
    label = f"地点「{location.name}」图片「{image.name}」"
    if image.selected_asset_id is not None:
        return LocationSetItem(location.id, image.id, label, "already_selected", None, None)
    kinds = {
        ReferenceGenerationKind.PANORAMA_CAPTURE
        if image.source is not None
        else ReferenceGenerationKind.LOCATION_IMAGE
    }
    generations = [item for item in generations_by_target.get(image.id, ()) if item.kind in kinds]
    if any(item.phase not in _SET_TERMINAL_PHASES for item in generations):
        status = (
            "submission_uncertain"
            if any(
                item.phase is ReferenceGenerationPhase.SUBMISSION_UNCERTAIN for item in generations
            )
            else "in_progress"
        )
        return LocationSetItem(location.id, image.id, label, status, "已有未结束任务。", None)
    if image.source is None and any(
        item.phase is ReferenceGenerationPhase.SUCCEEDED
        and not item.dismissed
        and item.output_asset_id in asset_ids
        for item in generations
    ):
        return LocationSetItem(
            location.id,
            image.id,
            label,
            "awaiting_selection",
            "已有成功候选，等待选择地点图片。",
            None,
        )
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
        return LocationSetItem(
            location.id,
            image.id,
            label,
            latest_failed.phase.value,
            "此前任务失败或已取消；不会自动重试。",
            None,
        )
    try:
        if image.source is not None:
            panorama_capture_request(document, image.id)
            step = "capture"
        else:
            location_image_plan(document, image.id)
            step = "image"
    except ValueError as exc:
        return LocationSetItem(location.id, image.id, label, "blocked", str(exc), None)
    return LocationSetItem(location.id, image.id, label, "ready", None, step)
