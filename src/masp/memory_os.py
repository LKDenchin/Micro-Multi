"""Multi-Layer Persistent Memory Operating System (Memory OS) for MASP.

Inspired by:
- Mem0 (hybrid user/project/session memory with automatic fact extraction & deduplication)
- Letta / MemGPT (in-context Core Memory blocks + out-of-context Archival/Episodic Recall)
- MemOS & OpenMemory (hierarchical Working, Episodic, and Semantic memory scheduling)
- Cognee & Graphmem (lightweight Entity & File relationship knowledge graph)
"""

from __future__ import annotations

import json
import math
import re
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _tokenize_for_retrieval(text: str) -> list[str]:
    """Hybrid tokenizer supporting both English/code identifiers and Chinese character n-grams."""
    if not text:
        return []
    lower = text.lower()
    tokens: list[str] = []
    # 1. Alphanumeric & path/symbol tokens
    for match in re.finditer(r"[a-z0-9_./-]+", lower):
        tok = match.group(0).strip("./-_")
        if tok:
            tokens.append(tok)
            if "/" in tok or "." in tok or "_" in tok:
                for sub in re.split(r"[/_.-]+", tok):
                    if len(sub) >= 2:
                        tokens.append(sub)
    # 2. CJK characters and bigrams
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", lower)
    for run in cjk_runs:
        for ch in run:
            tokens.append(ch)
        for i in range(len(run) - 1):
            tokens.append(run[i : i + 2])
    return tokens


def _compute_similarity(query_tokens: list[str], doc_tokens: list[str]) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    q_counts = Counter(query_tokens)
    d_counts = Counter(doc_tokens)
    intersection = set(q_counts.keys()) & set(d_counts.keys())
    if not intersection:
        return 0.0
    dot = sum(q_counts[t] * d_counts[t] for t in intersection)
    q_norm = math.sqrt(sum(v * v for v in q_counts.values()))
    d_norm = math.sqrt(sum(v * v for v in d_counts.values()))
    if q_norm == 0.0 or d_norm == 0.0:
        return 0.0
    cosine = dot / (q_norm * d_norm)
    overlap_ratio = len(intersection) / max(1, len(set(query_tokens)))
    return 0.65 * cosine + 0.35 * overlap_ratio


class MemoryOS:
    """Persistent multi-tier Memory Operating System for Main Agent and Subagents."""

    DEFAULT_CORE_BLOCKS = {
        "persona": "你是由主 Agent 与专业子 Agent 协同运转的工程级智能体系统，具备分层记忆、连续工作、自主审查与自愈纠错能力。",
        "human": "",
        "user_preferences": "",
        "project_architecture": "",
        "working_context": "",
        "active_directives": "",
    }

    BLOCK_ALIASES = {
        "human": "user_preferences",
        "user_preferences": "human",
        "working_context": "active_directives",
        "active_directives": "working_context",
    }

    def __init__(
        self,
        first_path: Path | str | None = None,
        second_path: Path | str | None = None,
        *,
        workspace_root: Path | str | None = None,
        global_home: Path | str | None = None,
        project_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.project_id = project_id
        self.workspace_root: Path | None
        if workspace_root is not None:
            self.workspace_root = Path(workspace_root).resolve()
            self.global_home = (
                Path(global_home).resolve()
                if global_home is not None
                else (Path(first_path).resolve() if first_path is not None else None)
            )
        elif first_path is not None and second_path is not None:
            p1 = Path(first_path).resolve()
            p2 = Path(second_path).resolve()
            # If p2 is a git workspace or p1 has a global store structure, map appropriately
            if (p2 / ".git").exists() or (p1 / "store.db").exists() or (p1 / "memory").exists():
                self.global_home = p1
                self.workspace_root = p2
            else:
                self.workspace_root = p1
                self.global_home = p2
        elif first_path is not None:
            self.workspace_root = Path(first_path).resolve()
            self.global_home = Path(global_home).resolve() if global_home is not None else None
        else:
            self.workspace_root = None
            self.global_home = Path(global_home).resolve() if global_home is not None else None

    def _project_memory_file(self) -> Path | None:
        if not self.workspace_root:
            return None
        mem_dir = self.workspace_root / ".masp" / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        return mem_dir / "memory_os.json"

    def _global_memory_file(self) -> Path | None:
        if not self.global_home:
            return None
        mem_dir = self.global_home / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        return mem_dir / "global_memory_os.json"

    def _empty_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "core_memory": dict(self.DEFAULT_CORE_BLOCKS),
            "semantic_memories": [],
            "archival_memories": [],
            "episodic_memories": [],
            "knowledge_graph": {
                "entities": {},
                "relations": [],
            },
            "processes": {},
            "updated_at": _utc_now(),
        }

    def _load_file(self, path: Path | None) -> dict[str, Any]:
        if path is None or not path.is_file():
            return self._empty_state()
        try:
            raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(raw, dict):
                return self._empty_state()
            state = self._empty_state()
            if isinstance(raw.get("core_memory"), dict):
                for k, v in raw["core_memory"].items():
                    state["core_memory"][str(k)] = str(v or "")
            if isinstance(raw.get("semantic_memories"), list):
                state["semantic_memories"] = [
                    m for m in raw["semantic_memories"] if isinstance(m, dict) and m.get("content")
                ]
            if isinstance(raw.get("archival_memories"), list):
                state["archival_memories"] = [
                    a for a in raw["archival_memories"] if isinstance(a, dict) and a.get("content")
                ]
            if isinstance(raw.get("episodic_memories"), list):
                state["episodic_memories"] = [
                    e for e in raw["episodic_memories"] if isinstance(e, dict)
                ]
            if isinstance(raw.get("knowledge_graph"), dict):
                kg = raw["knowledge_graph"]
                state["knowledge_graph"] = {
                    "entities": kg.get("entities") if isinstance(kg.get("entities"), dict) else {},
                    "relations": kg.get("relations")
                    if isinstance(kg.get("relations"), list)
                    else [],
                }
            if isinstance(raw.get("processes"), dict):
                state["processes"] = {
                    str(k): dict(v) for k, v in raw["processes"].items() if isinstance(v, dict)
                }
            return state
        except Exception:
            return self._empty_state()

    def _save_file(self, path: Path | None, state: dict[str, Any]) -> None:
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            state["updated_at"] = _utc_now()
            path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def load_state(self, scope: str = "project") -> dict[str, Any]:
        if scope == "global":
            return self._load_file(self._global_memory_file() or self._project_memory_file())
        return self._load_file(self._project_memory_file() or self._global_memory_file())

    def save_state(self, state: dict[str, Any], scope: str = "project") -> None:
        if scope == "global":
            target = self._global_memory_file() or self._project_memory_file()
        else:
            target = self._project_memory_file() or self._global_memory_file()
        self._save_file(target, state)

    # =========================================================================
    # Tier 1: Core / Working Memory (Letta / MemGPT style)
    # =========================================================================
    def get_core_memory(self) -> dict[str, str]:
        proj_state = self.load_state("project")
        glob_state = self.load_state("global") if self.global_home else self._empty_state()
        merged = dict(self.DEFAULT_CORE_BLOCKS)
        for k, v in glob_state.get("core_memory", {}).items():
            if v:
                merged[k] = str(v)
        for k, v in proj_state.get("core_memory", {}).items():
            if v:
                if k == "user_preferences" and merged.get(k) and merged[k] != v:
                    merged[k] = f"{merged[k]}\n{v}".strip()
                else:
                    merged[k] = str(v)
        return merged

    def update_core_memory(
        self, block: str, content: str, mode: str = "append", scope: str = "project"
    ) -> dict[str, Any]:
        block_key = block.strip() or "active_directives"
        state = self.load_state(scope)
        core = state.setdefault("core_memory", dict(self.DEFAULT_CORE_BLOCKS))
        existing = str(core.get(block_key, "")).strip()
        clean_new = content.strip()
        if mode == "replace" or not existing:
            core[block_key] = clean_new
        else:
            if clean_new and clean_new not in existing:
                core[block_key] = f"{existing}\n- {clean_new}".strip()
        # Keep core block bounded
        if len(core[block_key]) > 2400:
            core[block_key] = core[block_key][-2400:]
        alias = self.BLOCK_ALIASES.get(block_key)
        if alias:
            core[alias] = core[block_key]
        self.save_state(state, scope)
        return {"block": block_key, "content": core[block_key], "scope": scope}

    def core_memory_append(
        self, label: str, content: str, scope: str = "project"
    ) -> dict[str, Any]:
        """Letta Core Memory append operation."""
        return self.update_core_memory(label, content, mode="append", scope=scope)

    def core_memory_replace(
        self, label: str, old_content_or_new: str, new_content: Any = None, scope: str = "project"
    ) -> dict[str, Any]:
        """Letta Core Memory replace operation."""
        state = self.load_state(scope)
        core = state.setdefault("core_memory", dict(self.DEFAULT_CORE_BLOCKS))
        key = label.strip() or "active_directives"
        existing = str(core.get(key, "")).strip()

        if new_content is None or isinstance(new_content, int):
            updated = str(old_content_or_new).strip()
        elif isinstance(new_content, str):
            old_str = str(old_content_or_new)
            if old_str and old_str in existing:
                updated = existing.replace(old_str, new_content.strip())
            else:
                updated = new_content.strip()
        else:
            updated = str(old_content_or_new).strip()

        core[key] = updated[:2400]
        alias = self.BLOCK_ALIASES.get(key)
        if alias:
            core[alias] = core[key]
        self.save_state(state, scope)
        return {"block": key, "content": core[key], "scope": scope}

    def core_memory_get(self, label: str, scope: str = "project") -> str:
        """Letta Core Memory read operation."""
        all_blocks = self.get_core_memory()
        return all_blocks.get(label.strip(), "")

    # =========================================================================
    # Tier 1.5: Archival & Recall Memory (Letta style external memory)
    # =========================================================================
    def archival_memory_insert(
        self,
        content: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        scope: str = "project",
    ) -> dict[str, Any]:
        """Insert long-term document or knowledge into Letta Archival Memory."""
        clean = (content or "").strip()
        if not clean:
            raise ValueError("归档记忆内容不能为空")
        state = self.load_state(scope)
        archival = state.setdefault("archival_memories", [])
        norm_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
        record = {
            "id": f"arch_{uuid.uuid4().hex[:10]}",
            "content": clean,
            "tags": norm_tags,
            "metadata": dict(metadata or {}),
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
        }
        archival.append(record)
        if len(archival) > 500:
            state["archival_memories"] = archival[-500:]
        self.save_state(state, scope)
        return {**record, "action": "inserted_archival"}

    def archival_memory_search(
        self, query: str, limit: int = 5, scope: str = "project"
    ) -> list[dict[str, Any]]:
        """Search Letta Archival Memory by token & semantic similarity."""
        state = self.load_state(scope)
        records = state.get("archival_memories", [])
        if not records:
            records = state.get("semantic_memories", [])
        q_clean = (query or "").strip()
        q_tokens = _tokenize_for_retrieval(q_clean)
        scored = []
        for r in records:
            text = f"{r.get('content', '')} {' '.join(r.get('tags') or [])}"
            sim = _compute_similarity(q_tokens, _tokenize_for_retrieval(text)) if q_tokens else 0.5
            if not q_tokens or sim > 0.05:
                scored.append((sim, r))
        scored.sort(key=lambda p: p[0], reverse=True)
        return [{**item, "similarity": round(score, 3)} for score, item in scored[: max(1, limit)]]

    def recall_memory_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search Letta Recall Memory (conversational episodic history & turn logs)."""
        state = self.load_state("project")
        episodes = state.get("episodic_memories", [])
        q_clean = (query or "").strip()
        q_tokens = _tokenize_for_retrieval(q_clean)
        scored = []
        for ep in episodes:
            text = f"{ep.get('user_request', '')} {ep.get('outcome_summary', '')} {' '.join(ep.get('changed_files') or [])}"
            sim = _compute_similarity(q_tokens, _tokenize_for_retrieval(text)) if q_tokens else 0.4
            if not q_tokens or sim > 0.05:
                scored.append((sim, ep))
        scored.sort(key=lambda p: p[0], reverse=True)
        return [{**ep, "similarity": round(score, 3)} for score, ep in scored[: max(1, limit)]]

    # =========================================================================
    # Operating System-Style Process & Subagent Lifecycle Management
    # =========================================================================
    def register_process(
        self,
        agent_id: str,
        name: str = "",
        role: str = "",
        task: Any = "",
        model: str = "",
        owned_paths: list[str] | None = None,
        route: str = "",
    ) -> dict[str, Any]:
        """Register a sub-agent as an OS process (PCB) with state tracking."""
        state = self.load_state("project")
        processes = state.setdefault("processes", {})
        pid = f"proc_{agent_id}"

        # Handle positional parameter flexibility where (agent_id, task_or_name, model, owned_paths)
        if isinstance(task, list) and owned_paths is None:
            owned_paths = task
            if not model and role:
                model = role
            task = name

        chosen_model = model or route or "default"
        record = {
            "pid": pid,
            "agent_id": agent_id,
            "name": name or agent_id,
            "role": role or name or "agent",
            "task": str(task) if not isinstance(task, list) else "",
            "model": chosen_model,
            "route": chosen_model,
            "owned_paths": list(owned_paths or []),
            "state": "running",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
        }
        processes[agent_id] = record
        processes[pid] = record
        self.save_state(state, "project")
        return record

    def pause_process(self, agent_id_or_pid: str) -> bool:
        """Pause a sub-agent process (OS preemptive pause)."""
        state = self.load_state("project")
        processes = state.setdefault("processes", {})
        target = processes.get(agent_id_or_pid)
        if target:
            target["state"] = "paused"
            target["updated_at"] = _utc_now()
            self.save_state(state, "project")
            return True
        return False

    def resume_process(
        self,
        agent_id_or_pid: str,
        updated_task: str | None = None,
        updated_model: str | None = None,
        updated_route: str | None = None,
    ) -> bool:
        """Resume a paused sub-agent process with updated task instructions and model routing."""
        state = self.load_state("project")
        processes = state.setdefault("processes", {})
        target = processes.get(agent_id_or_pid)
        if target:
            target["state"] = "running"
            if updated_task is not None:
                target["task"] = updated_task
            model_val = updated_model or updated_route
            if model_val is not None:
                target["model"] = model_val
                target["route"] = model_val
            target["updated_at"] = _utc_now()
            self.save_state(state, "project")
            return True
        return False

    def update_process(self, agent_id_or_pid: str, **updates: Any) -> dict[str, Any] | None:
        """Update properties of an agent process (task description, model routing, etc.)."""
        state = self.load_state("project")
        processes = state.setdefault("processes", {})
        target = processes.get(agent_id_or_pid)
        if target:
            for k, v in updates.items():
                if v is not None:
                    target[k] = v
            target["updated_at"] = _utc_now()
            self.save_state(state, "project")
            return target
        return None

    def list_processes(self) -> list[dict[str, Any]]:
        """List all active and recent sub-agent processes."""
        state = self.load_state("project")
        processes = state.get("processes", {})
        seen = set()
        result = []
        for p in processes.values():
            aid = p.get("agent_id")
            if aid and aid not in seen:
                seen.add(aid)
                result.append(p)
        return result

    def get_process(self, agent_id_or_pid: str) -> dict[str, Any] | None:
        """Get process control block for a specific agent."""
        state = self.load_state("project")
        processes = state.get("processes", {})
        return processes.get(agent_id_or_pid)

    # =========================================================================
    # Letta Context Window Overview (MMU)
    # =========================================================================
    def get_context_overview(
        self,
        max_tokens: int = 64000,
        current_messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Calculate comprehensive token and memory metrics across Memory OS tiers."""
        core = self.get_core_memory()
        core_chars = sum(len(v) for v in core.values())
        core_tokens = max(1, int(core_chars / 3.0))

        state = self.load_state("project")
        archival_chars = sum(
            len(str(a.get("content", ""))) for a in state.get("archival_memories", [])
        )
        archival_tokens = max(0, int(archival_chars / 3.0))

        recall_chars = sum(
            len(str(e.get("user_request", "")) + str(e.get("outcome_summary", "")))
            for e in state.get("episodic_memories", [])
        )
        recall_tokens = max(0, int(recall_chars / 3.0))

        msgs = current_messages or []
        msgs_chars = sum(len(str(m.get("content") or "")) for m in msgs)
        msgs_tokens = max(0, int(msgs_chars / 2.5))

        total_used = core_tokens + msgs_tokens
        limit = max(1000, max_tokens)
        pct = min(100.0, round((total_used / limit) * 100, 1))

        return {
            "context_window_size_max": limit,
            "context_window_size_current": total_used,
            "total_tokens": total_used,
            "core_memory": core,
            "core_memory_tokens": core_tokens,
            "archival_memory_tokens": archival_tokens,
            "recall_memory_tokens": recall_tokens,
            "messages_tokens": msgs_tokens,
            "remaining_tokens": max(0, limit - total_used),
            "utilization_pct": pct,
            "num_messages": len(msgs),
            "num_core_blocks": len(core),
            "num_archival": len(state.get("archival_memories", [])),
            "num_recall_episodes": len(state.get("episodic_memories", [])),
        }

    # =========================================================================
    # Tier 2: Semantic Fact Memory (Mem0 style add/deduplicate/update/delete)
    # =========================================================================
    def store_memory(
        self,
        content: str,
        *,
        category: str = "fact",
        tier: str = "semantic",
        tags: list[str] | None = None,
        importance: int | float = 3,
        scope: str = "project",
        source: str = "agent",
    ) -> dict[str, Any]:
        clean_content = (content or "").strip()
        if not clean_content:
            raise ValueError("记忆内容不能为空")
        if tier == "core":
            block_map = {
                "preference": "user_preferences",
                "architecture": "project_architecture",
                "rule": "active_directives",
            }
            blk = block_map.get(category, "active_directives")
            res = self.update_core_memory(blk, clean_content, mode="append", scope=scope)
            return {
                "id": blk,
                "tier": "core",
                "category": category,
                **res,
                "action": "updated_core",
            }
        effective_scope = "global" if category == "preference" and self.global_home else scope
        state = self.load_state(effective_scope)
        memories: list[dict[str, Any]] = state.setdefault("semantic_memories", [])
        new_tokens = _tokenize_for_retrieval(clean_content)
        norm_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
        if isinstance(importance, float) and importance <= 1.0:
            imp = max(1, min(5, int(round(importance * 5))))
        else:
            imp = max(1, min(5, int(importance or 3)))

        # Deduplicate or merge with existing similar memory (Mem0 style)
        for item in memories:
            existing_text = str(item.get("content", ""))
            if existing_text == clean_content:
                item["updated_at"] = _utc_now()
                item["importance"] = max(int(item.get("importance", 3)), imp)
                item["access_count"] = int(item.get("access_count", 0)) + 1
                if norm_tags:
                    item["tags"] = list(dict.fromkeys([*(item.get("tags") or []), *norm_tags]))
                self.save_state(state, effective_scope)
                return {**item, "action": "deduplicated"}

            if item.get("category") == category:
                existing_tokens = _tokenize_for_retrieval(existing_text)
                sim = _compute_similarity(new_tokens, existing_tokens)
                shared_ident = set(
                    t
                    for t in new_tokens
                    if len(t) >= 3 and not any("\u4e00" <= c <= "\u9fff" for c in t)
                ) & set(
                    t
                    for t in existing_tokens
                    if len(t) >= 3 and not any("\u4e00" <= c <= "\u9fff" for c in t)
                )
                if sim >= 0.50 or (shared_ident and sim >= 0.28):
                    item["content"] = clean_content
                    item["updated_at"] = _utc_now()
                    item["importance"] = max(int(item.get("importance", 3)), imp)
                    if norm_tags:
                        item["tags"] = list(dict.fromkeys([*(item.get("tags") or []), *norm_tags]))
                    self.save_state(state, effective_scope)
                    return {**item, "action": "merged"}

        record = {
            "id": f"mem_{uuid.uuid4().hex[:10]}",
            "content": clean_content[:2000],
            "category": category or "fact",
            "tags": norm_tags,
            "importance": imp,
            "scope": effective_scope,
            "source": source,
            "access_count": 1,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
        }
        memories.append(record)
        # Keep bounded to top 300 memories sorted by importance & recency
        if len(memories) > 300:
            memories.sort(
                key=lambda m: (int(m.get("importance", 3)), str(m.get("updated_at", ""))),
                reverse=True,
            )
            state["semantic_memories"] = memories[:300]
        self.save_state(state, effective_scope)
        # Mirror project preferences into project file too if stored globally
        if effective_scope == "global" and self.workspace_root:
            proj_state = self.load_state("project")
            proj_mems = proj_state.setdefault("semantic_memories", [])
            if not any(m.get("content") == clean_content for m in proj_mems):
                proj_mems.append(dict(record))
                self.save_state(proj_state, "project")
        return {**record, "action": "created"}

    def update_memory(
        self,
        memory_id: str,
        content: str,
        *,
        importance: int | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        clean = (content or "").strip()
        if not clean:
            raise ValueError("更新内容不能为空")
        for scope in ("project", "global"):
            state = self.load_state(scope)
            for item in state.get("semantic_memories", []):
                if item.get("id") == memory_id:
                    item["content"] = clean[:2000]
                    if importance is not None:
                        item["importance"] = max(1, min(5, int(importance)))
                    if tags is not None:
                        item["tags"] = [str(t).strip() for t in tags if str(t).strip()]
                    item["updated_at"] = _utc_now()
                    self.save_state(state, scope)
                    return {**item, "updated": True}
        # If memory_id matches a core memory block name, update core memory
        if memory_id in {"user_preferences", "project_architecture", "active_directives"}:
            res = self.update_core_memory(memory_id, clean, mode="replace")
            return {"id": memory_id, "content": res["content"], "updated": True}
        raise KeyError(f"未找到记忆项：{memory_id}")

    def delete_memory(self, memory_id_or_query: str) -> dict[str, Any]:
        target = (memory_id_or_query or "").strip()
        if not target:
            raise ValueError("需要提供要删除的 memory_id 或匹配关键词")
        deleted_ids: list[str] = []
        for scope in ("project", "global"):
            state = self.load_state(scope)
            before = state.get("semantic_memories", [])
            kept = []
            for item in before:
                if (
                    item.get("id") == target
                    or target.lower() in str(item.get("content", "")).lower()
                ):
                    deleted_ids.append(str(item.get("id")))
                else:
                    kept.append(item)
            if len(kept) != len(before):
                state["semantic_memories"] = kept
                self.save_state(state, scope)
        return {
            "deleted_count": len(set(deleted_ids)),
            "deleted_ids": list(dict.fromkeys(deleted_ids)),
        }

    # =========================================================================
    # Tier 3: Episodic Memory (Cross-Turn & Cross-Session Task History)
    # =========================================================================
    def record_episode(
        self,
        *,
        conversation_id: str,
        user_request: str,
        outcome_summary: str,
        changed_files: list[str] | None = None,
        tools_used: list[str] | None = None,
        agent_mode: str = "multi_agent",
    ) -> dict[str, Any]:
        state = self.load_state("project")
        episodes: list[dict[str, Any]] = state.setdefault("episodic_memories", [])
        episode = {
            "id": f"ep_{uuid.uuid4().hex[:10]}",
            "conversation_id": conversation_id,
            "user_request": (user_request or "").strip()[:600],
            "outcome_summary": (outcome_summary or "").strip()[:800],
            "changed_files": list(dict.fromkeys(changed_files or []))[:40],
            "tools_used": list(dict.fromkeys(tools_used or []))[:25],
            "agent_mode": agent_mode,
            "created_at": _utc_now(),
        }
        episodes.append(episode)
        if len(episodes) > 80:
            state["episodic_memories"] = episodes[-80:]
        self.save_state(state, "project")
        return episode

    # =========================================================================
    # Tier 4: Entity & File Knowledge Graph (Cognee / Graphmem style)
    # =========================================================================
    def update_knowledge_graph_from_workspace(
        self, workspace_snapshot: dict[str, str], changed_files: list[str] | None = None
    ) -> None:
        if not self.workspace_root:
            return
        state = self.load_state("project")
        kg = state.setdefault("knowledge_graph", {"entities": {}, "relations": []})
        entities: dict[str, Any] = kg.setdefault("entities", {})
        relations: list[dict[str, str]] = []

        # Prune deleted files from entities
        current_files = set(workspace_snapshot.keys())
        for existing_key in list(entities.keys()):
            if existing_key not in current_files and entities[existing_key].get("type") == "file":
                entities.pop(existing_key, None)

        for rel_path, content in list(workspace_snapshot.items())[:80]:
            ext = Path(rel_path).suffix.lower()
            line_count = content.count("\n") + 1 if content else 0
            symbols: list[str] = []
            if ext == ".py":
                symbols = re.findall(r"^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", content, re.M)[
                    :15
                ]
                for imp in re.findall(r"^(?:from|import)\s+([A-Za-z0-9_.]+)", content, re.M)[:12]:
                    relations.append({"source": rel_path, "target": imp, "relation": "imports"})
            elif ext in {".js", ".ts", ".tsx", ".jsx"}:
                symbols = re.findall(
                    r"(?:function\s+([A-Za-z_$][A-Za-z0-9_$]*)|class\s+([A-Za-z_$][A-Za-z0-9_$]*))",
                    content,
                )[:15]
                symbols = [s[0] or s[1] for s in symbols if s[0] or s[1]]
                for imp in re.findall(r"""from\s+['"]([^'"]+)['"]""", content)[:12]:
                    relations.append({"source": rel_path, "target": imp, "relation": "imports"})
            elif ext in {".html", ".htm"}:
                for href in re.findall(r"""<link[^>]+href=['"]([^'"]+)['"]""", content, re.I):
                    relations.append(
                        {"source": rel_path, "target": href, "relation": "styles_with"}
                    )
                for src in re.findall(r"""<script[^>]+src=['"]([^'"]+)['"]""", content, re.I):
                    relations.append(
                        {"source": rel_path, "target": src, "relation": "loads_script"}
                    )
            elif ext == ".md":
                symbols = [h.strip() for h in re.findall(r"^#{1,3}\s+(.+)$", content, re.M)[:10]]

            entities[rel_path] = {
                "type": "file",
                "ext": ext,
                "lines": line_count,
                "symbols": symbols,
                "recently_modified": bool(changed_files and rel_path in changed_files),
                "updated_at": _utc_now(),
            }

        kg["relations"] = relations[:160]
        self.save_state(state, "project")

    # =========================================================================
    # Hybrid Search & Pre-Turn Context Recall
    # =========================================================================
    def search_memories(
        self,
        query: str,
        *,
        category: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        proj_state = self.load_state("project")
        glob_state = self.load_state("global") if self.global_home else self._empty_state()

        seen_ids: set[str] = set()
        all_semantic: list[dict[str, Any]] = []
        for m in [
            *proj_state.get("semantic_memories", []),
            *glob_state.get("semantic_memories", []),
        ]:
            mid = str(m.get("id") or "")
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                all_semantic.append(m)

        q_clean = (query or "").strip()
        q_tokens = _tokenize_for_retrieval(q_clean)

        scored_semantic: list[tuple[float, dict[str, Any]]] = []
        for item in all_semantic:
            if category and item.get("category") != category:
                continue
            text = f"{item.get('content', '')} {' '.join(item.get('tags') or [])}"
            sim = _compute_similarity(q_tokens, _tokenize_for_retrieval(text)) if q_tokens else 0.5
            imp_boost = int(item.get("importance", 3)) * 0.08
            score = sim + imp_boost
            if (
                not q_tokens
                or sim > 0.05
                or item.get("category") in {"preference", "rule", "architecture"}
            ):
                scored_semantic.append((score, item))

        scored_semantic.sort(
            key=lambda pair: (pair[0], str(pair[1].get("updated_at", ""))), reverse=True
        )
        top_semantic = [
            {**item, "score": round(score, 3)}
            for score, item in scored_semantic[: max(1, min(30, limit))]
        ]

        episodes = list(proj_state.get("episodic_memories", []))
        scored_episodes: list[tuple[float, dict[str, Any]]] = []
        for ep in episodes:
            ep_text = f"{ep.get('user_request', '')} {ep.get('outcome_summary', '')} {' '.join(ep.get('changed_files') or [])}"
            sim = (
                _compute_similarity(q_tokens, _tokenize_for_retrieval(ep_text)) if q_tokens else 0.4
            )
            scored_episodes.append((sim, ep))
        scored_episodes.sort(
            key=lambda pair: (pair[0], str(pair[1].get("created_at", ""))), reverse=True
        )
        top_episodes = [ep for _, ep in scored_episodes[:4]]

        return {
            "query": q_clean,
            "core_memory": self.get_core_memory(),
            "semantic_memories": top_semantic,
            "recent_episodes": episodes[-3:],
            "relevant_episodes": top_episodes,
            "knowledge_graph_summary": {
                "entity_count": len(proj_state.get("knowledge_graph", {}).get("entities", {})),
                "relation_count": len(proj_state.get("knowledge_graph", {}).get("relations", [])),
            },
        }

    # =========================================================================
    # Automatic Fact Extraction & Post-Turn Consolidation
    # =========================================================================
    def ingest_turn_interaction(
        self,
        *,
        conversation_id: str,
        user_content: str,
        assistant_content: str,
        agent_id: str | None = None,
        changed_files: list[str] | None = None,
        tools_used: list[str] | None = None,
        tool_events: list[dict[str, Any]] | None = None,
        workspace_snapshot: dict[str, str] | None = None,
        agent_mode: str = "multi_agent",
        **kwargs: Any,
    ) -> None:
        raw_u = (user_content or "").strip()
        if not raw_u:
            return

        effective_tools = list(tools_used or [])
        if tool_events and not effective_tools:
            effective_tools = [
                str(ev.get("name") or ev.get("short_name") or "")
                for ev in tool_events
                if isinstance(ev, dict) and (ev.get("name") or ev.get("short_name"))
            ]

        # 1. Extract explicit user preferences, rules, or constraints
        pref_patterns = [
            r"(不要[^，。；;\n]{2,50})",
            r"(禁止[^，。；;\n]{2,50})",
            r"(严禁[^，。；;\n]{2,50})",
            r"(必须[^，。；;\n]{2,50})",
            r"(统一使用[^，。；;\n]{2,50})",
            r"(默认[^，。；;\n]{2,40})",
            r"(记住[^，。；;\n]{2,60})",
            r"(以后都[^，。；;\n]{2,60})",
        ]
        extracted_prefs: list[str] = []
        for pat in pref_patterns:
            for m in re.finditer(pat, raw_u):
                phrase = m.group(1).strip()
                if 4 <= len(phrase) <= 80 and phrase not in extracted_prefs:
                    extracted_prefs.append(phrase)

        for pref in extracted_prefs[:4]:
            try:
                self.store_memory(
                    pref,
                    category="preference",
                    tags=["user_rule", "auto_extracted"],
                    importance=4,
                    scope="project",
                    source="auto_extract",
                )
            except Exception:
                pass
        if extracted_prefs:
            self.update_core_memory(
                "user_preferences",
                "；".join(extracted_prefs[:3]),
                mode="append",
                scope="project",
            )

        # 2. Update project architecture summary & knowledge graph if workspace files changed
        if (
            kwargs.get("scan_workspace", True)
            and workspace_snapshot is None
            and self.workspace_root
            and self.workspace_root.is_dir()
        ):
            snap: dict[str, str] = {}
            try:
                for p in sorted(self.workspace_root.rglob("*")):
                    if not p.is_file():
                        continue
                    if ".git" in p.parts or ".masp" in p.parts or "node_modules" in p.parts:
                        continue
                    rel_p = str(p.relative_to(self.workspace_root)).replace("\\", "/")
                    if rel_p in {
                        "task.md",
                        "plan.md",
                        "approved_plan.md",
                        "glossary.md",
                        "style-guide.md",
                        "verification_report.md",
                        "delivery_report.md",
                        "SHARED_DEV_SPEC.md",
                    }:
                        continue
                    try:
                        if p.stat().st_size <= 250_000:
                            snap[rel_p] = p.read_text(encoding="utf-8", errors="replace")[:12000]
                    except OSError:
                        pass
                    if len(snap) >= 60:
                        break
                workspace_snapshot = snap
            except OSError:
                pass

        if workspace_snapshot is not None:
            self.update_knowledge_graph_from_workspace(workspace_snapshot, changed_files)
            file_list = sorted(workspace_snapshot.keys())
            if file_list:
                arch_summary = f"工作区当前文件 ({len(file_list)} 个): {', '.join(file_list[:25])}"
                self.update_core_memory(
                    "project_architecture",
                    arch_summary,
                    mode="replace",
                    scope="project",
                )

        # 3. Record Episodic Memory for this turn
        summary_text = (assistant_content or "").strip()
        if not summary_text and changed_files:
            summary_text = f"已完成文件变更：{', '.join(changed_files)}"
        if raw_u and (summary_text or changed_files or effective_tools):
            self.record_episode(
                conversation_id=conversation_id,
                user_request=raw_u,
                outcome_summary=summary_text[:500],
                changed_files=changed_files or [],
                tools_used=effective_tools,
                agent_mode=agent_id or agent_mode,
            )

    def get_overview(self) -> dict[str, Any]:
        """Return a structured overview of all 4 Memory OS tiers."""
        proj_state = self.load_state("project")
        glob_state = self.load_state("global") if self.global_home else self._empty_state()
        kg = proj_state.get("knowledge_graph") or {"entities": {}, "relations": []}
        return {
            "core_memory": self.get_core_memory(),
            "semantic_count": len(proj_state.get("semantic_memories") or [])
            + len(glob_state.get("semantic_memories") or []),
            "semantic_memories": (proj_state.get("semantic_memories") or [])[-20:],
            "episodic_count": len(proj_state.get("episodic_memories") or []),
            "recent_episodes": (proj_state.get("episodic_memories") or [])[-10:],
            "knowledge_graph": {
                "entity_count": len(kg.get("entities") or {}),
                "relation_count": len(kg.get("relations") or []),
                "entities": kg.get("entities") or {},
                "relations": (kg.get("relations") or [])[:40],
            },
            "updated_at": proj_state.get("updated_at"),
        }

    def build_memory_context_prompt(
        self,
        query: str,
        *,
        workspace_snapshot: dict[str, str] | None = None,
        max_chars: int = 2400,
    ) -> str:
        """Build a compact, high-signal Memory OS context block for LLM system prompts."""
        recall = self.search_memories(query, limit=6)
        core = recall.get("core_memory") or {}
        semantic = recall.get("semantic_memories") or []
        recent_eps = recall.get("recent_episodes") or []
        proj_state = self.load_state("project")
        kg_entities = proj_state.get("knowledge_graph", {}).get("entities", {})
        kg_relations = proj_state.get("knowledge_graph", {}).get("relations", [])

        sections: list[str] = ["【Memory OS 长期记忆与项目全局感知】"]

        if core.get("user_preferences"):
            sections.append(f"- 用户偏好与长期规范：{core['user_preferences'][:400]}")
        if core.get("active_directives"):
            sections.append(f"- 核心指令约束：{core['active_directives'][:400]}")

        if workspace_snapshot is not None:
            files = sorted(workspace_snapshot.keys())
            if files:
                file_descs = []
                for fp in files[:24]:
                    ent = kg_entities.get(fp) or {}
                    syms = ent.get("symbols") or []
                    sym_str = f" (符号: {', '.join(syms[:4])})" if syms else ""
                    file_descs.append(f"`{fp}`{sym_str}")
                sections.append(f"- 当前工作区文件树 ({len(files)} 项)：{', '.join(file_descs)}")
            else:
                sections.append("- 当前工作区状态：空工作区（尚无业务源码文件）")
        elif core.get("project_architecture"):
            sections.append(f"- 项目架构概览：{core['project_architecture'][:400]}")

        if kg_relations:
            rel_strs = [
                f"`{r['source']}` -> `{r['target']}` ({r['relation']})" for r in kg_relations[:8]
            ]
            sections.append(f"- 跨文件依赖图谱：{'; '.join(rel_strs)}")

        if semantic:
            mem_lines = [
                f"  * [{m.get('category', 'fact')}] {m.get('content', '')}" for m in semantic[:6]
            ]
            sections.append("- 关联语义记忆 (Semantic Memory)：\n" + "\n".join(mem_lines))

        if recent_eps:
            ep_lines = []
            for ep in recent_eps[-3:]:
                files_tag = (
                    f" [涉及文件: {', '.join(ep['changed_files'][:6])}]"
                    if ep.get("changed_files")
                    else ""
                )
                ep_lines.append(
                    f"  * 历史任务「{ep.get('user_request', '')[:60]}」-> {ep.get('outcome_summary', '')[:100]}{files_tag}"
                )
            sections.append("- 近期执行轨迹记忆 (Episodic Memory)：\n" + "\n".join(ep_lines))

        block = "\n".join(sections)
        return block[:max_chars]
