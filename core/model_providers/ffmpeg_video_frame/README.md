# FFmpeg 视频抽帧

受控 MP4 字节加一个从 0 开始的帧号，转换为该帧画面的 PNG。帧号合法范围由 Core 从
MP4 容器读出后在提交前校验，worker 解码后再次校验。只负责媒体协议，不接收项目路径、
不选择候选。任务使用现有 submit/observe/cancel/read_artifact 生命周期。
