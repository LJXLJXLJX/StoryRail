# Web contracts

Web 快照与 proposal 的结构契约声明在这里，再由 `scripts/gen_web_contracts.py` 生成
`web/src/api/types.ts` 与 `web/src/api/validation.ts`。

- `snapshot_schema.py` 描述 Core HTTP 快照和设置响应。枚举值引用领域 `StrEnum`，
  不在 TypeScript 里再写一份。
- `proposal_schema.py` 读取六个 codec 已经生成的 JSON Schema，并标上 TypeScript 类型名。
- 跨字段不变量（解锁层单调、状态与计划一致性等）不在 schema 里，
  留在手写的 `web/src/api/refine.ts`。

`python scripts/gen_web_contracts.py --check` 比较生成物与工作区；漂移时 CI 失败。
