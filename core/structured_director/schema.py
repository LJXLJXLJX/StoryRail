"""当前唯一受支持的 project.json schema。"""

# v28 引入地点库（location_library：地点、陈设、状态、机位视图）；
# Scene 绑定地点与状态，Shot 绑定视图，Keyframe 引用视图。
# v30 角色图以造型为唯一单位（CharacterLook.selected_asset_id），Keyframe 按造型选择角色图。
# v31 角色卡标记非人形（CharacterCard.non_humanoid），造型设定图按形体选择版式。
# v32 创建时固化旁白语言（narration_languages），未选语言轨道、音色与成片字段为 null；
#     移除 v31 的 non_humanoid，非人形设定图改由提示词约束。
# v33 Scene 下并列 shots（创作层）与 segments（生产层，shot_ids 记录覆盖的 Shot）；
#     旁白 Cue 删除 Shot 锚点，Narration Scene 的唯一 Cue 覆盖整个 Scene。
# 更早版本按开发期规则不迁移，需新建项目。
PROJECT_SCHEMA_VERSION = 33
