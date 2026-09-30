# 技能快速开始

当前实现采用元数据扫描、有限内容缓存和强制 help/run 凭据校验。
完整协议、代码示例、缓存行为及已知限制统一维护在
[运行时修复与迁移说明](RUNTIME_HARDENING.md)。

- Skill 文档放在 workspace/office/skills/<name>/SKILL.md，或 README.md。
- 说明中的 name/description 应位于开头 50 行；文件采用 UTF-8。
- help 返回完整说明及一次性 help_token；run 需要 command 和 help_token。
- SDK 调用需在 config.configurable.thread_id 指定会话；CLI 自动传入。
- 每次执行都需新凭据，说明变化、过期、清缓存、重复使用和重启后均需重新 help。
- 修改说明会在旧工具的下一次调用中检测到；新增技能需重新扫描并重绑 Agent 工具集合。
- 原文档的零延迟、无限扩展和百分比性能结论已移除，未以测量支持的数字不作为当前承诺。

可运行 examples/benchmark_lazy_loading.py 查看当前机器上的局部测量。
