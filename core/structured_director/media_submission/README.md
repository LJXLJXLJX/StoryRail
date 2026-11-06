# media_submission/

L6 媒体提交。`MediaSubmissionUseCases` 仍是服务的调用入口，方法签名不变。
实现按能力拆在同包的 audio、image、video、frames、pano_view、assembly、animatic、narration。
独立地点图片生成在 image（输入与提示词由 `location_requests.py` 编译），全景查看器的确定性取景在 pano_view；
取景 Generation 冻结全景 Asset 与角度，产物由回调直接选给创建时的新普通图片。
语音提交按能力解析 recipe，由 Core 填充语义角色并合入轨道机制参数，构造通用 RecipeRequest；其它提交构造 Core contracts，成功或失败都经 Store facade 写入 Generation。
