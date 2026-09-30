# 执行协议与本次运行时修复

后续新增的子 Agent 委派与独立执行作用域见 [Subagents 说明](SUBAGENTS.md)。以下 93 项结果记录的是强制校验修复阶段；包含子 Agent 的最新回归结果见 README。

## help → run：现在由代码强制

每次动态 Skill 执行都需要一次新的 help：

1. help 返回完整说明和随机 help_token。
2. run 携带 command 和 help_token。
3. 服务端验证会话 thread_id、技能目录身份、技能说明实际路径、说明内容 SHA-256、300 秒有效期。
4. 凭据在进入执行器前原子消费，只能使用一次；执行失败后也必须重新 help。

没有凭据、伪造凭据、跨会话/跨技能、过期、重复使用、说明变化、说明被删除时，
run 均返回权限拒绝，执行器不会被调用。并发重用同一个凭据最多放行一次。
一个新的 help 会取代本会话同一技能的旧凭据。清缓存和进程重启也会失效。

运行时配置由 LangGraph 传入，不在模型可填写的工具 schema 中：

~~~python
import re
from openguard.core.skill_loader import load_dynamic_skills

tool = load_dynamic_skills()[0]
config = {"configurable": {"thread_id": "my-session"}}
manual = tool.invoke({"mode": "help"}, config=config)
token = re.search(r"help_token: ([A-Za-z0-9_-]+)", manual).group(1)
result = tool.invoke(
    {"mode": "run", "command": "echo {baseDir}", "help_token": token},
    config=config,
)
~~~

日常 CLI 会由模型读取 help 的返回结果并填入 run，用户不需要手动复制凭据。
SDK 调用方必须提供稳定的 thread_id。没有 thread_id 时可以阅读 help，但不会签发凭据。
原来的仅传 mode=run、command 的调用会被拒绝，这是有意的协议变更。
当前已经运行的 CLI 需重启，才能使用新的工具 schema 和实现。

这不是“确认过一定安全”的证明。它只证明执行前已向相应会话返回该版本的说明；
不证明模型理解正确，也不代替用户授权。凭据留在进程内，checkpoint 恢复后需重新 help。

## 说明版本与缓存

- 说明最多 64 KiB。返回完整内容，取消原来的 3000 字符静默截断；超过上限明确拒绝。
- 每次 help/run 重新读取有大小上限的原始字节并计算 SHA-256，即使 mtime 和文件大小未变，也能检测内容变化。
- cache_size 控制当前加载器的内容缓存条目上限；缓存解码文本，不承诺免除文件校验 I/O。
- 元数据目录扫描缓存 60 秒；新增、删除、改名后调用 reload_skills 得到新的工具列表。
- 修改说明后，旧工具对象的 help 也能读取新内容；新增工具仍需要同步重建/绑定模型和 ToolNode。
- clear_skill_cache 和 reload_skills 会撤销已签发凭据。
- 凭据最多保留 1024 个，按过期与容量规则清理；容量驱逐后需要重新 help。
- 说明版本不覆盖目录中所有脚本/依赖；执行前后的文件变化竞态也不能靠文档哈希完全解决。
- 重复技能名，以及内置工具与技能重名，会明确报错。

## 其他修复

| 模块 | 改动 |
| --- | --- |
| 路径 | 使用 resolve 后的父子关系，拒绝同前缀兄弟目录、越界符号链接和绝对/盘符路径 |
| Shell | 不允许通过带路径前缀的命令名绕过白名单名称检查 |
| 文件读取 | 最多读取 10001 字符后判断截断，避免先把大文件读入内存 |
| 日志 | 有界队列；可观察 dropped_events/write_errors；幂等关闭；关闭后不再入队 |
| Agent | 向模型透传 RunnableConfig；在工具审计参数/结果预览中遮盖 help_token |
| 监视器 | 补充 ai_message 展示分支 |
| 工具注册 | 补全 read_user_profile，与保存工具说明一致 |
| 任务 JSON | 临时文件写入、flush/fsync、同目录原子替换；失败保留旧文件 |
| 心跳 | 写回失败不继续投递；无效任务记录保留并记日志 |
| 退出 | 先取消并等待心跳生产者，再投递消费者退出标记并排空队列 |
| 任务参数 | 校验 repeat 和重复次数；可空参数 schema 与函数行为一致 |
| 上下文 | 校验 1 <= keep_turns <= trigger_turns |
| 打包 | 补 tools/__init__.py，去掉不存在的顶层 cli 模块，声明 Python >= 3.10 |

日志默认队列满时丢弃新事件并增加 dropped_events，而不是无限占用内存。
这仍是尽力而为的本地日志，不是可靠审计存储。构造 JSONLEventLogger 现在创建独立实例，
共享调用仍使用模块级 audit_logger。

## 明确保留的边界

- help/run gate 作用于动态 Skill 接口。内置 execute_office_shell 是另一项能力，
  此次没有把它改成统一授权代理。该 gate 不构成抵御任意代码执行的安全沙盒。
- Shell 仍在宿主权限下执行；解释器可以访问宿主资源。运行不可信技能需进一步做 OS 隔离。
- 路径规范化不能消除检查后替换链接的竞态；高威胁环境需安全打开原语/独立执行环境。
- 任务仍使用 JSON + 内存队列，仍存在“写回后、入队前崩溃”的可靠性交接缺口。
  原子文件写入仅解决文件半写和写入失败问题，不提供可靠队列、任务 ACK 或 exactly-once。
- Heartbeat 是同进程每 10 秒检查的协程，退出后不继续执行；不是系统守护服务。
- 裁剪调用值仍为 40/10，未改为 token 预算；摘要、画像和多租户隔离没有在本次重构。
- 历史两阶段实验和懒加载性能百分比未在本次重跑，不应作为此次修复后的测量结论。
- Anthropic/Ollama 的可选适配依赖与各提供商真实 API 兼容性仍需另做安装、端到端验证。

## 验证

Ubuntu-24.04 / WSL2，Python 3.12.3；沿用用户现有 LangGraph 1.1.6、
langchain-core 1.2.26、Pydantic 2.12.5 和 SQLite checkpoint 3.0.3。

~~~bash
OPENGUARD_WORKSPACE="$(mktemp -d)" python3 -m unittest discover -s tests
OPENGUARD_WORKSPACE="$(mktemp -d)" python3 tests/test_lazy_loader.py
~~~

本次本地回归覆盖真实图中的 ToolNode 和同步/异步 Agent Loop，模型和 Shell 使用替身，
不向真实模型发请求。新测试位于 tests/test_runtime_guards.py 和
tests/test_task_storage_and_shutdown.py。原有 .gitignore 本地改动保持不变。

验证结果：93 项 unittest 回归通过，独立懒加载脚本通过；wheel 在隔离目录构建、安装并从仓库外成功导入 tools、agent、CLI。
