<div align="center">

![OpenGuard Logo](docs/openguard-logo.svg)

# OpenGuard

**基于 LangGraph 的通用智能体：可观察的决策、可扩展的技能、执行前的协议校验**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](setup.py)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/ttguy0707/OpenGuard)](https://github.com/ttguy0707/OpenGuard/stargazers)

[中文](#中文) · [English](#english)

</div>

<a id="中文"></a>

## 项目概述

OpenGuard 受 [OpenClaw](https://github.com/openclaw/openclaw) 启发，以 Python 和 LangGraph 实现通用智能体工作流。项目围绕“模型决策 → 工具行动 → 结果观察”构建状态图，提供 SQLite 会话持久化、用户画像、上下文摘要、动态技能、定时任务、子 Agent 委派和结构化行为日志。

核心设计是 **help → run 两段式技能调用**：模型先获取技能说明，再决定执行或更换技能。当前版本在动态技能执行端加入一次性凭据校验，让调用顺序由代码落实。项目是单机 CLI 应用；OpenClaw 的产品理念与 SKILL.md 约定是参考来源，不代表对其 Node.js 代码的逐模块迁移或功能完全对等。

## 快速开始

需要 Python 3.10+。以下命令适用于 Linux / WSL2：

~~~bash
git clone https://github.com/ttguy0707/OpenGuard.git
cd OpenGuard
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
openguard config
openguard run
~~~

Windows PowerShell 激活虚拟环境时使用 .\.venv\Scripts\Activate.ps1。实际可用命令取决于宿主系统。

配置向导会写入模型设置并测试普通消息连通性。也可以复制 .env.example 为 .env，设置 DEFAULT_PROVIDER、DEFAULT_MODEL、对应 API Key 和 Base URL。请按所选提供商修改模板中的地址与模型。

- OpenAI 兼容接口使用 OPENAI_API_KEY 和可选的 OPENAI_API_BASE。
- Anthropic 分支需要额外安装 langchain-anthropic；Ollama 分支需要 langchain-community，并启动本地模型服务。这些可选分支尚未在本次回归中进行真实 API 验证。
- 默认数据目录为项目下 workspace；部署时可通过 OPENGUARD_WORKSPACE 指向自己的可写目录。
- 在另一个终端运行 openguard monitor 查看当前 CLI 会话的日志。
- 输入 /exit 结束 CLI；心跳任务也随主进程停止。

## 核心能力与当前实现

| 能力 | 实现 |
| --- | --- |
| 状态图工作流 | START → agent → tools → agent；模型不再返回 tool_calls 时结束本次请求 |
| 会话持久化 | CLI 使用 AsyncSqliteSaver 保存 messages 和 summary，通过 thread_id 关联会话 |
| 上下文压缩 | 按 HumanMessage 开始的完整回合裁剪；主调用达到 40 回合后保留最近 10 回合，并让 LLM 合并旧摘要 |
| 长期记忆 | Markdown 用户画像，支持读取及主动更新；每次模型决策注入画像 |
| 动态技能 | 扫描 office/skills 下的 SKILL.md 或 README.md，按需读取完整说明，执行前校验 help 凭据 |
| 子 Agent 委派 | 主 Agent 通过 delegate_task 调用代码审查/文档整理子 Agent，独立上下文、只读默认工具、预算与审计关联 |
| 行为日志 | 5 类 JSONL 事件，后台线程写盘，Rich 终端监控 |
| 定时任务 | 同进程心跳协程每 10 秒检查 tasks.json，支持一次性及 hourly/daily/weekly/monthly 规则 |
| 模型适配 | 模型工厂封装 OpenAI 兼容接口及 Anthropic、Ollama 分支 |
| 文件与 Shell 工具 | 相对路径校验、命令白名单、展开语法过滤、60 秒 subprocess 超时 |

函数 trim_context_messages 的默认参数为 8/4，agent_node 显式使用 40/10。水位可在代码调用参数中调整，当前没有对应的 CLI 配置项。达到阈值后裁剪，因此也不是固定每 40 个新增回合触发。按回合控制不等于按 token 控制。

SQLite checkpoint 保存可恢复的图状态；它不提供外部工具副作用的恰好一次执行。长期画像当前是全局文件，尚未按用户隔离。

## 两段式调用：从约定到强制校验

每次动态技能执行都需要新的 help：

1. help 返回完整说明和随机 help_token。
2. run 携带 command 和 help_token。
3. 加载器校验可信运行配置中的 thread_id、技能身份、说明路径及内容 SHA-256。
4. 凭据 300 秒有效，在调用执行器之前原子消费；同一凭据并发重用最多放行一次。

缺少凭据、跨会话/跨技能、过期、重放或说明变化都会拒绝执行。新的 help 替换本会话该技能的旧凭据；清缓存和进程重启也会撤销凭据。执行失败后应重新 help。

~~~python
import re
from openguard.core.skill_loader import load_dynamic_skills

# 先安装至少一个技能到 workspace/office/skills/<技能名>/
skill = load_dynamic_skills()[0]
config = {"configurable": {"thread_id": "demo-session"}}
manual = skill.invoke({"mode": "help"}, config=config)
token = re.search(r"help_token: ([A-Za-z0-9_-]+)", manual).group(1)

result = skill.invoke(
    {"mode": "run", "command": "echo {baseDir}", "help_token": token},
    config=config,
)
print(result)
~~~

CLI 中由模型从工具结果读取凭据并填入下一次调用。升级后请重启 CLI；SDK 调用方必须提供 thread_id。没有会话配置时仍可阅读 help，但不会签发凭据。

凭据证明相应会话获得了该版本说明，不证明模型理解正确、执行安全或用户已授权。该流程约束动态技能接口；内置 execute_office_shell 是单独的工具。完整迁移规则与限制见 [运行时修复说明](docs/RUNTIME_HARDENING.md)。

## Subagents：让主 Agent 委派子任务

默认 CLI 注册 delegate_task。主 Agent 可以使用以下两个预设角色，也可以按任务临时定义新的子 Agent，等待结果后汇总：

| 角色 | 用途 | 默认权限 |
| --- | --- | --- |
| code_reviewer | 代码阅读、缺陷分析、测试建议 | 列目录、读文件 |
| document_analyst | 资料提炼、比较、文档草稿 | 列目录、读文件 |

先将资料放在 workspace/office/ 下，再启动 openguard run，例如：

> 请让 code_reviewer 检查 project/heartbeat.py 的恢复逻辑，再由你汇总问题。

没有合适的预设角色时，主 Agent 可指定新 agent_name、instructions（职责/方法/输出要求）和 tool_names（所需工具），例如：

> 请临时定义一个测试设计师，阅读 project/agent.py，给出异常路径的测试方案，再由你整理。

动态角色默认可选工具为 list_office_files、read_office_file；不选工具时仅分析传入信息。宿主验证工具白名单，拒绝越权工具和对预设角色的覆盖。角色仅在本次委派生效，不会永久注册；模型、权限上限和预算仍由宿主配置。

每次子任务使用新的消息上下文和执行 thread_id，不继承父 checkpoint 或全局画像；模型只接收显式任务与必要背景。子 Agent 不能继续委派；自定义角色可以在宿主代码中显式选择模型和工具。动态技能仍需在子任务自身作用域中 help → run。

默认每个 app 最多 2 个并发子图调用，超额返回 busy；等待预算 120 秒，最多 16 个图步骤，返回结果最多 6000 字符。主 Agent 必须检查 completed、failed、timeout 等状态。超时是协作式取消，不能保证已启动的同步工具、线程或远端请求立即停止。

CLI 为主任务生成 run_id；子日志带 parent_run_id、agent_name、execution_thread_id，写入父会话日志，monitor 可显示关联。13 个基础内置工具之外，默认主 Agent 额外获得 1 个委派工具。

SDK 默认启用；allow_dynamic_subagents=False 可只保留预设角色，dynamic_subagent_tools 可调整动态角色的宿主工具白名单。显式 tools=[...] 保持原行为，可用 enable_subagents=True 开启或通过 subagent_specs 自定义；enable_subagents=False 可关闭。完整示例与预算配置见 [Subagents 使用说明](docs/SUBAGENTS.md)。

这是主任务等待结果的进程内委派，不是后台作业服务。子图不持久化，重启后不能续跑；工具注册隔离也不是 OS 沙盒。

## 技能安装与更新

将技能说明及脚本放在 workspace/office/skills/<技能名>/ 下。例如：

~~~text
workspace/office/skills/
└── my-skill/
    ├── SKILL.md
    └── scripts/
        └── main.py
~~~

SKILL.md 可以包含 name、description 元数据及操作说明。命令中的 {baseDir} 会替换为相对于 office 的技能目录。

支持读取 OpenClaw / Claude Code 风格的说明文件，但不自动实现两个生态的全部权限、依赖安装、钩子和运行时协议。脚本依赖与可用命令需要部署者准备。MCP 可通过第三方技能扩展；仓库没有独立的原生 MCP 会话客户端。

- 元数据扫描缓存 60 秒；说明每次 help/run 读取并校验，最多 64 KiB，超限明确拒绝。
- 内容缓存默认最多 50 条，凭据默认最多 1024 条。
- 说明改动后旧工具对象也能读到新内容，旧凭据失效。
- 新增、删除或改名后调用 reload_skills，并同步更新模型绑定与 ToolNode；CLI 可直接重启。
- 重复技能名、技能与内置工具重名会报错。

详见 [技能调用指南](docs/LAZY_LOADING_GUIDE.md) 与 [快速参考](docs/LAZY_LOADING_QUICKSTART.md)。

## 13 个内置工具

| 工具 | 用途 |
| --- | --- |
| get_current_time | 获取宿主本地时间 |
| calculator | 基于 AST 白名单的算术求值 |
| get_system_model_info | 读取环境中的模型配置 |
| read_user_profile / save_user_profile | 读取或覆盖长期画像 |
| schedule_task / list_scheduled_tasks | 创建或查询计划任务 |
| delete_scheduled_task / modify_scheduled_task | 删除或修改计划任务 |
| list_office_files / read_office_file | 列目录、读取文本 |
| write_office_file | 新建、覆盖或追加文本 |
| execute_office_shell | 校验后在 office 工作目录执行命令 |

## 行为审计与监控

埋点覆盖 llm_input、tool_call、tool_result、ai_message、system_action 五类事件：

- llm_input 记录消息数；tool_call 记录工具与参数；tool_result 记录结果前 200 字符。
- 工具审计参数及结果预览中的 help_token 会被遮盖。
- 日志后台写入 logs/<thread_id>.jsonl；默认有界队列为 4096 条。
- 队列满时丢弃新事件并增加 dropped_events；写入异常增加 write_errors。
- 正常关闭会停止接收事件并排空队列，重复 shutdown 不会再次等待已退出线程。

~~~bash
openguard monitor
tail -f logs/local_geek_master.jsonl
~~~

这是用于观察和排查的本地结构化日志。输入未保存完整 prompt，结果有截断，崩溃或队列满可能丢事件；不能据此宣称“100% 可追溯”或完整回放。monitor 默认读取 CLI 固定会话日志，其他 thread_id 的文件需单独查看。

## 执行与可靠性边界

- 文件工具使用规范路径的父子关系校验，拒绝绝对路径、盘符路径、同前缀兄弟目录及已存在的越界符号链接。
- Shell 采用命令白名单，过滤部分展开、重定向与解释器参数；执行超时设为 60 秒。超时不保证整棵子进程树停止，也没有独立资源配额。
- Shell 仍使用宿主权限；office 只是工作目录。路径检查与命令过滤不能限制脚本内部的全部 I/O，不能替代容器、低权限账号或 OS 隔离。
- 任务 JSON 通过临时文件、flush/fsync 和同目录原子替换更新，写失败保留旧文件；心跳写回失败不继续投递。
- JSON 写回和内存队列入队之间仍存在崩溃窗口，尚无持久化领取、ACK 或幂等任务执行协议。
- CLI 退出时先停止心跳生产者，再投递退出标记并排空队列。

## 评测口径

历史 README / 实验材料记录了 20 组人工构造的工具选择场景：

| 指标 | 单阶段 | 双阶段 |
| --- | --- | --- |
| 历史安全命中率 | 10/20（50%） | 18/20（90%） |
| 历史平均决策耗时 | 19.33 秒 | 23.88 秒 |

50% → 90% 是 **提升 40 个百分点**；上述数字未在本次修复后重新测量，不能当作通用任务准确率。旧材料把双阶段的 2 例失败同时描述为“事故”和“安全中止”，所以不继续引用“P0 事故下降 80%”作为结论。

[历史实验脚本](tests/test_two_phase_skills.py) 使用模拟工具，评分未严格核对当前场景的目标工具，基线可见信息不同，异常耗时也没有完整纳入统计。它使用独立的模拟工具实现，不验证新的 help_token 协议。重新评测应逐场景核验工具和参数，区分错误执行、拒绝、超时与成功，保存模型版本、随机种子和原始轨迹。

[懒加载测量示例](examples/benchmark_lazy_loading.py) 只报告实际运行的加载/help 耗时，不再输出未经测量的固定性能增益。

## 测试

确定性测试不调用真实模型，建议使用临时工作区：

~~~bash
OPENGUARD_WORKSPACE="$(mktemp -d)" python3 -m unittest discover -s tests
OPENGUARD_WORKSPACE="$(mktemp -d)" python3 tests/test_lazy_loader.py
~~~

2026-09-09 在 Ubuntu-24.04 / WSL2、Python 3.12.3 环境中：**130 项 unittest 通过**，独立懒加载脚本通过，wheel 隔离构建、安装并从仓库外导入成功。测试覆盖真实 ToolNode 及同步/异步图循环，模型与执行器使用替身；这不代表各模型提供商的端到端验收或代码覆盖率。

主要新增测试：

- tests/test_subagents.py：主/子真实图、上下文与工具隔离、并发、超时/取消、技能凭据作用域、审计和结果边界。

- tests/test_runtime_guards.py：顺序校验、令牌隔离/过期/重放/并发、文档变化、真实图配置传递、路径及日志。
- tests/test_task_storage_and_shutdown.py：原子写入失败、心跳投递边界、非法参数和退出排空。

## 项目结构

~~~text
OpenGuard/
├── openguard/core/
│   ├── agent.py          # 组装图、模型节点、摘要与审计埋点
│   ├── context.py        # AgentState、消息 reducer、完整回合裁剪
│   ├── skill_loader.py   # 技能发现、说明缓存、help 凭据与 run 校验
│   ├── subagents.py      # 子 Agent 注册、独立子图、预算、委派工具与审计
│   ├── provider.py       # 模型工厂
│   ├── config.py         # 工作目录、数据库和画像路径
│   ├── logger.py         # 有界异步 JSONL 日志
│   ├── heartbeat.py      # 到期任务检查、循环规则与投递
│   ├── task_storage.py   # 任务 JSON 原子写入
│   ├── bus.py            # 共享队列与生产者/消费者关闭顺序
│   └── tools/
│       ├── __init__.py   # 工具子包标记，确保 wheel 收录
│       ├── base.py       # 工具装饰器
│       ├── builtins.py   # 内置工具与注册表
│       └── sandbox_tools.py # 文件操作、路径和 Shell 校验
├── entry/
│   ├── cli.py            # 命令分发、配置向导
│   ├── main.py           # 交互循环、checkpoint、worker 与心跳
│   └── monitor.py        # Rich 日志查看器
├── examples/             # SDK 用法与局部性能测量
├── tests/                # 确定性回归与独立模型实验脚本
├── docs/                 # 运行时说明、技能指南、演示图片
├── setup.py              # 包发现、依赖与 CLI 注册
├── requirements.txt      # 运行依赖
└── .env.example          # 本地配置模板
~~~

运行时生成 workspace/state.sqlite3、workspace/tasks.json、workspace/memory/user_profile.md 和 office 等目录；这些数据不是随仓库提供的示例技能。

<a id="english"></a>

## English

OpenGuard is a Python / LangGraph CLI agent inspired by OpenClaw. It combines a model/tool state graph, SQLite checkpoints, Markdown profiles, context summaries, pluggable skills, scheduled tasks and structured event logs.

### Getting started

Use Python 3.10+, clone the repository, create a virtual environment and run:

~~~bash
python -m pip install -e .
openguard config
openguard run
# In another terminal:
openguard monitor
~~~

Configure the selected provider and its credentials using the wizard or .env.example. Anthropic and Ollama adapters require additional langchain-anthropic and langchain-community packages respectively. Actual provider API compatibility was not tested in this regression run.

### Enforced help → run

A dynamic skill's help response includes a one-use help_token. Each run requires that token and a trusted runtime thread_id. The loader binds the token to the session, skill and manual content hash, expires it after 300 seconds, and consumes it atomically before dispatch. Missing, stale, cross-session and replayed tokens are rejected. Restart the CLI after upgrading; SDK callers must supply session configuration.

This proves that the session received the manual version, not that the model understood it or that execution is authorized. Built-in Shell is a separate capability. See [runtime and migration notes](docs/RUNTIME_HARDENING.md).

### Subagents

The default CLI exposes delegate_task with code_reviewer and document_analyst presets, both limited to listing/reading office files. The main agent can also define a temporary role with a new agent_name, instructions and selected tool_names. The host validates the tool allowlist; an empty selection means text-only analysis. Dynamic definitions are invocation-local and cannot override presets. Models and execution budgets remain host-controlled. Each invocation starts with a fresh context and execution thread ID; it receives only the explicit task/context, does not inherit the parent checkpoint or global profile, and cannot delegate again.

The parent waits for a JSON result and checks its status. Defaults: 2 admitted graph calls per app, 120 seconds, 16 graph steps and 6000 result characters. Cancellation is cooperative and cannot forcibly stop running synchronous tools or remote requests. Child graphs are not persisted or resumed after a restart.

Child events stay in the parent's log file with run_id, parent_run_id, agent_name and execution_thread_id. SDK callers can register explicit role/model/tool configurations or disable delegation. allow_dynamic_subagents=False disables temporary roles only; dynamic_subagent_tools configures their allowed tool catalog. Existing explicit tools=[...] calls retain their tool list unless enabled. See [Subagents guide](docs/SUBAGENTS.md).

### Current behavior and limits

- The main agent trims at 40 user turns, keeps the latest 10 and merges older content into an LLM summary.
- AsyncSqliteSaver persists graph state. The global Markdown profile is not isolated by user.
- Five event types are logged through a bounded queue. Truncation, drops and crashes prevent a claim of complete audit delivery.
- Heartbeat runs every 10 seconds in the CLI process. It stops when the CLI exits.
- Task JSON writes are atomic, but durable queue handoff and exactly-once side effects are not implemented.
- File/path checks and a Shell allowlist reduce accidental misuse. Execution still uses host permissions and is not an OS sandbox.
- OpenClaw / Claude Code style skill manuals can be loaded; full runtime compatibility and native MCP sessions are not provided.

### Validation and historical metrics

On 2026-09-09, 130 deterministic unittest cases, the standalone lazy-loading test and an isolated wheel installation/import check passed under Ubuntu-24.04 / WSL2 with Python 3.12.3. Model and execution calls were replaced by test doubles.

Historical materials reported 10/20 versus 18/20 safe hits, an increase of 40 percentage points, with average latency of 19.33 versus 23.88 seconds. These simulated results have scoring and baseline limitations and have not been remeasured after this change. They are not production incident rates or general tool-call accuracy.

## 贡献与许可证 / Contributing and license

欢迎提交 Issue 和 Pull Request。涉及执行协议的改动请提供拒绝路径与成功路径测试，文档应区分当前实现、历史实验和计划能力。

本项目采用 [MIT License](LICENSE)。感谢 OpenClaw、LangGraph、LangChain、Rich 及项目贡献者。
