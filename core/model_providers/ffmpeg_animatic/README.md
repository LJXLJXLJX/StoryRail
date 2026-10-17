# FFmpeg Animatic

Core 侧的 Scene 级动态分镜预览插件。它只接受按时间排序的关键帧图片字节（PNG/JPEG）、旁白 WAV 字节、
受限转场枚举和项目画幅，通过独立 HTTP API 调用默认 FFmpeg 服务。插件不接受文件路径、滤镜文本、
命令行或任意编码参数。

段内平分展示首尾两张关键帧时使用硬切（`transition_from_previous=None`）；段间转场语义与最终装配一致：
相邻片段共用边界 Keyframe 时使用 0.1 秒 `seam_blend` 接缝融合，否则使用 null 硬切。旁白由 Core 绑定到起始
Segment，外部服务只负责按已声明时间线混音。
