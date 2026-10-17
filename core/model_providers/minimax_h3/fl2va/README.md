# MiniMax H3 FL2VA Provider

插件标识：`minimax.h3.fl2va`。该模型级用法至少需要 Segment 已选首帧或尾帧之一，也可以同时使用二者。StoryRail 请求模型同时生成并封装环境声、动作声和音乐等非对白音轨。

本插件接入 H3 的关键帧视频用法。请求必须至少包含首帧或尾帧，并可同时包含两者；插件负责严格校验
图片、画布（32 像素网格）、时长和采样参数，再调用该用法自己的 HTTP API。`sampling` 只允许 20 或 8 步，并携带
`sage_attention`、`selflift` 两个布尔开关，三者都来自全局 H3 渲染设置。
