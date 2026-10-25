# Comfy Core runtime

这里不是 ComfyUI 服务，也不接受任意 workflow。它在隔离子进程中导入固定版本的 Comfy Core，由
`graph.py` 按 mode → 20/8 步与权重 → Sage/默认注意力 → SelfLift 现场构造 FL2VA 或 Ref2VA 节点图并执行。
`graph.py` 只允许固定节点类型，要求每条连线指向图内节点且不存在孤立节点。同 mode 任务可复用进程；资源切换、取消或控制租约结束时退出，
由操作系统回收全部 Private Commit。

- 不启动 HTTP、Web UI、数据库、队列或资产索引；
- 不扫描外部 custom nodes；只加载 H3 固定图所需的 ComfyUI 内置扩展和显式列出的 `comfyui-SelfLift`；
- 初始化时探测 SageAttention 与 Triton 缓存可写性；请求 Sage 而不可用时直接失败，不静默回退；
- 完成事件附带实际生效参数摘要（画布、帧数、权重、采样器、注意力），由外层写进任务完成消息；
  CUDA OOM 映射为带当前配置的明确错误，不自动降档；
- 请求只能引用 Provider 已建立任务目录中的首尾图片和 Ref2VA 参考 WAV；模型名、节点图、输入区和
  输出区由部署端固定；
- 内存调度保持该 ComfyUI 版本自己的 DynamicVRAM、RAM-pressure cache 和阶段卸载实现；
- 外层 Windows Provider 仍然常驻，并继续负责互斥调度、取消、恢复与 Core 租约。

Ref2VA 固定图使用官方 `MiniMaxH3ReferenceToVideo`。首尾图片在前、最多 4 张附加图片随后按顺序作为 `<Picture N>` 输入；参考音频为可选输入（官方节点 `ref_audios` 上限 3 条），存在时按 Core 给出的稳定顺序以 0 起的 `ref_audios.ref_audio_{N-1}` 接入。Prompt 的 `<Audio N>` 与同序输入对应，音频用途由 Core 保存的说明表达；没有音频时固定图只建立图片参考条件。可选参考视频（最多 3 条）先在暂存阶段用 PyAV 重采样为 24fps、无音轨的 H.264 MP4（官方节点按 24fps 解释参考帧），再经 `LoadVideo` → `GetVideoComponents` 取 IMAGE 帧，以 0 起的 `ref_videos.ref_video_{N-1}` 接入（`ref_video_0` 对应 `<Video 1>`）；不接 `ref_video_audios`，只作视觉参考。时间对齐语句负责近精确首尾安排。这里不再注入自定义 latent 节点，也不把
模型的提示词服从性提升为像素级硬约束。FL2VA 和 Ref2VA 使用不同 resident runner；相邻同 mode 复用，
两者切换时先释放旧进程，避免两个进程同时持有扩散权重占用 16 GB VRAM / 32 GB RAM。

FL2VA 与 Ref2VA 共用 `../sampling_progress.py`：从相邻有效步数回调的单调时钟差计算本步 s/iter，
跳步时标为最近 N 步均值；使用平滑步速估计仅采样阶段的剩余时间。首个无基准事件只显示正在估算，
其它节点事件不重置采样计时。按 request ID 过滤旧任务进度，进入解码后忽略迟到的采样事件。
总进度是单调的阶段估算，采样完成后仍有视频／音频 VAE 解码与 MP4 封装。

外层资源调度器在取得资源后开始总计时，到最终产物校验完成为止；包含 runtime 准备、采样、解码、
封装及产物处理，不含排队。完成耗时写入持久化任务消息并传回 Core 的 Generation，Web 候选展示该消息。
已有历史任务没有可靠计时记录时不补造耗时；运行中服务中断也不伪称完整计时。

## Qwen Image

`runtime.py` 的 `ComfyCoreRuntime` 是通用初始化（DynamicVRAM、固定节点加载、RAM-pressure cache、进度回调）；
H3 与 Qwen Image 子类各自声明需要的内置节点文件与固定节点类型。`qwen_image.py` 的 Qwen Image 子类只加载
`nodes_qwen.py`，按 `UNETLoader → QwenImage21Cache → KSampler`、`CLIPLoader + VAELoader → TextEncodeQwenImage21`、
`EmptyLatentImage → KSampler → VAEDecode → SaveImage` 现场构造固定图并校验节点白名单与连线。
`worker.py` 按 `STORYRAIL_COMFY_CORE_MODE`（`fl2va`、`ref2va` 或 `qwen_image`）选择运行时与请求解析。
