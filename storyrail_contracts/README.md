# StoryRail 共享 wire 契约

这里只放 Core、server 与隔离 adapter 都必须使用的零依赖 wire 形状；不得导入 Store、Provider、
业务模型或任一边缘实现。`errors.py` 是 `docs/error-contract.md` 错误信封的唯一构造入口。
`fields.py` 是严格对象字段集合报错的唯一入口：点名缺失与多余字段并列出允许的字段，不回显字段值。
