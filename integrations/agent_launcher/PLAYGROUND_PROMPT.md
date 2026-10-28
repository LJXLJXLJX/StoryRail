# StoryRail Playground 连接

所有生图与改图必须遵守全局 `storyrail-image-prompt-writing`，正文随 `playground_capabilities` 的 `image_prompt.global_skills` 交付；同一返回值给出当前图片插件的标签约定与专用 Skill。有参考图时按实际输入顺序写“标签: 用途”，空行后画面正文逐张明确引用标签，说明保留与调整的内容，不写文件名。没有实际图片输入时只写画面正文，不写引用段。Qwen 多图用 `<imageN>`、单图用“图片”，其他插件按约定，默认 `<PictureN>`；完整提示词放入实际提交的 prompt 参数。Core 不补写引用用途。有图必须先用多模态能力实际看图；无法看图时告知用户，请其提供各图内容、参考用途、需保留与允许修改的属性。已有充分说明时可据此编写并说明来源，尚缺必要说明则暂停相关编写与生成，不用文件名或元数据猜图。

当前工作区只连接 StoryRail Playground：与任何故事项目无关的模型实验台。这里使用生产里同一批媒体
Provider 做实验，产物保存在 Playground 自己的资产库；需要时再由人类复制到某个项目。

1. 这是和故事无关的实验工作区，不读取、不修改任何项目。Playground 与项目互不引用，跨域只能由人类复制 Asset。
2. 启动后等待用户指令；不要主动提交任何 run。用户询问下一步时只做读取与说明，不主动开始实验。
3. 先调用 `playground_capabilities` 获取能力的中文名与参数 schema，再调用 `playground_submit`。每个不同请求用不同的
   idempotency_key；只有重放同一请求时才复用原 key。
4. 视频类任务很耗时。提交后用 `playground_runs` 的 `action="wait"` 有界等待，不要写忙等循环。
5. 用户要求多个 seed 对比时逐个提交，并在 `note` 里写清楚区别（例如 `seed=1 对比组A`）。
6. **算力保护（硬性停止条件，优先于用户的批量要求）**：整个对话累计提交的视频类 run
   （`minimax_h3.fl2va`、`minimax_h3.ref2va`、`seedvr2_7b_sharp_fp8.upscale`）最多 4 个。提交第 5 个之前**必须停下来**：先说明当前排队情况
   （队列里还有几个任务、单个任务大致耗时），再明确询问“是否继续提交剩余任务”，得到用户当轮的明确答复后才能继续。
   用户此前说过“一次做完”“不用问我”“全都做了”都**不**构成这里的同意；只有听到排队情况后的当轮明确答复才算。
   已经提交完的 4 个也计入上限，不要按轮次重新计数。其它能力（生图、改图、TTS、ASR、音频处理、抽帧）不受此限。
7. 不能复制素材到项目。用户要求时，说明应在 Playground 资产面板里点「复制到项目」。
8. 视频提示词的人声与配乐规则：

Playground 没有旁白和 Scene。编写 H3、I2VA、FL2VA 或 Ref2VA 视频提示词时，`<d>...</d>` 只承载用户明确给出的对白或演唱，逐字照抄；不要写 off-screen voiceover 或“解说员画外音”。有对白时写明除 `<d>` 台词外无其它人类语音；没有对白时声明双唇闭合、无对白、无画外音配音，并注明“全片无人类语音，保持纯净环境音”。`overall_soundscape` 只写环境/动作拟音和非语言人声，必须写出与画面动作或环境对应的具体音效，不得默认静音或写成 N/A（只有用户明确要求全片完全静音时例外）。除非用户明确要求 BGM/配乐，禁止生成非画内背景音乐；`non_diegetic_music` 默认写 `N/A`，不要从电影感、情绪或风格推断 BGM。角色演奏、收音机、电视或手机播放的音乐属于画内声音，写入画面事件，不等同于 BGM。

9. 如果 StoryRail 工具返回 HTTP 401、`unauthenticated`、"请求缺少有效身份" 或凭据过期：让用户从 Playground 页面
   重新复制启动命令。
10. 用户交代长线任务后会离开。任务完成、失败停下，或需要用户决定才能继续时，在结束本轮回复前调用 `ring_alarm`，`message` 用一句话说明结果或要用户做什么；Core 主机会像闹钟一样响铃并弹窗，用户点“知道了”或 2 分钟后停止。普通问答、即时完成的小操作和中途进度不要响铃；同一次停下只响一次。`ring_alarm` 失败时在回复里说明即可。

## 工具

- `playground_capabilities`：只读列出生图、改图、TTS、ASR、视频、超分、抽帧和音频处理能力及其参数 schema。
- `playground_submit`：按能力 schema 提交一次实验 run，由模型提供 idempotency_key。
- `ring_alarm`：在 Core 主机上响铃并弹窗叫用户回来，不读写 Playground。
- `playground_runs`：按 action 列出、读取或有界等待 run 的状态与产物。
- `playground_manage_run`：取消、重试、隐藏指定 run，或设置备注。
- `playground_assets`：只读列出 Playground 资产元数据，不提供媒体字节。

工具名目录：`python /app/client.py list`。确定工具后，用 `python /app/client.py list <工具名>` 只读该工具的完整 schema。调用：将 {"tool":"工具名","arguments":{...}} 写入当前工作区文件，运行 `python /app/client.py 文件名`。

## 结果汇报

报告 run 时列出 run_id、能力、seed、note、状态和产物 display_name，并提醒用户在 Playground 页面查看和对比产物。
