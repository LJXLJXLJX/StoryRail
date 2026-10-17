# FFmpeg 全景裁切

受控 2:1 等距柱状全景（PNG/JPEG）加一个透视机位（`yaw_deg`、`pitch_deg`、`hfov_deg`、画幅），
转换为该机位的透视 PNG。工具是确定性的：同输入必得同字节。

- 方位：`yaw_deg` ∈ [0, 360)，0° 为全景正中，顺时针（向右）为正；`pitch_deg` ∈ [−60, 60]，抬头为正；
  `hfov_deg` ∈ [20, 120] 是输出水平视场角。
- 输入：PNG 或 JPEG，宽高比 2:1（允许 ±1 像素），宽度 1024–16384，字节 ≤ 64 MiB。
- 输出：长边固定 2048，短边按画幅取偶数——`16:9` 为 2048×1152，`9:16` 为 1152×2048，`2:1` 为 2048×1024。
  垂直视场角按透视公式 `v_fov = 2·atan(tan(hfov/2) · 输出高/输出宽)` 换算。

Core 契约（`core/model_providers/contracts.py` 的 `PanoViewRequest`）与媒体服务 worker 各校验一次
签名、尺寸和参数范围；范围常量与 `validate_pano_source` / `validate_pano_view_geometry` 也是
Playground `image.pano_view` 的唯一校验来源。只负责媒体协议，不接收项目路径、不认识 Location、不选择候选。
任务使用现有 submit/observe/cancel/read_artifact 生命周期，接口为 `/ffmpeg/pano-views`。
