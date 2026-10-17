# MiniMax H3 Ref2VA Provider

插件标识：`minimax.h3.ref2va`。该用法可携带 0 到 8 条由 Segment 显式选择的 WAV 参考音频；
音频按视频计划顺序组成有序列表，并与提示词中的 `<Audio N>` 一一对应。音频用途由 Core 保存的必填说明表达，Provider 不推断角色或音色语义。
还可携带 0 到 3 条 2–15 秒 MP4 参考视频（payload `video_references`，base64，稳定顺序对应 `<Video N>`，
`plugin_version` 4）；参考视频只作视觉参考，Provider 不把其音轨当作音频参考。

本插件接入 H3 reference-to-video 用法。首帧和尾帧都可为空，也可以完全不使用图片；首帧、尾帧、附加图片、
参考音频与参考视频五类槽位合计至少有一个输入资产。有素材时按 Core 给出的稳定顺序携带，其中附加参考图最多 4 张。画布按 32 像素网格；`step_count` 只允许 20 或
8，并携带 `sage_attention`、`selflift` 两个布尔开关，三者都来自全局 H3 渲染设置。它拥有独立的请求字段、外部状态翻译、取消方式和产物回收路径。
