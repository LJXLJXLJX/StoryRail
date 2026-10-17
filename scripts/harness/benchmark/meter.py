"""MCP 计量：逐请求记录线上字节，并给出场景级汇总。

口径（与 `04-agent-token-and-harness.md` §3 对应）：

- `input_bytes`：一次请求中客户端交给 MCP server 的正文字节
  （`json.dumps(arguments, separators=(",", ":"))`，UTF-8）；不含传输框架开销。
- `output_bytes`：该调用 `structured_content` 的紧凑 JSON 字节；不含传输框架开销。
- `tools_list_bytes`：`tools/list` 每个工具 `description + input_schema` 的紧凑 JSON 字节之和。
- `contract_read_bytes`：`read_professional_contract` 的请求与响应字节之和。
- `workset_read_bytes`：`read_professional_workset` 的请求与响应字节之和（含分页 chunk）。
- `pagination_rounds`：一次分页读取实际发生的请求次数（1 表示未分页）。
- `wait_rounds`：`manage_generation(action="wait")` 的调用次数。

合计 `total_wire_bytes = sum(input_bytes + output_bytes)`，是防回归门禁比较的量。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


def compact_bytes(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


@dataclass
class RequestRecord:
    index: int
    step: str
    tool: str
    action: str
    input_bytes: int
    output_bytes: int
    is_error: bool
    pagination_rounds: int = 1
    wait_again: bool | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "step": self.step,
            "tool": self.tool,
            "action": self.action,
            "input_bytes": self.input_bytes,
            "output_bytes": self.output_bytes,
            "is_error": self.is_error,
            "pagination_rounds": self.pagination_rounds,
            "wait_again": self.wait_again,
        }


@dataclass
class Meter:
    records: list[RequestRecord] = field(default_factory=list)
    tools_list_bytes: int = 0
    tool_count: int = 0
    _index: int = 0

    def record(
        self,
        *,
        step: str,
        tool: str,
        action: str,
        arguments: object,
        result: dict[str, object],
        is_error: bool,
        pagination_rounds: int = 1,
    ) -> RequestRecord:
        self._index += 1
        entry = RequestRecord(
            index=self._index,
            step=step,
            tool=tool,
            action=action,
            input_bytes=compact_bytes(arguments),
            output_bytes=compact_bytes(result),
            is_error=is_error,
            pagination_rounds=pagination_rounds,
        )
        self.records.append(entry)
        return entry

    def total(self, *, tools: str | None = None) -> int:
        return sum(
            record.input_bytes + record.output_bytes
            for record in self.records
            if tools is None or record.tool == tools
        )

    def by_tool(self, tool: str) -> int:
        return self.total(tools=tool)

    def pagination_rounds(self) -> int:
        return sum(record.pagination_rounds for record in self.records)

    def wait_rounds(self) -> int:
        return sum(1 for record in self.records if record.action == "wait")

    def summary(self) -> dict[str, object]:
        return {
            "tools_list_bytes": self.tools_list_bytes,
            "tool_count": self.tool_count,
            "requests": len(self.records),
            "input_bytes": sum(record.input_bytes for record in self.records),
            "output_bytes": sum(record.output_bytes for record in self.records),
            "total_wire_bytes": self.total(),
            "contract_read_bytes": self.by_tool("read_professional_contract"),
            "workset_read_bytes": self.by_tool("read_professional_workset"),
            "pagination_rounds": self.pagination_rounds(),
            "wait_rounds": self.wait_rounds(),
            "error_responses": sum(1 for record in self.records if record.is_error),
        }
