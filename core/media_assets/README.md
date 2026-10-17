# core/media_assets

与项目和 Playground 都无关的媒体字节工具：媒体字节校验（`media_bytes.py`）、WAV/MP4 时长读取
（`media_bytes.py`）、可读资产文件名规范化（`filenames.py`）和 MP4 帧数与时长读取（`mp4_frames.py`）。

本包没有状态，不读写文件，也不 import 项目或 Playground 的任何模块，因此可以被两边的
authority 同时复用（`core/structured_director` 只做别名导入保持既有调用点不变）。
