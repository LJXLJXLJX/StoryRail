"""L0–L7 分层架构守卫（分层说明见 docs/architecture.md）。

三个断言：
1. ``core/`` 内函数体 import 兄弟模块数为 0。唯二豁免：
   TYPE_CHECKING 块（类型标注）与 PEP 562 模块级 ``__getattr__`` 懒加载
   export（import 写在函数体内是该机制的定义要求）。插件懒加载同理——
   本守卫只统计 import 目标是 ``core.*`` 的语句。基线 0，新增违例直接红。
2. 分层依赖方向：只允许向下（dep 层 < 自身层）。跨单元同层/向上 import
   必须出现在 ``DIRECTION_WHITELIST`` 并逐条注释理由；白名单外的违例直接红。
3. 模块级 runtime import 图无环（函数级 import 掩盖的环由断言 1 治理）。

层归属表：

- L0 models/ 包（纯领域数据，按域拆分，__init__ 再导出）
- L1 codec/ / schema / errors / video_contracts / video_inputs /
  video_continuation / candidate_eligibility / script_index / project_settings /
  project_workspaces / audio_effects / director_proposals（声明与契约）
- L2 *_mutations.py / generation_lifecycle / assembly_timeline /
  production_context / run_state / asset_metadata / narration_timing /
  planning_inputs（纯领域变换）
- L3 store/（持久化/CAS/原子写）
- L4 reads/ 包（read_tools facade、snapshot_view、semantic_projection、
  professional_worksets、execution_reads、workflow_state、impact、common）/
  prompt_worksets / keyframe_requests / director_steps / manual_commands（读模型）
- L5 proposal_requests / planning_proposals / script_proposals /
  workflow_commands / application_requests / director_commands / application
  （命令与授权）
- L6 service / media_submission / generation_observer / external_batches /
  keyframe_batches / location_batches / production_commands / provider_ports（应用编排）
- L7 http_api / http_requests（HTTP 边缘；MCP/launcher 在 core 外）
- core.model_providers.* 是插件边界，豁免本守卫。

单元粒度：core.structured_director 目录内部互为同单元；其余按顶层包划分。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"

LAYER_MAP = {
    "core.structured_director.models": 0,
    "core.structured_director.codec": 1,
    "core.structured_director.schema": 1,
    "core.structured_director.errors": 1,
    "core.structured_director.video_contracts": 1,
    "core.structured_director.video_inputs": 1,
    "core.structured_director.video_continuation": 1,
    "core.structured_director.candidate_eligibility": 1,
    "core.structured_director.script_index": 1,
    "core.media_assets": 1,
    "core.playground.capabilities": 2,
    "core.playground.codec": 1,
    "core.playground.commands": 5,
    "core.playground.errors": 1,
    "core.playground.http_api": 7,
    "core.playground.projection": 4,
    "core.playground.lifecycle": 2,
    "core.playground.observer": 6,
    "core.playground.service": 6,
    "core.playground.models": 0,
    "core.playground.parameters": 1,
    "core.playground.store": 3,
    "core.playground.usage": 2,
    "core.project_settings": 1,
    "core.project_workspaces": 1,
    "core.audio_effects": 1,
    "core.director_proposals": 1,
    "core.structured_director.script_mutations": 2,
    "core.structured_director.keyframe_mutations": 2,
    "core.structured_director.repair_mutations": 2,
    "core.structured_director.video_mutations": 2,
    "core.structured_director.mutations.narration": 2,
    "core.structured_director.mutations.run": 2,
    "core.structured_director.mutations.generation": 2,
    "core.structured_director.mutations.asset": 2,
    "core.structured_director.mutations.final": 2,
    "core.structured_director.generation_lifecycle": 2,
    "core.structured_director.assembly_timeline": 2,
    "core.structured_director.production_context": 2,
    "core.structured_director.run_state": 2,
    "core.structured_director.asset_metadata": 2,
    "core.structured_director.narration_timing": 2,
    "core.structured_director.planning_inputs": 2,
    "core.structured_director.reference_image_mutations": 2,
    "core.structured_director.reference_image_requests": 4,
    "core.structured_director.store": 3,
    "core.structured_director.reads": 4,
    "core.structured_director.reads.common": 4,
    "core.structured_director.reads.workflow_state": 4,
    "core.structured_director.reads.snapshot_view": 4,
    "core.structured_director.reads.semantic_projection": 4,
    "core.structured_director.reads.professional_worksets": 4,
    "core.structured_director.reads.execution_reads": 4,
    "core.structured_director.reads.read_tools": 4,
    "core.structured_director.reads.impact": 4,
    "core.structured_director.reads.dependencies": 4,
    "core.structured_director.reads.batch_observation": 4,
    "core.structured_director.reads.proposal_observation": 4,
    "core.structured_director.proposal_request_guard": 5,
    "core.structured_director.prompt_worksets": 4,
    "core.structured_director.keyframe_requests": 4,
    "core.structured_director.location_requests": 4,
    "core.structured_director.director_steps": 4,
    "core.structured_director.manual_commands": 4,
    "core.structured_director.proposal_requests": 5,
    "core.structured_director.planning_proposals": 5,
    "core.structured_director.location_proposals": 5,
    "core.structured_director.script_proposals": 5,
    "core.structured_director.workflow_commands": 5,
    "core.structured_director.application_requests": 5,
    "core.director_commands": 5,
    "core.application": 5,
    "core.structured_director.service": 6,
    "core.structured_director.media_submission": 6,
    "core.structured_director.generation_observer": 6,
    "core.structured_director.external_batches": 6,
    "core.structured_director.keyframe_batches": 6,
    "core.structured_director.location_batches": 6,
    "core.structured_director.production_commands": 6,
    "core.structured_director.provider_ports": 6,
    "core.structured_director.http_api": 7,
    "core.structured_director.http_requests": 7,
}

# 跨单元同层/向上 import 白名单（模块, 依赖前缀, 理由）。
# 条目随 Phase 2/3 的拆分逐批删除；新增违例不允许进白名单，除非先改本文注释。
# 地点权限投影可依赖同层 location_requests 的只读编译，
# 保持按钮与写入规则同源；不允许借此调用 Store 写入或 Provider。
DIRECTION_WHITELIST = [
    (
        "core.structured_director.store.domains.video",
        "core.application.caller",
        "阻止 Agent 通过通用 recipe 写入绕过参考图片候选的人类选择",
    ),
    (
        "core.structured_director.reference_image_mutations",
        "core.structured_director.video_mutations",
        "共享视频目标 scope 与冲突 Generation 拒绝规则",
    ),
    (
        "core.structured_director.reference_image_requests",
        "core.structured_director.keyframe_requests",
        "复用同一角色造型选择与就绪校验",
    ),
    (
        "core.structured_director.planning_proposals",
        "core.director_commands.video_commands",
        "专业 proposal 编译为严格的视频命令输入值对象",
    ),
    (
        "core.structured_director.reads.location_image",
        "core.structured_director.location_requests",
        "地点卡与单项/批次提交复用依赖检查与裁切有效性",
    ),
    # L5 命令层内部：application 与 director_commands 是同一层的协作包，
    # 共享 caller/receipt/registry 类型；P2-A4 把共享类型下沉后复核。
    ("core.structured_director.application_requests", "core.application", "L5 协作"),
    ("core.structured_director.application_requests", "core.director_commands", "L5 协作"),
    ("core.structured_director.proposal_requests", "core.application", "L5 协作"),
    ("core.structured_director.proposal_requests", "core.director_commands", "L5 协作"),
    ("core.structured_director.workflow_commands", "core.director_commands", "L5 协作"),
    # L5 命令分派：registry 按稳定 command name 分发到 proposal/workflow 两个
    # 外部 OPERATIONS 注册表（01 基线 D10 的延迟挂载机制，P3-T? 统一注册机制后复核）。
    ("core.director_commands.registry", "core.structured_director.proposal_requests", "L5 协作"),
    ("core.director_commands.registry", "core.structured_director.workflow_commands", "L5 协作"),
    (
        "core.structured_director.script_proposals",
        "core.structured_director.proposal_requests",
        "L5 协作",
    ),
    # L5 proposal 生命周期分派到 planning handler（P2-A5 下沉 owned_request/
    # proposal_observation 解环后模块级化）。
    (
        "core.structured_director.proposal_requests",
        "core.structured_director.planning_proposals",
        "L5 协作",
    ),
    # L5 proposal 所有权/授权校验 guard（P2-A5 从 proposal_requests 下沉解环）。
    ("core.structured_director.proposal_request_guard", "core.application", "L5 协作"),
    (
        "core.structured_director.proposal_requests",
        "core.structured_director.proposal_request_guard",
        "L5 协作",
    ),
    (
        "core.structured_director.application_requests",
        "core.structured_director.proposal_request_guard",
        "L5 协作",
    ),
    (
        "core.structured_director.script_proposals",
        "core.structured_director.proposal_request_guard",
        "L5 协作",
    ),
    # L1 纯函数复用：candidate_eligibility 使用 video_inputs 的候选纯函数。
    (
        "core.structured_director.candidate_eligibility",
        "core.structured_director.video_inputs",
        "L1 协作",
    ),
    # L1 声明复用 L5 类型：proposal dataclass 携带 caller/command 类型，
    # P3 契约统一时随类型下沉消除。
    ("core.director_proposals.keyframe", "core.director_commands", "P3 下沉"),
    ("core.director_proposals.keyframe_codec", "core.director_commands", "P3 下沉"),
    ("core.director_proposals.location", "core.director_commands", "P3 下沉"),
    ("core.director_proposals.location_codec", "core.director_commands", "P3 下沉"),
    ("core.director_proposals.script_codec", "core.application", "P3 下沉"),
    ("core.structured_director.codec.document", "core.application", "P3 下沉"),
    ("core.structured_director.models", "core.application", "P3 下沉"),
    # L0/L1 引用共享词汇：settings 与 schema 视为 L1 公共依赖。
    ("core.project_workspaces.store", "core.project_settings", "L1 公共词汇"),
    ("core.project_workspaces.store", "core.structured_director.store", "装配耦合"),
    ("core.structured_director.codec.document", "core.project_settings", "L1 公共词汇"),
    ("core.structured_director.codec.document", "core.structured_director.schema", "L1 公共词汇"),
    (
        "core.structured_director.codec.generation",
        "core.structured_director.video_contracts",
        "L1 公共词汇",
    ),
    (
        "core.structured_director.codec.keyframe",
        "core.structured_director.video_contracts",
        "L1 公共词汇",
    ),
    ("core.structured_director.models", "core.project_settings", "L1 公共词汇"),
    ("core.structured_director.models", "core.structured_director.schema", "L1 公共词汇"),
    ("core.structured_director.models", "core.structured_director.video_contracts", "L1 公共词汇"),
    # models/ 按域拆包（P2-B1）后 L0 域文件复用 L1 公共词汇（同原 models.py 口径）。
    (
        "core.structured_director.models.document",
        "core.structured_director.schema",
        "L1 公共词汇",
    ),
    (
        "core.structured_director.models.keyframe",
        "core.structured_director.video_contracts",
        "L1 公共词汇",
    ),
    (
        "core.structured_director.models.validation.document",
        "core.structured_director.schema",
        "L1 公共词汇",
    ),
    (
        "core.structured_director.video_inputs",
        "core.structured_director.video_contracts",
        "L1 协作",
    ),
    (
        "core.structured_director.video_continuation",
        "core.structured_director.video_inputs",
        "L1 协作",
    ),
    # L1 脚本访问层：视频输入按 Segment 序列定位上一段，不直接展开脚本树。
    (
        "core.structured_director.video_inputs",
        "core.structured_director.script_index",
        "L1 协作",
    ),
    # L2 复用 L5 命令类型（receipt/scope），P2-C pipeline 抽取时下沉。
    ("core.structured_director.keyframe_mutations", "core.director_commands", "P2-C 下沉"),
    ("core.structured_director.repair_mutations", "core.director_commands", "P2-C 下沉"),
    ("core.structured_director.script_mutations", "core.director_commands", "P2-C 下沉"),
    ("core.structured_director.video_mutations", "core.director_commands", "P2-C 下沉"),
    ("core.structured_director.errors", "core.director_commands", "P2-C 下沉"),
    ("core.structured_director.production_context", "core.director_commands", "P2-C 下沉"),
    # L2 读 L4 输入组装 / L2 域间复用：P2-A3 重定层后消除。
    (
        "core.structured_director.planning_inputs",
        "core.structured_director.director_steps",
        "P2-A3 重定",
    ),
    (
        "core.structured_director.production_context",
        "core.structured_director.reads.read_tools",
        "P2-A3 重定",
    ),
    (
        "core.structured_director.production_context",
        "core.structured_director.reads.semantic_projection",
        "P2-A3 重定",
    ),
    (
        "core.structured_director.production_context",
        "core.structured_director.keyframe_requests",
        "P2-A3 重定",
    ),
    (
        "core.structured_director.candidate_eligibility",
        "core.structured_director.keyframe_requests",
        "P2-A3 重定",
    ),
    (
        "core.structured_director.assembly_timeline",
        "core.structured_director.narration_timing",
        "L2 协作",
    ),
    (
        "core.structured_director.production_context",
        "core.structured_director.narration_timing",
        "L2 协作",
    ),
    # 每次脚本写入都按旁白真实时长自动重建生产基线。
    (
        "core.structured_director.script_mutations",
        "core.structured_director.narration_timing",
        "L2 协作",
    ),
    (
        "core.structured_director.video_mutations",
        "core.structured_director.repair_mutations",
        "L2 协作",
    ),
    # P2-C2 旁白域 mutations：L2 域间复用（失效传播/run 生命周期/时序规则），
    # 与 video_mutations 同口径；director_commands 类型随 P3 下沉后复核。
    (
        "core.structured_director.mutations.narration",
        "core.structured_director.script_mutations",
        "L2 协作",
    ),
    (
        "core.structured_director.mutations.narration",
        "core.structured_director.repair_mutations",
        "L2 协作",
    ),
    (
        "core.structured_director.mutations.narration",
        "core.structured_director.run_state",
        "L2 协作",
    ),
    (
        "core.structured_director.mutations.narration",
        "core.director_commands",
        "P2-C 下沉",
    ),
    (
        "core.structured_director.mutations.run",
        "core.director_commands",
        "P2-C 下沉",
    ),
    (
        "core.structured_director.mutations.generation",
        "core.director_commands",
        "P2-C 下沉",
    ),
    (
        "core.structured_director.mutations.generation",
        "core.structured_director.video_mutations",
        "L2 协作",
    ),
    (
        "core.structured_director.mutations.generation",
        "core.structured_director.run_state",
        "L2 协作",
    ),
    (
        "core.structured_director.mutations.asset",
        "core.structured_director.mutations.generation",
        "L2 协作",
    ),
    (
        "core.structured_director.mutations.asset",
        "core.structured_director.video_mutations",
        "L2 协作",
    ),
    (
        "core.structured_director.mutations.asset",
        "core.structured_director.asset_metadata",
        "L2 协作",
    ),
    (
        "core.structured_director.mutations.final",
        "core.director_commands",
        "P2-C 下沉",
    ),
    # L4 读模型标注 L5 caller 类型：类型下沉后消除。
    ("core.structured_director.reads.execution_reads", "core.application", "P2-A3 重定"),
    (
        "core.structured_director.reads.batch_observation",
        "core.application",
        "P2-A3 重定",
    ),
    # L4 内部协作（P2-A3 已归入 reads/ 包，同包 import 不再逐条登记；
    # 以下保留给仍在外部的 L4 模块与跨包协作）。
    (
        "core.structured_director.reads.batch_observation",
        "core.structured_director.keyframe_requests",
        "L4 内部",
    ),
    (
        "core.structured_director.reads.batch_observation",
        "core.structured_director.location_requests",
        "L4 内部",
    ),
    (
        "core.structured_director.reads.semantic_projection",
        "core.structured_director.prompt_worksets",
        "L4 内部",
    ),
    (
        "core.structured_director.reads.professional_worksets",
        "core.structured_director.prompt_worksets",
        "L4 内部",
    ),
    (
        "core.structured_director.prompt_worksets",
        "core.structured_director.keyframe_requests",
        "L4 内部",
    ),
    (
        "core.structured_director.reads.workflow_state",
        "core.structured_director.keyframe_requests",
        "L4 内部",
    ),
    # L4 reads 需要 L5 proposal 观察读模型（run.get_status / request_read 内联观察）；
    # P2-A5 已把 proposal_observation 下沉 reads.proposal_observation，本组条目保留
    # 给仍在读 L5 proposal 模块的位置（后续随 P3 类型统一复核）。
    # L3 store 在命令入口复用 L4/L5 类型：P2-C pipeline 下沉后消除。
    ("core.structured_director.store", "core.director_commands", "P2-C 下沉"),
    ("core.structured_director.store", "core.structured_director.manual_commands", "P2-C 下沉"),
    (
        "core.structured_director.store",
        "core.structured_director.application_requests",
        "P2-C 下沉",
    ),
    # L3 store 命令入口的阶段门禁前置校验依赖 L4 读模型投影；
    # require_workflow_action 是纯函数（无 store 依赖），P2 分层重定时随门禁下沉消除。
    (
        "core.structured_director.store",
        "core.structured_director.reads.workflow_state",
        "P2-A3 重定",
    ),
    # L4 需要命令领域类型（impact preview 试算命令 / read_tools 命令解析）：
    # P2-A2 随 mutations 下沉消除。
    ("core.structured_director.reads.impact", "core.director_commands", "P2-A2 下沉"),
    (
        "core.structured_director.reads.read_tools",
        "core.director_commands",
        "P2-A2 下沉",
    ),
    ("core.structured_director.director_steps", "core.director_commands", "P2-A2 下沉"),
    ("core.structured_director.manual_commands", "core.director_commands", "P2-A2 下沉"),
    # L6/L7 内部协作。
    (
        "core.structured_director.external_batches",
        "core.structured_director.keyframe_batches",
        "L6 内部",
    ),
    (
        "core.structured_director.external_batches",
        "core.structured_director.location_batches",
        "L6 内部",
    ),
    (
        "core.structured_director.generation_observer",
        "core.structured_director.provider_ports",
        "L6 内部",
    ),
    (
        "core.structured_director.media_submission",
        "core.structured_director.provider_ports",
        "L6 内部",
    ),
    ("core.structured_director.service", "core.structured_director.generation_observer", "L6 内部"),
    ("core.structured_director.service", "core.structured_director.media_submission", "L6 内部"),
    ("core.structured_director.service", "core.structured_director.provider_ports", "L6 内部"),
    ("core.structured_director.service", "core.structured_director.external_batches", "L6 内部"),
    ("core.structured_director.service", "core.structured_director.production_commands", "L6 内部"),
    ("core.structured_director.http_api", "core.structured_director.http_requests", "L7 内部"),
    # Playground 参数层复用中立的 preset 名单与表演指令校验器：两者都是 L1
    # 声明/契约包（audio_effects、director_proposals），不含项目状态，也不反向
    # 依赖 Playground（由 test_playground_boundaries.py 守卫）。
    ("core.playground.parameters", "core.audio_effects.presets", "L1 契约复用"),
    ("core.playground.parameters", "core.director_proposals.narration", "L1 契约复用"),
    # Playground 命令层读取当前 caller（Caller 值与严格 JSON 解析）做归属与摘要，
    # 与项目 application_requests 的用法相同；core.application 不反向依赖 Playground。
    ("core.playground.commands", "core.application.caller", "L5 协作"),
]


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(CORE).with_suffix("").parts)
    # __init__.py 即包模块本身（等同 Python import 语义），归一为包名，
    # 使包级 LAYER_MAP/白名单条目对拆包后的 __init__ 继续生效。
    if parts and parts[-1] == "__init__":
        parts.pop()
    return "core." + ".".join(parts)


def _unit(module: str) -> str:
    parts = module.split(".")
    if parts[1] == "structured_director":
        return ".".join(parts[:3])
    return ".".join(parts[:2])


def _layer(module: str) -> int | None:
    parts = module.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in LAYER_MAP:
            return LAYER_MAP[candidate]
        parts.pop()
    return None


def _scan_file(
    path: Path,
) -> tuple[list[tuple[str, int, str]], set[str]]:
    """扫描单个模块：返回 (函数级 core import 记录, runtime 模块级依赖)。"""
    tree = ast.parse(path.read_text())
    module = _module_name(path)
    parents: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def context(node) -> tuple[bool, bool, bool]:
        type_checking = False
        function_level = False
        lazy_export = False
        current = parents.get(node)
        while current is not None:
            if (
                isinstance(current, ast.If)
                and isinstance(current.test, ast.Name)
                and current.test.id == "TYPE_CHECKING"
            ):
                type_checking = True
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_level = True
                # PEP 562 模块级 __getattr__ 的懒加载 export 是刻意的模块级机制：
                # import 写在函数体内是该机制的定义要求（提前到模块级会重建被消解的
                # 包初始化环），不计入函数级违例，也不构成静态 import 图边。
                if current.name == "__getattr__" and isinstance(parents.get(current), ast.Module):
                    function_level = False
                    lazy_export = True
            current = parents.get(current)
        return type_checking, function_level, lazy_export

    function_level_records: list[tuple[str, int, str]] = []
    runtime_deps: set[str] = set()
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = module.split(".")[:-1]
                for _ in range(node.level - 1):
                    if parts:
                        parts.pop()
                base = ".".join(parts + ([base] if base else []))
            targets = [base] if base else []
        else:
            continue
        type_checking, function_level, lazy_export = context(node)
        for target in targets:
            if not target.startswith("core"):
                continue
            statement = (
                f"import {target}" if isinstance(node, ast.Import) else f"from {target} import ..."
            )
            if function_level:
                function_level_records.append((module, node.lineno, statement))
            elif not type_checking and not lazy_export:
                runtime_deps.add(target)
    return function_level_records, runtime_deps


class _Scan:
    def __init__(self) -> None:
        self.function_level: list[tuple[str, int, str]] = []
        self.runtime_graph: dict[str, set[str]] = {}
        for path in sorted(CORE.rglob("*.py")):
            records, deps = _scan_file(path)
            self.function_level.extend(records)
            self.runtime_graph[_module_name(path)] = deps


_SCAN = None


def _scan() -> _Scan:
    global _SCAN
    if _SCAN is None:
        _SCAN = _Scan()
    return _SCAN


def _resolve(graph: dict[str, set[str]], module: str) -> str | None:
    parts = module.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in graph:
            return candidate
        parts.pop()
    return None


def test_no_function_level_core_imports() -> None:
    violations = _scan().function_level
    listing = "\n".join(f"{module}:{lineno}: {stmt}" for module, lineno, stmt in violations)
    assert not violations, f"core/ 内函数级 import {len(violations)} 处：\n{listing}"


def _whitelisted(module: str, dep: str) -> bool:
    return any(
        (
            module == whitelisted_module
            # store/domains/  collaborator 是 facade 的实现拆分（P2-D1），
            # 继承 facade 的包级白名单条目（同 store 单元、同依赖语义）。
            or module.startswith(whitelisted_module + ".domains.")
            # media_submission/ 按能力拆分后仍是同一个 L6 用例包。
            or (
                whitelisted_module == "core.structured_director.media_submission"
                and module.startswith(whitelisted_module + ".")
            )
        )
        and (dep == whitelisted_dep or dep.startswith(whitelisted_dep + "."))
        for whitelisted_module, whitelisted_dep, _reason in DIRECTION_WHITELIST
    )


def test_layer_direction() -> None:
    graph = _scan().runtime_graph
    violations = []
    for module, deps in sorted(graph.items()):
        own_layer = _layer(module)
        if own_layer is None or module.startswith("core.model_providers"):
            continue
        for dep in sorted(deps):
            if dep == module or dep.startswith(module + ".") or module.startswith(dep + "."):
                continue
            if _unit(dep) == _unit(module):
                continue
            dep_layer = _layer(dep)
            if dep_layer is None or dep_layer < own_layer:
                continue
            if _whitelisted(module, dep):
                continue
            violations.append(f"{module}(L{own_layer}) -> {dep}(L{dep_layer})")
    assert not violations, "白名单外的跨单元同层/向上 import：\n" + "\n".join(violations)


def test_no_import_cycles() -> None:
    graph = _scan().runtime_graph
    visited: set[str] = set()
    in_stack: set[str] = set()
    stack: list[str] = []
    cycles: list[str] = []

    def visit(node: str) -> None:
        visited.add(node)
        in_stack.add(node)
        stack.append(node)
        for dep in sorted(graph.get(node, ())):
            target = _resolve(graph, dep)
            if target is None or target == node:
                continue
            if target not in visited:
                visit(target)
            elif target in in_stack:
                start = stack.index(target)
                cycles.append(" -> ".join(stack[start:] + [target]))
        stack.pop()
        in_stack.discard(node)

    import sys

    sys.setrecursionlimit(10000)
    for module in sorted(graph):
        if module not in visited:
            visit(module)
    assert not cycles, "模块级 import 环：\n" + "\n".join(cycles)
