# Project Workspaces

管理 `.stories/<项目名>-<project_id>/` 项目容器、项目列表和内部回收站。

创建时直接建立 `PROJECT_SCHEMA_VERSION` 指定的唯一当前 schema（现为 v32）`project.json`，固化 Core 生成的
Project ID、标题、用户选择的画面比例和不可变完整导演方案。项目列表只读取 `project.json`，没有独立
`stage`、shadow state 或双写文件。

领域恢复事实保存在 project.json；不创建或读取厂商会话、工作区与 runtime 目录。

Web 只能传 Project ID，不能传文件路径。无法通过当前 schema 校验的目录不会出现在列表，直接读取会要求
新建项目；读取、列表和服务启动都不会迁移、改写或另存旧 schema。删除把整个项目原子移动到
`.stories/.trash/`。

目录显示名保留中文项目名，清理路径/控制字符，最多 48 字符，后缀为完整 32 位 Project ID。同名项目不冲突。HTTP/MCP 和项目事实仍使用原 ID；目录解析集中在本模块，不接受客户端路径。既有纯 ID 目录只读取，不自动重命名或迁移 schema；同一 ID 出现多个普通目录时拒绝读取，符号链接不参与发现。回收目录保留显示名并追加时间和随机后缀。

创建必须提供旁白语言 `narration_languages`（中文 `zh`、英文 `en`，至少一种、不重复），由项目 Store 固化；没有修改语言的入口。
