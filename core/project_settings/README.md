# Project settings

这里定义创建项目时由用户确定、此后只能读取的少量项目级设置。当前只有画面比例，允许 `16:9`、
`9:16` 或 `2:1`。权威值保存在 `project.json`，Agent 工作稿和 Provider 请求都只是它的消费者。
