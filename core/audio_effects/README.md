# Audio Effects

本目录提供不依赖项目状态的确定性 WAV 截取与音频后处理。它位于领域/Skill 与具体 DSP 之间：调用方提交
`AudioEffectRequest` 和 WAV 字节，得到新的 WAV 字节及可复现事件时间线；模块不读取或写入
`project.json`、不选择候选，也不拥有 Generation 生命周期。

当前实现 `radio`，preset 只负责组合参数，所有 preset 共用同一 DSP。随机噪声、dropout 和 burst
仅使用请求携带的 `seed` 创建局部随机源。同一输入字节、参数、seed 和 StoryRail 版本产生相同输出。

高层入口：

```python
from core.audio_effects import AudioEffectRequest, apply_audio_effect

result = apply_audio_effect(
    wav_bytes,
    AudioEffectRequest(
        effect="radio",
        preset="weak_signal",
        strength=0.7,
        seed=42,
        start_seconds=1.25,
        end_seconds=4.8,
    ),
)
output_wav = result.audio
timeline = result.metadata.to_dict()
```

CLI：

```bash
.venv/bin/python -m core.audio_effects input.wav output.wav \
  --effect radio --preset weak_signal --strength 0.7 --seed 42 \
  --start 1.25 --end 4.8 \
  --metadata output.json
```

首版输入限定为未压缩 PCM WAV（8/16/24/32-bit），输出为保持原采样率和声道数的 PCM16 WAV。
高级覆盖参数可通过重复的 `--set name=value` 传入。CLI 是人工试听入口，不接触 StoryRail
业务 authority；外部 Agent 的项目内写入仍须由上层正式领域命令负责。

`start_seconds` / `end_seconds` 必须同时提供；省略时处理全长。选择局部区间时 DSP 只读取该切片，
在区间内部做短交叉淡化，区间外保持原声。metadata 中的事件时间使用源音频绝对时间，仍可直接与字幕
或视频时间线同步。

项目内入口由 Structured Director 提供：资产中心对每个 WAV Asset 显示“音频后处理”，向
`POST /assets/{asset_id}/audio-effect` 提交语义参数。Core 保留源 Asset，原子登记处理后的不可变
Asset，并以隐藏的 `audio_effect` Generation 保存输入、输出、处理器版本和可复现事件时间线。

纯截取使用独立的 `AudioTrimRequest` / `trim_audio` 入口，按采样帧对齐保留指定范围，保持采样率和
声道数并输出 PCM16 WAV。项目内 `POST /assets/{asset_id}/audio-trim` 保留源 Asset、创建不可变副本，
并用隐藏的 `audio_trim/process` Generation 记录请求时间、实际对齐时间、输出时长和内容哈希；它不会
伪装成某种音频效果，也不会影响后续效果副本的选择逻辑。
