"""文档编解码：final 域的 parse/serialize 函数对。"""

from __future__ import annotations

from typing import Any

from ..models import (
    FinalApproval,
    FinalAssemblyClip,
    FinalAssemblyPlan,
    FinalTransition,
)
from ._shared import _exact_object, _integer, _object_list, _optional_string, _string

_FINAL_CLIP_FIELDS = {"scene_id", "zh_asset_id", "en_asset_id", "transition_from_previous"}

_FINAL_ASSEMBLY_FIELDS = {
    "source_script_revision",
    "clips",
    "selected_zh_asset_id",
    "selected_en_asset_id",
}

_FINAL_APPROVAL_FIELDS = {
    "zh_asset_id",
    "zh_generation_id",
    "en_asset_id",
    "en_generation_id",
    "source_script_revision",
    "approved_project_revision",
}


def _serialize_final_assembly(plan: FinalAssemblyPlan) -> dict[str, Any]:
    return {
        "source_script_revision": plan.source_script_revision,
        "clips": [
            {
                "scene_id": item.scene_id,
                "zh_asset_id": item.zh_asset_id,
                "en_asset_id": item.en_asset_id,
                "transition_from_previous": (
                    None
                    if item.transition_from_previous is None
                    else item.transition_from_previous.value
                ),
            }
            for item in plan.clips
        ],
        "selected_zh_asset_id": plan.selected_zh_asset_id,
        "selected_en_asset_id": plan.selected_en_asset_id,
    }


def _serialize_final_approval(approval: FinalApproval) -> dict[str, Any]:
    return {
        "zh_asset_id": approval.zh_asset_id,
        "zh_generation_id": approval.zh_generation_id,
        "en_asset_id": approval.en_asset_id,
        "en_generation_id": approval.en_generation_id,
        "source_script_revision": approval.source_script_revision,
        "approved_project_revision": approval.approved_project_revision,
    }


def _parse_final_assembly(value: object) -> FinalAssemblyPlan:
    fields = _exact_object(value, _FINAL_ASSEMBLY_FIELDS)
    return FinalAssemblyPlan(
        source_script_revision=_integer(
            fields["source_script_revision"], "final_assembly.source_script_revision"
        ),
        clips=_object_list(fields["clips"], _parse_final_clip),
        selected_zh_asset_id=_optional_string(
            fields["selected_zh_asset_id"], "final_assembly.selected_zh_asset_id"
        ),
        selected_en_asset_id=_optional_string(
            fields["selected_en_asset_id"], "final_assembly.selected_en_asset_id"
        ),
    )


def _parse_final_approval(value: object) -> FinalApproval:
    fields = _exact_object(value, _FINAL_APPROVAL_FIELDS)
    return FinalApproval(
        zh_asset_id=_optional_string(fields["zh_asset_id"], "final_approval.zh_asset_id"),
        zh_generation_id=_optional_string(
            fields["zh_generation_id"], "final_approval.zh_generation_id"
        ),
        en_asset_id=_optional_string(fields["en_asset_id"], "final_approval.en_asset_id"),
        en_generation_id=_optional_string(
            fields["en_generation_id"], "final_approval.en_generation_id"
        ),
        source_script_revision=_integer(
            fields["source_script_revision"], "final_approval.source_script_revision"
        ),
        approved_project_revision=_integer(
            fields["approved_project_revision"], "final_approval.approved_project_revision"
        ),
    )


def _parse_final_clip(value: object) -> FinalAssemblyClip:
    fields = _exact_object(value, _FINAL_CLIP_FIELDS)
    transition = fields["transition_from_previous"]
    return FinalAssemblyClip(
        scene_id=_string(fields["scene_id"], "final_assembly.clip.scene_id"),
        zh_asset_id=_optional_string(fields["zh_asset_id"], "final_assembly.clip.zh_asset_id"),
        en_asset_id=_optional_string(fields["en_asset_id"], "final_assembly.clip.en_asset_id"),
        transition_from_previous=(
            None
            if transition is None
            else FinalTransition(_string(transition, "final_assembly.clip.transition"))
        ),
    )
