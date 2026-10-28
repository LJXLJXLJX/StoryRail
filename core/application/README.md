# Application 边界

`caller.py` 定义服务端签发的不可变 `Caller` / `MutationGrant`、严格访问策略、认证、路由授权与请求身份摘要。
HTTP 每次请求重读受保护策略；`ContextVar` 只在受信调度期间存在；请求正文永远不能授予权限。

- Agent 写入需要部署开关、`project.mutate`，并且命令在 Agent 操作白名单内；再满足其一：受信 `project.execute`
  项目委托（本机启动签发，单项目、30 天），或绑定命令名、参数与原 revision 的精确 grant。
- `project.propose` 只允许提交、拒绝、取消**自己的** proposal 任务；Core 每次提交与重放都重新验证原请求的 grant 或委托。
- Agent 可经 `keyframe.select_candidate` 采用 Keyframe 候选，经 `video.select_reference_image` 为 Segment 其他图片
  选入任一项目图片（候选、关键帧已选图或资产库图片）或移除，人类随时可改选；其它候选采用、审核确认、Approval、
  重新开放、repair 与旧写路由不在白名单内，Agent 永远拒绝。
  用户明确要求撤回旁白音频时，Agent 可调用 `narration.clear_selection` 解除当前引用，这不选择新候选。
- Core 不读取外部对话，不声称能鉴别指令来自人类还是模型；它独立校验项目、操作、状态、revision、请求归属与撤权。
- 项目读授权是整个项目，不提供 Scene/Shot 级读隔离。人类凭据不能交给 Agent。

`requests.py` 定义 `ApplicationRequest` 严格持久类型与请求上下文，不持有 Store 或 Provider。原子回执与生成恢复由
`structured_director/application_requests.py` 经 Service/Store 实现：同步命令的业务变化与回执同次落盘；生成命令先登记
pending 回执与 Generation，中断后标记 uncertain，绝不自动重新提交；批次的同一回执记录整轮 Generation 与领域 run。

Agent 错误信封的唯一构造入口是中立的 `storyrail_contracts/errors.py`，分类见 [错误契约](../../docs/error-contract.md)。
授权与请求流程见 [控制流](../../docs/control-flow.md)。
