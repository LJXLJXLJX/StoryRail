# media_submission/

L6 媒体提交。`MediaSubmissionUseCases` 仍是服务的调用入口，方法签名不变。
实现按能力拆在同包的 audio、image、video、frames、pano_view、assembly、animatic、narration。
地点主图与视图细化/转向在 image（输入与提示词由 `location_requests.py` 编译），室内视图的全景裁切在 pano_view；
裁切 Generation 冻结主图与几何，产物由回调直接写入视图 `crop_asset_id`，不是候选。
语音提交按能力解析 recipe，由 Core 填充语义角色并合入轨道机制参数，构造通用 RecipeRequest；其它提交构造 Core contracts，成功或失败都经 Store facade 写入 Generation。
