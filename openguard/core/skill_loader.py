"""Lazy skills with a session-bound, one-use help/run gate."""
import hashlib
from pathlib import Path
import re
import secrets
import threading
import time
from collections import OrderedDict
from typing import Literal
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from .config import SKILLS_DIR
from .tools.sandbox_tools import execute_office_shell

MAX_SKILL_BYTES = 64 * 1024

class DynamicSkillInput(BaseModel):
    mode: Literal["help", "run"] = Field(description="先 help 阅读说明并获取凭据，再 run 执行。")
    command: str = Field(default="", description="run 的完整命令，保留 {baseDir} 占位符。")
    help_token: str = Field(default="", description="run 必填：本会话 help 返回的一次性 help_token。")

class LazySkillLoader:
    """Metadata TTL: 60s. Manual bytes are verified on every help/run.

    Grants expire and are consumed before dispatch. Restart requires help again.
    This proves manual delivery, not human authorization or script isolation.
    """
    def __init__(self, cache_size=50, grant_ttl=300, max_grants=1024):
        if cache_size < 1 or grant_ttl <= 0 or max_grants < 1:
            raise ValueError("cache_size、grant_ttl 和 max_grants 必须大于 0")
        self._cache_size, self._grant_ttl, self._max_grants = cache_size, grant_ttl, max_grants
        self._skill_registry, self._last_scan_time, self._scan_interval = None, 0.0, 60
        self._lock = threading.RLock()
        self._content_cache, self._grants = OrderedDict(), OrderedDict()

    def _snapshot(self, md_path):
        root, path = Path(SKILLS_DIR).resolve(), Path(md_path).resolve(strict=True)
        if not path.is_relative_to(root):
            raise PermissionError("技能说明必须位于 skills 目录内")
        with path.open("rb") as stream:
            raw = stream.read(MAX_SKILL_BYTES + 1)
        if len(raw) > MAX_SKILL_BYTES:
            raise ValueError(f"技能说明超过 {MAX_SKILL_BYTES} 字节，请精简；不会截断后授权")
        version = hashlib.sha256(raw).hexdigest()
        key = (str(path), version)
        with self._lock:
            content = self._content_cache.get(key)
            if content is None:
                content = raw.decode("utf-8")
                self._content_cache[key] = content
            self._content_cache.move_to_end(key)
            while len(self._content_cache) > self._cache_size:
                self._content_cache.popitem(last=False)
        return str(path), version, content

    def _load_skill_content(self, md_path, mtime=None):
        # Compatibility helper; a captured mtime must never authorize execution.
        return self._snapshot(md_path)[2]

    @staticmethod
    def _session_id(config):
        value = (config or {}).get("configurable", {}).get("thread_id")
        return str(value) if value is not None and str(value).strip() else None

    def _issue_grant(self, session, path, version):
        now = time.monotonic()
        with self._lock:
            for token, grant in list(self._grants.items()):
                if grant[3] <= now or grant[:2] == (session, path):
                    del self._grants[token]
            token = secrets.token_urlsafe(32)
            self._grants[token] = (session, path, version, now + self._grant_ttl)
            while len(self._grants) > self._max_grants:
                self._grants.popitem(last=False)
            return token

    def _consume_grant(self, token, session, path, version):
        with self._lock:
            grant = self._grants.get(token)
            if grant is None:
                return False
            if grant[3] <= time.monotonic():
                del self._grants[token]
                return False
            if grant[:3] != (session, path, version):
                return False
            del self._grants[token]
            return True

    def _extract_metadata(self, md_path):
        with open(md_path, "rb") as stream:
            lines, remaining = [], MAX_SKILL_BYTES
            for _ in range(50):
                if remaining <= 0:
                    break
                line = stream.readline(remaining)
                if not line:
                    break
                lines.append(line)
                remaining -= len(line)
        content = b"".join(lines).decode("utf-8", errors="replace")
        name = re.search(r"^name:[ \t]*(.+)$", content, re.MULTILINE)
        desc = re.search(r"^description:[ \t]*(.+)$", content, re.MULTILINE)
        raw_name = name.group(1).strip().strip("\"'") if name else Path(md_path).parent.name
        tool_name = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_name)
        if not tool_name:
            raise ValueError("技能名称不能为空")
        return {"raw_name": raw_name, "name": tool_name,
                "description": desc.group(1).strip().strip("\"'") if desc else f"提供 {raw_name} 相关功能"}

    def _scan_skills(self, force_rescan=False):
        with self._lock:
            now = time.monotonic()
            if not force_rescan and self._skill_registry is not None and now-self._last_scan_time < self._scan_interval:
                return self._skill_registry
            root, skills, names = Path(SKILLS_DIR).resolve(), [], set()
            if root.is_dir():
                for folder in sorted(root.iterdir()):
                    if not folder.is_dir() or not folder.resolve().is_relative_to(root):
                        continue
                    md = folder / "SKILL.md"
                    if not md.is_file():
                        md = folder / "README.md"
                    if not md.is_file() or not md.resolve().is_relative_to(root):
                        continue
                    metadata = self._extract_metadata(str(md))
                    if metadata["name"] in names:
                        raise ValueError(f"技能名称冲突: {metadata['name']}")
                    names.add(metadata["name"])
                    skills.append({"folder": folder.name, "md_path": str(md), **metadata})
            self._skill_registry, self._last_scan_time = skills, now
            return skills

    def _create_lazy_tool(self, skill_info):
        def lazy_runner(mode: str, command: str = "", help_token: str = "", config: RunnableConfig = None) -> str:
            session = self._session_id(config)
            if mode == "run" and (not session or not help_token or not command.strip()):
                return "权限拒绝：run 需要 thread_id、非空 command 和本会话 help 返回的 help_token。"
            if mode not in ("help", "run"):
                return "错误：mode 只能是 help 或 run。"
            try:
                path, version, content = self._snapshot(skill_info["md_path"])
            except (OSError, ValueError) as exc:
                return f"权限拒绝：无法读取当前技能说明，请修复后重新 help。{exc}"
            if mode == "help":
                manual = f"========== 【{skill_info['raw_name']} 完整说明书】 ==========\n{content}\n====================================\n"
                if not session:
                    return manual + "未提供 config.configurable.thread_id：可阅读说明，但不会签发执行凭据。"
                token = self._issue_grant(session, (skill_info["folder"], path), version)
                return (manual + f"help_token: {token}\n"
                        f"有效期 {self._grant_ttl:g} 秒，仅限本会话、本技能当前说明版本使用一次。\n"
                        "确认适用后以 mode=run、command 和 help_token 调用；执行失败或说明变化后需重新 help。")
            if not self._consume_grant(help_token, session, (skill_info["folder"], path), version):
                return "权限拒绝：help_token 无效、已使用、过期、跨会话/技能或说明版本已变化。请重新 help。"
            actual_cmd = command.replace("{baseDir}", f"skills/{skill_info['folder']}")
            return execute_office_shell.invoke({"command": actual_cmd}, config=config)
        return StructuredTool.from_function(
            func=lazy_runner, name=skill_info["name"], args_schema=DynamicSkillInput,
            description=(skill_info["description"] + "\n外部技能：每次执行必须先 help 获取一次性 help_token，"
                         "再 run(command, help_token)。服务端校验会话、说明版本、有效期和重复使用。"))

    def get_all_tools(self, force_rescan=False):
        return [self._create_lazy_tool(info) for info in self._scan_skills(force_rescan)]

    def get_tool_count(self):
        return len(self._scan_skills())

    def clear_cache(self):
        with self._lock:
            self._content_cache.clear()
            self._skill_registry = None
            self._grants.clear()

_lazy_loader = LazySkillLoader()

def load_dynamic_skills(force_rescan=False):
    return _lazy_loader.get_all_tools(force_rescan)

def reload_skills():
    """Clear grants/cache and return new tools; existing graphs need rebinding."""
    _lazy_loader.clear_cache()
    return _lazy_loader.get_all_tools(force_rescan=True)

def get_skill_count():
    return _lazy_loader.get_tool_count()

def clear_skill_cache():
    _lazy_loader.clear_cache()
