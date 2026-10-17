# HTTP client contract

`types.ts` 与 `validation.ts` 由 `scripts/gen_web_contracts.py` 从 schema 生成，不要手改。
`schema_check.ts` 解释这份 schema；`refine.ts` 只保留跨字段不变量，例如解锁层单调、
状态与计划一致性。二者不调用网络或修改状态。上层 `api.ts` 负责请求发送、
错误翻译与类型导出。类型声明不能替代响应验证；业务授权始终由 Core 决定。
