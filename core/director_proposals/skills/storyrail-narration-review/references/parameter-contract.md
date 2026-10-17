# 旁白合成参数契约

每条 Cue 的中文与英文轨道分别使用旁白身份中同语言的参考音色。工作集的 `speech_recipe` 描述当前
`speech.synthesize` 插件、recipe、`editable_params`、生效设置与提示。先读取它再调整参数，不假定所有插件
都接受自然语言表演指示。

- `recipe_params`：以 `speech_recipe.recipe.id` 为键，保存无语义角色的机制参数。按 `editable_params`
  的类型、范围、可空性和说明填写完整对象；保留其它 recipe 的已存参数。Breeze 的 `performance_instruction`
  是其中一个可空文本参数，最多 200 字，描述语气、情绪、语速、停顿与重音，不复述正文或音色。
- `seed`：领域参数，用于复现；想换一个表演变体时再调整。

单语言以该音频真实时长为准，双语言以较长的一条决定画面时长。调整语速会改变真实时长与时间基准。

返回目标 `cue_updates`：用 `cue_id` 与 `language` 定位，给出 `recipe_params` 和 `seed`。
同一 Cue 的同一语言最多出现一次；未授权的 Cue 或语言不更新。修改参数使该语言的已选音频失效，历史候选保留。
解释听感取舍，不能声称音频已经生成、审核通过或被选中。
