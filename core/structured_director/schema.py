"""当前唯一受支持的 project.json schema。"""

# v28 引入地点库（location_library：地点、陈设、状态、机位视图）；
# Scene 绑定地点与状态，Shot 绑定视图，Keyframe 引用视图。
# v30 角色图以造型为唯一单位（CharacterLook.selected_asset_id），Keyframe 按造型选择角色图。
# v31 角色卡标记非人形（CharacterCard.non_humanoid），造型设定图按形体选择版式。
# v32 创建时固化旁白语言（narration_languages），未选语言轨道、音色与成片字段为 null；
#     移除 v31 的 non_humanoid，非人形设定图改由提示词约束。
# v33 Scene 下并列 shots（创作层）与 segments（生产层，shot_ids 记录覆盖的 Shot）；
#     旁白 Cue 删除 Shot 锚点，Narration Scene 的唯一 Cue 覆盖整个 Scene。
# v34 DialogueLine 获得稳定 ID 与临时说话者音色描述；DialoguePlan 保存逐句 TTS
#     选择、机制参数与 Segment 内真实音频起点，有对白视频必须先完成对白音频生产。
# v35 地点库改为带强制说明的独立图片集合；全景图只提供确定性取景，取景结果
#     记录来源但独立存在；Shot 与 Keyframe 不再绑定地点视图，Scene 只保留可选语义地点。
# 更早版本按开发期规则不迁移，需新建项目。
PROJECT_SCHEMA_VERSION = 35
