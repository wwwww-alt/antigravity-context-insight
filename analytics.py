from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

BRAIN_DIR = Path.home() / ".gemini" / "antigravity" / "brain"

SUBAGENT_CREATED_RE = re.compile(
    r"Created the following subagent:\s*(\{[\s\S]*?\})", re.MULTILINE
)
SYS_MSG_HEADER_RE = re.compile(
    r"\[Message\]\s+timestamp=(\S+)\s+sender=(\S+)\s+priority=(\S+)\s+content=([\s\S]*?)(?:\n</SYSTEM_MESSAGE>|$)"
)
USER_REQ_RE = re.compile(r"<USER_REQUEST>\s*([\s\S]*?)\s*</USER_REQUEST>")
CREATED_AT_RE = re.compile(r"Created At:\s*([0-9T:\-\+]+)")
COMPLETED_AT_RE = re.compile(r"Completed At:\s*([0-9T:\-\+]+)")
EXIT_CODE_RE = re.compile(r"Command exited with code\s+(-?\d+)")
SKILL_PATH_RE = re.compile(r"[/\\]([^/\\]+)[/\\]SKILL\.md$", re.IGNORECASE)

MODEL_WINDOWS: dict[str, int] = {
    "gemini-4": 1_000_000,
    "gemini-3": 1_000_000,
    "gemini-2.5": 1_000_000,
    "gemini-2.0": 1_000_000,
    "claude": 200_000,
    "gpt-5": 400_000,
    "gpt-4": 128_000,
    "o3": 200_000,
}

# In-memory cache keyed by (path_str, mtime_ns, size)
_DETAIL_CACHE: dict[str, tuple[int, int, dict[str, Any]]] = {}
_LS_CACHE: dict[str, tuple[float, Any]] = {}


def _ls_post(method: str, body: dict[str, Any] | None = None, ttl: float = 15.0) -> dict[str, Any] | None:
    now = time.time()
    cached = _LS_CACHE.get(method)
    if cached and (now - cached[0]) < ttl:
        return cached[1]
    addr = os.environ.get("ANTIGRAVITY_LS_ADDRESS", "").strip()
    csrf = os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "").strip()
    if not addr or not csrf:
        return None
    url = f"http://{addr}/exa.language_server_pb.LanguageServerService/{method}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body or {}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-codeium-csrf-token": csrf,
        },
        method="POST",
    )
    try:
        # Loopback: bypass any system proxy
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        _LS_CACHE[method] = (now, data)
        return data
    except Exception:
        return None


def _extract_project_name(workspaces: list[dict[str, Any]] | None) -> tuple[str, str]:
    """Return (display_name, norm_key) merging case & collapsing /tmp."""
    if not workspaces:
        return ("未绑定项目", "__unbound__")
    for ws in workspaces:
        uri = str(ws.get("workspaceFolderAbsoluteUri") or ws.get("repository") or "").strip()
        if not uri:
            continue
        p = unquote(uri)
        if p.startswith("file:///"):
            p = p[8:]
        elif p.startswith("file://"):
            p = p[7:]
        p = p.rstrip("/\\")
        if not p:
            continue
        low = p.lower()
        if "/tmp" in low or "\\temp\\" in low or low.endswith("/tmp") or low.endswith("\\tmp"):
            return ("/tmp", "/tmp")
        name = Path(p.replace("\\", "/")).name or p
        return (name, name.lower())
    return ("未绑定项目", "__unbound__")


def _fetch_ls_trajectories() -> dict[str, dict[str, Any]]:
    data = _ls_post("GetAllCascadeTrajectories", {}, ttl=15.0)
    if not data or not isinstance(data.get("trajectorySummaries"), dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for cid, meta in data["trajectorySummaries"].items():
        if not isinstance(meta, dict):
            continue
        proj_name, proj_key = _extract_project_name(meta.get("workspaces"))
        out[cid] = {
            "summary": str(meta.get("summary") or "").strip(),
            "project": proj_name,
            "projectKey": proj_key,
            "status": str(meta.get("status") or ""),
        }
    return out


def _fetch_live_gemini_quota() -> dict[str, Any]:
    data = _ls_post("GetUserStatus", {}, ttl=20.0)
    result: dict[str, Any] = {
        "available": False,
        "remainingPct": None,
        "consumedPct": None,
        "resetTime": "",
        "windowStartIso": "",
        "windowEndIso": "",
    }
    if not data:
        return result
    configs = (
        data.get("userStatus", {})
        .get("cascadeModelConfigData", {})
        .get("clientModelConfigs", [])
    )
    if not isinstance(configs, list):
        return result
    for cfg in configs:
        label = str(cfg.get("label") or "")
        q = cfg.get("quotaInfo") or {}
        if "gemini" in label.lower() and isinstance(q.get("remainingFraction"), (int, float)):
            rem = max(0.0, min(1.0, float(q["remainingFraction"])))
            reset_ts = str(q.get("resetTime") or "")
            win_start = ""
            dt_reset = _parse_iso(reset_ts)
            if dt_reset:
                win_start = (dt_reset - timedelta(hours=5)).isoformat()
            result.update(
                {
                    "available": True,
                    "remainingPct": round(rem * 100.0, 1),
                    "consumedPct": round((1.0 - rem) * 100.0, 1),
                    "resetTime": reset_ts,
                    "windowStartIso": win_start,
                    "windowEndIso": reset_ts,
                }
            )
            break
    return result


def format_model_name(model: str) -> str:
    raw = (model or "").strip()
    if not raw or raw == "unknown":
        return "Unknown Model"
    m = raw.lower()
    # Normalize known Antigravity / Gemini / Claude / GPT model strings
    tier_map = {
        "xhigh": "XHigh",
        "high": "High",
        "medium": "Medium",
        "low": "Low",
    }
    parts = m.split("-")
    tier = ""
    if parts and parts[-1] in tier_map:
        tier = tier_map[parts[-1]]
        parts = parts[:-1]
    parts = [p for p in parts if p != "tiered"]

    if parts and parts[0] == "gemini":
        body = " ".join(p.capitalize() if not p[0].isdigit() else p for p in parts)
        return f"{body} ({tier})" if tier else body
    if parts and parts[0] == "claude":
        body = " ".join(p.capitalize() if not p[0].isdigit() else p for p in parts)
        return f"{body} ({tier})" if tier else body
    if parts and parts[0] == "gpt":
        body = "GPT-" + "-".join(parts[1:]).upper()
        return f"{body} ({tier})" if tier else body
    return raw


def _is_gemini_model(model: str) -> bool:
    m = (model or "").lower()
    return ("gemini" in m) or ("neon" in m) or ("hydrogen" in m) or ("carbon" in m) or ("argon" in m)


def _classify_scene(
    *,
    model_steps: int,
    tool_calls: int,
    subagent_count: int,
    files_written: int,
    commands_run: int,
    peak_context: int,
) -> str:
    if subagent_count >= 2 and tool_calls >= 6:
        return "多 Agent 协作"
    if tool_calls >= max(3, int(model_steps * 0.55)) or commands_run >= 3:
        return "工具执行轮次"
    if files_written >= 2:
        return "代码编写与编辑"
    if peak_context >= 100_000:
        return "长上下文分析"
    return "对话与问答"


def _weighted_tokens(input_billed: int, cache_read: int, output_tokens: int) -> int:
    # Standard billing/quota equivalence: uncached input = 1x, cache read = 0.1x, output = 4x
    return int(round(max(0, input_billed) + max(0, cache_read) * 0.1 + max(0, output_tokens) * 4.0))


def _model_window(model: str) -> int:
    m = (model or "").lower()
    for prefix, win in MODEL_WINDOWS.items():
        if prefix in m:
            return win
    return 1_000_000


def _est_tokens(text: Any) -> int:
    if not text:
        return 0
    s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    if not s:
        return 0
    non_ascii = sum(1 for ch in s if ord(ch) > 127)
    ascii_len = len(s) - non_ascii
    return max(1, int(non_ascii * 0.78 + ascii_len / 3.8))


def _unquote_arg(val: Any) -> str:
    if val is None:
        return ""
    if not isinstance(val, str):
        return str(val)
    s = val.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        try:
            decoded = json.loads(s)
            if isinstance(decoded, str):
                return decoded
        except Exception:
            return s[1:-1]
    return s


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        t = ts.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        return datetime.fromisoformat(t)
    except Exception:
        return None


def _local_day(ts: str) -> str:
    dt = _parse_iso(ts)
    if not dt:
        return ""
    return dt.astimezone().strftime("%Y-%m-%d")


def _extract_user_text(content: str) -> str:
    m = USER_REQ_RE.search(content or "")
    text = m.group(1).strip() if m else (content or "").strip()
    return text


def _path_to_file_uri(path_str: str) -> str:
    p = path_str.replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return "file://" + quote(p, safe="/:")


def _extract_program(cmdline: str) -> str:
    s = (cmdline or "").strip()
    if not s:
        return "shell"
    parts = re.split(r"\s*;\s*|\s*&&\s*", s)
    for part in parts:
        p = part.strip()
        if not p or p.startswith("$") or p.lower().startswith("set-location") or p.lower().startswith("cd "):
            continue
        if p.startswith("&"):
            p = p[1:].strip()
        m = re.match(r'^["\']?([^"\'\s]+)["\']?', p)
        if not m:
            continue
        tok = m.group(1)
        base = Path(tok.replace("\\", "/")).name.lower()
        for ext in (".exe", ".cmd", ".bat", ".ps1", ".cjs", ".mjs"):
            if base.endswith(ext):
                base = base[: -len(ext)]
        if base:
            return base
    return "powershell"


def _discover_transcript_files() -> list[tuple[str, Path]]:
    if not BRAIN_DIR.is_dir():
        return []
    out: list[tuple[str, Path]] = []
    for entry in BRAIN_DIR.iterdir():
        if not entry.is_dir():
            continue
        t = entry / ".system_generated" / "logs" / "transcript.jsonl"
        if t.is_file():
            out.append((entry.name, t))
    out.sort(key=lambda item: item[1].stat().st_mtime, reverse=True)
    return out


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue
    return rows


def _parse_session_full(conv_id: str, path: Path) -> dict[str, Any]:
    st = path.stat()
    cache_key = str(path)
    cached = _DETAIL_CACHE.get(cache_key)
    if cached and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
        return cached[2]

    rows = _read_jsonl(path)
    title = ""
    models_seen: list[str] = []
    model_step_counts: Counter[str] = Counter()
    last_model = ""
    first_ts = ""
    last_ts = ""

    cum = {
        "system": 0,
        "user": 0,
        "skills": 0,
        "assistant": 0,
        "tools": 0,
        "events": 0,
    }

    total_input_billed = 0
    total_cache_read = 0
    total_output_tokens = 0
    gemini_input_billed = 0
    gemini_cache_read = 0
    gemini_output_tokens = 0
    peak_context = 0
    current_context = 0
    user_turns = 0
    model_steps = 0
    tool_calls_total = 0
    error_count = 0

    tool_counter: Counter[str] = Counter()
    skill_counter: Counter[str] = Counter()
    program_counter: Counter[str] = Counter()
    daily_tokens: defaultdict[str, int] = defaultdict(int)
    daily_calls: defaultdict[str, int] = defaultdict(int)

    step_series: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    browser_items: list[dict[str, Any]] = []
    files_map: dict[str, dict[str, Any]] = {}
    commands: list[dict[str, Any]] = []

    spawned_children: list[dict[str, Any]] = []
    child_role_by_id: dict[str, dict[str, Any]] = {}
    fleet_events: list[dict[str, Any]] = []
    gemini_step_records: list[tuple[str, int]] = []  # (ts, weighted_tokens)

    pending_tools: list[dict[str, Any]] = []
    last_user_preview = ""
    new_in_this_step: list[str] = []
    prev_prompt = 0
    baseline_system: int | None = None
    turn_index = 0

    for row in rows:
        idx = int(row.get("step_index", len(browser_items)))
        source = str(row.get("source") or "")
        rtype = str(row.get("type") or "")
        status = str(row.get("status") or "")
        ts = str(row.get("created_at") or "")
        if ts:
            if not first_ts:
                first_ts = ts
            last_ts = ts

        if status == "ERROR" or rtype == "ERROR_MESSAGE" or row.get("error"):
            error_count += 1
            events.append(
                {
                    "step": idx,
                    "turn": turn_index,
                    "kind": "error",
                    "label": "错误",
                    "detail": str(row.get("error") or row.get("content") or "Step error")[:200],
                    "delta": 0,
                    "ts": ts,
                }
            )

        if source == "USER_EXPLICIT" and rtype == "USER_INPUT":
            user_turns += 1
            turn_index = user_turns
            raw_c = str(row.get("content") or "")
            u_text = _extract_user_text(raw_c)
            if not title and u_text:
                title = u_text.splitlines()[0][:72]
            last_user_preview = u_text.replace("\n", " ")[:140]
            media = row.get("media") or []
            tok = _est_tokens(raw_c) + len(media) * 320
            cum["user"] += tok
            new_in_this_step.append(f"用户消息 ({tok} tok)")
            browser_items.append(
                {
                    "id": f"s{idx}",
                    "step": idx,
                    "turn": turn_index,
                    "category": "user",
                    "kind": "user",
                    "title": u_text.splitlines()[0][:80] if u_text else "(空消息)",
                    "tokens": tok,
                    "ts": ts,
                    "preview": u_text[:280],
                    "content": u_text[:12000],
                    "mediaCount": len(media),
                }
            )
            continue

        if source == "SYSTEM" and rtype == "SYSTEM_MESSAGE":
            raw_c = str(row.get("content") or "")
            tok = _est_tokens(raw_c)
            cum["events"] += tok
            m = SYS_MSG_HEADER_RE.search(raw_c)
            sender = m.group(2) if m else "system"
            msg_body = m.group(4).strip() if m else raw_c.strip()
            is_subagent_msg = sender not in ("system", "") and "/" not in sender and len(sender) >= 16
            is_task_msg = "/" in sender and "task-" in sender

            label = (
                f"子 Agent 回报 ({sender[:8]})"
                if is_subagent_msg
                else ("后台任务完成" if is_task_msg else "系统消息")
            )
            new_in_this_step.append(f"{label} ({tok} tok)")
            browser_items.append(
                {
                    "id": f"s{idx}",
                    "step": idx,
                    "turn": turn_index,
                    "category": "events",
                    "kind": "subagent_reply" if is_subagent_msg else "system",
                    "title": label,
                    "sender": sender,
                    "tokens": tok,
                    "ts": ts,
                    "preview": msg_body.replace("\n", " ")[:220],
                    "content": msg_body[:12000],
                }
            )
            if is_subagent_msg:
                role_info = child_role_by_id.get(sender, {})
                fleet_events.append(
                    {
                        "id": f"fe-{idx}",
                        "step": idx,
                        "kind": "reply",
                        "from": sender,
                        "fromLabel": role_info.get("role") or sender[:8],
                        "to": conv_id,
                        "toLabel": "主 Agent",
                        "ts": m.group(1) if m else ts,
                        "summary": msg_body.replace("\n", " ")[:180],
                        "content": msg_body[:8000],
                    }
                )
            elif "BROWSER_HOST_FACTS" in msg_body:
                sub_m = re.search(r"subagent=([0-9a-f\-]{16,})", msg_body)
                sub_id = sub_m.group(1) if sub_m else "browser"
                fleet_events.append(
                    {
                        "id": f"fe-{idx}",
                        "step": idx,
                        "kind": "host_facts",
                        "from": "host",
                        "fromLabel": "Host 校验事实",
                        "to": sub_id,
                        "toLabel": child_role_by_id.get(sub_id, {}).get("role") or sub_id[:8],
                        "ts": m.group(1) if m else ts,
                        "summary": msg_body.replace("\n", " ")[:180],
                        "content": msg_body[:4000],
                    }
                )
            continue

        if source == "MODEL" and rtype == "PLANNER_RESPONSE":
            model_steps += 1
            model = str(row.get("model") or last_model or "unknown")
            if model and model not in models_seen:
                models_seen.append(model)
            if model:
                model_step_counts[model] += 1
            is_model_switch = bool(last_model and model and model != last_model)
            if is_model_switch:
                events.append(
                    {
                        "step": idx,
                        "turn": turn_index,
                        "kind": "switch",
                        "label": "切换模型",
                        "detail": f"{format_model_name(last_model)} → {format_model_name(model)}",
                        "delta": 0,
                        "ts": ts,
                    }
                )
            last_model = model

            in_tok = int(row.get("input_tokens") or 0)
            cache_tok = int(row.get("cache_read_tokens") or 0)
            out_tok = int(row.get("output_tokens") or 0)
            prompt_tok = in_tok + cache_tok

            total_input_billed += in_tok
            total_cache_read += cache_tok
            total_output_tokens += out_tok
            if _is_gemini_model(model):
                gemini_input_billed += in_tok
                gemini_cache_read += cache_tok
                gemini_output_tokens += out_tok
                w_step = _weighted_tokens(in_tok, cache_tok, out_tok)
                if ts and w_step > 0:
                    gemini_step_records.append((ts, w_step))

            if prompt_tok > peak_context:
                peak_context = prompt_tok
            if prompt_tok > 0:
                current_context = prompt_tok

            day_key = _local_day(ts)
            if day_key:
                daily_tokens[day_key] += in_tok + cache_tok + out_tok
                daily_calls[day_key] += 1

            if baseline_system is None and prompt_tok > 0:
                baseline_system = max(1200, prompt_tok - cum["user"] - cum["events"])
                cum["system"] = baseline_system

            delta = (prompt_tok - prev_prompt) if (prev_prompt > 0 and prompt_tok > 0) else 0
            is_compaction = prev_prompt > 8000 and prompt_tok > 0 and delta < -max(4000, int(prev_prompt * 0.15))
            if is_compaction:
                events.append(
                    {
                        "step": idx,
                        "turn": turn_index,
                        "kind": "compact",
                        "label": "上下文压缩/回收",
                        "detail": f"窗口从 {prev_prompt:,} 降至 {prompt_tok:,}（回收 {abs(delta):,} tokens）",
                        "delta": delta,
                        "ts": ts,
                    }
                )

            est_sum = sum(cum.values()) or 1
            target_total = prompt_tok if prompt_tok > 0 else est_sum
            scaled = {k: int(round(cum[k] * target_total / est_sum)) for k in cum}
            diff = target_total - sum(scaled.values())
            if diff != 0:
                biggest = max(scaled, key=lambda k: scaled[k])
                scaled[biggest] = max(0, scaled[biggest] + diff)

            thinking = str(row.get("thinking") or "")
            answer = str(row.get("content") or "")
            tcs = row.get("tool_calls") or []
            if not isinstance(tcs, list):
                tcs = []

            tool_names_this_step: list[str] = []
            pending_tools = []
            for tc in tcs:
                if not isinstance(tc, dict):
                    continue
                tname = str(tc.get("name") or "unknown")
                targs = tc.get("args") if isinstance(tc.get("args"), dict) else {}
                tool_counter[tname] += 1
                tool_calls_total += 1
                tool_names_this_step.append(tname)
                pending_tools.append({"name": tname, "args": targs, "step": idx, "ts": ts})

                if tname in ("read_file", "write_file", "edit_file"):
                    fpath = _unquote_arg(targs.get("Path") or targs.get("path"))
                    if fpath:
                        act = "read" if tname == "read_file" else "write"
                        fentry = files_map.setdefault(
                            fpath,
                            {
                                "path": fpath,
                                "name": Path(fpath.replace("\\", "/")).name or fpath,
                                "fileUri": _path_to_file_uri(fpath),
                                "reads": 0,
                                "writes": 0,
                                "searches": 0,
                                "ops": [],
                            },
                        )
                        if act == "read":
                            fentry["reads"] += 1
                        else:
                            fentry["writes"] += 1
                        fentry["ops"].append({"step": idx, "tool": tname, "action": act, "ts": ts})

                        sm = SKILL_PATH_RE.search(fpath)
                        if tname == "read_file" and sm:
                            sname = sm.group(1)
                            skill_counter[sname] += 1
                            events.append(
                                {
                                    "step": idx,
                                    "turn": turn_index,
                                    "kind": "skill",
                                    "label": f"加载 Skill: {sname}",
                                    "detail": fpath,
                                    "delta": 0,
                                    "ts": ts,
                                }
                            )
                elif tname in ("grep_search", "find_by_name", "list_dir"):
                    spath = _unquote_arg(
                        targs.get("SearchPath") or targs.get("SearchDirectory") or targs.get("DirectoryPath")
                    )
                    if spath:
                        fentry = files_map.setdefault(
                            spath,
                            {
                                "path": spath,
                                "name": Path(spath.replace("\\", "/")).name or spath,
                                "fileUri": _path_to_file_uri(spath),
                                "reads": 0,
                                "writes": 0,
                                "searches": 0,
                                "ops": [],
                            },
                        )
                        fentry["searches"] += 1
                        fentry["ops"].append({"step": idx, "tool": tname, "action": "search", "ts": ts})
                elif tname == "send_message":
                    rec = _unquote_arg(targs.get("Recipient"))
                    msg = _unquote_arg(targs.get("Message"))
                    fleet_events.append(
                        {
                            "id": f"fe-{idx}-send",
                            "step": idx,
                            "kind": "send_message",
                            "from": conv_id,
                            "fromLabel": "主 Agent",
                            "to": rec,
                            "toLabel": child_role_by_id.get(rec, {}).get("role") or rec[:8],
                            "ts": ts,
                            "summary": msg.replace("\n", " ")[:180],
                            "content": msg[:8000],
                        }
                    )

            resp_parts = []
            if answer.strip():
                resp_parts.append(answer.strip().replace("\n", " ")[:120])
            if tool_names_this_step:
                resp_parts.append("调用工具: " + ", ".join(tool_names_this_step[:6]))
            if not resp_parts and thinking:
                resp_parts.append("思考: " + thinking.replace("\n", " ")[:100])

            step_series.append(
                {
                    "step": idx,
                    "seq": model_steps,
                    "turn": turn_index,
                    "ts": ts,
                    "model": format_model_name(model),
                    "rawModel": model,
                    "promptTokens": prompt_tok,
                    "inputTokens": in_tok,
                    "cacheReadTokens": cache_tok,
                    "outputTokens": out_tok,
                    "cacheRate": round((cache_tok / prompt_tok) * 100, 1) if prompt_tok > 0 else 0.0,
                    "deltaTokens": delta,
                    "isModelSwitch": is_model_switch,
                    "isCompaction": is_compaction,
                    "composition": scaled,
                    "brief": {
                        "user": last_user_preview,
                        "inSummary": " · ".join(new_in_this_step[:4]) if new_in_this_step else "延续上一步上下文",
                        "response": " | ".join(resp_parts) if resp_parts else "(空回复)",
                    },
                }
            )
            new_in_this_step = []
            if prompt_tok > 0:
                prev_prompt = prompt_tok

            think_tok = _est_tokens(thinking)
            ans_tok = _est_tokens(answer)
            tc_tok = _est_tokens(tcs)
            cum["assistant"] += think_tok + ans_tok
            cum["tools"] += tc_tok

            kinds = []
            if thinking:
                kinds.append("thinking")
            if tcs:
                kinds.append("tools")
            if answer.strip():
                kinds.append("answer")

            browser_items.append(
                {
                    "id": f"s{idx}",
                    "step": idx,
                    "turn": turn_index,
                    "category": "assistant",
                    "kind": kinds[0] if kinds else "answer",
                    "kinds": kinds,
                    "model": format_model_name(model),
                    "title": (
                        f"回复 + {len(tcs)} 个工具"
                        if answer.strip() and tcs
                        else (f"调用工具: {', '.join(tool_names_this_step[:3])}" if tcs else "助手回复")
                    ),
                    "tokens": out_tok or (think_tok + ans_tok + tc_tok),
                    "promptTokens": prompt_tok,
                    "cacheReadTokens": cache_tok,
                    "ts": ts,
                    "preview": (answer.strip() or thinking.strip() or ", ".join(tool_names_this_step))[:260],
                    "thinking": thinking[:10000],
                    "answer": answer[:12000],
                    "toolCalls": [
                        {
                            "name": str(tc.get("name") or ""),
                            "argsPreview": json.dumps(tc.get("args") or {}, ensure_ascii=False)[:600],
                        }
                        for tc in tcs
                        if isinstance(tc, dict)
                    ],
                }
            )
            continue

        if source == "MODEL" and rtype == "GENERIC":
            raw_c = str(row.get("content") or "")
            media = row.get("media") or []
            tok = _est_tokens(raw_c) + len(media) * 320
            matched_tc = pending_tools.pop(0) if pending_tools else None
            tname = matched_tc["name"] if matched_tc else "tool_result"
            targs = matched_tc["args"] if matched_tc else {}

            is_skill_read = False
            if tname == "read_file":
                fpath = _unquote_arg(targs.get("Path") or targs.get("path"))
                if SKILL_PATH_RE.search(fpath):
                    is_skill_read = True
                    cum["skills"] += tok
                else:
                    cum["tools"] += tok
            else:
                cum["tools"] += tok

            sm = SUBAGENT_CREATED_RE.search(raw_c)
            if sm:
                try:
                    sub_json = json.loads(sm.group(1))
                    sub_cid = str(sub_json.get("conversationId") or "")
                    if sub_cid:
                        role = _unquote_arg(targs.get("Role")) or "Subagent"
                        sub_type = _unquote_arg(targs.get("TypeName")) or "subagent"
                        sub_model = _unquote_arg(targs.get("Model")) or "inherit"
                        sub_prompt = _unquote_arg(targs.get("Prompt"))
                        info = {
                            "conversationId": sub_cid,
                            "role": role,
                            "type": sub_type,
                            "requestedModel": sub_model,
                            "prompt": sub_prompt[:1000],
                            "spawnStep": idx,
                            "spawnTs": ts,
                        }
                        spawned_children.append(info)
                        child_role_by_id[sub_cid] = info
                        events.append(
                            {
                                "step": idx,
                                "turn": turn_index,
                                "kind": "subagent",
                                "label": f"派生子 Agent: {role}",
                                "detail": f"{sub_type} ({sub_cid[:8]})",
                                "delta": 0,
                                "ts": ts,
                            }
                        )
                        fleet_events.append(
                            {
                                "id": f"fe-{idx}-spawn",
                                "step": idx,
                                "kind": "spawn",
                                "from": conv_id,
                                "fromLabel": "主 Agent",
                                "to": sub_cid,
                                "toLabel": role,
                                "ts": ts,
                                "summary": f"派生 {sub_type}: {sub_prompt.replace(chr(10), ' ')[:160]}",
                                "content": sub_prompt[:8000],
                            }
                        )
                except Exception:
                    pass

            if tname == "run_command":
                cmdline = _unquote_arg(targs.get("CommandLine"))
                summary = _unquote_arg(targs.get("toolSummary"))
                prog = _extract_program(cmdline)
                program_counter[prog] += 1
                em = EXIT_CODE_RE.search(raw_c)
                if em:
                    exit_code: int | None = int(em.group(1))
                    cmd_status = "ok" if exit_code == 0 else "error"
                elif "running as a background task" in raw_c:
                    exit_code = None
                    cmd_status = "bg"
                else:
                    exit_code = 0 if status == "DONE" else -1
                    cmd_status = "ok" if status == "DONE" else "error"

                dur_ms = 0
                c1 = CREATED_AT_RE.search(raw_c)
                c2 = COMPLETED_AT_RE.search(raw_c)
                if c1 and c2:
                    d1, d2 = _parse_iso(c1.group(1)), _parse_iso(c2.group(1))
                    if d1 and d2:
                        dur_ms = max(0, int((d2 - d1).total_seconds() * 1000))

                commands.append(
                    {
                        "step": idx,
                        "program": prog,
                        "summary": summary or prog,
                        "command": cmdline[:600],
                        "status": cmd_status,
                        "exitCode": exit_code,
                        "durationMs": dur_ms,
                        "ts": ts,
                        "outputPreview": raw_c[:1600],
                    }
                )

            new_in_this_step.append(f"{tname} 结果 ({tok} tok)")
            browser_items.append(
                {
                    "id": f"s{idx}",
                    "step": idx,
                    "turn": turn_index,
                    "category": "skills" if is_skill_read else "tools",
                    "kind": "skill" if is_skill_read else "tool_result",
                    "toolName": tname,
                    "status": status or "DONE",
                    "title": (
                        f"Skill: {SKILL_PATH_RE.search(_unquote_arg(targs.get('Path'))).group(1)}"
                        if is_skill_read
                        else f"{tname} 返回"
                    ),
                    "tokens": tok,
                    "ts": ts,
                    "preview": raw_c.replace("\n", " ")[:240],
                    "content": raw_c[:12000],
                    "argsPreview": json.dumps(targs, ensure_ascii=False)[:600] if targs else "",
                }
            )

    turns_map: dict[int, dict[str, Any]] = {}
    for s in step_series:
        tnum = s["turn"] or 1
        turns_map[tnum] = {
            "turn": tnum,
            "step": s["step"],
            "ts": s["ts"],
            "model": s["model"],
            "promptTokens": s["promptTokens"],
            "inputTokens": s["inputTokens"],
            "cacheReadTokens": s["cacheReadTokens"],
            "outputTokens": s["outputTokens"],
            "cacheRate": s["cacheRate"],
            "composition": s["composition"],
            "brief": s["brief"],
            "isCompaction": s["isCompaction"],
            "isModelSwitch": s["isModelSwitch"],
        }
    turn_series = []
    prev_t_tok = 0
    for tnum in sorted(turns_map):
        item = turns_map[tnum]
        item["deltaTokens"] = (item["promptTokens"] - prev_t_tok) if prev_t_tok > 0 else 0
        prev_t_tok = item["promptTokens"]
        turn_series.append(item)

    dur_s = 0
    d_start, d_end = _parse_iso(first_ts), _parse_iso(last_ts)
    if d_start and d_end:
        dur_s = max(0, int((d_end - d_start).total_seconds()))

    total_prompt_sum = total_input_billed + total_cache_read
    cache_hit_rate = round((total_cache_read / total_prompt_sum) * 100, 1) if total_prompt_sum > 0 else 0.0
    dominant_raw = model_step_counts.most_common(1)[0][0] if model_step_counts else (last_model or "unknown")
    dominant_display = format_model_name(dominant_raw)
    model_win = _model_window(dominant_raw)
    occupancy_pct = round((current_context / model_win) * 100, 2) if model_win > 0 else 0.0
    files_list = sorted(
        files_map.values(),
        key=lambda f: (f["reads"] + f["writes"] + f["searches"]),
        reverse=True,
    )
    files_written = sum(1 for f in files_list if f["writes"] > 0)
    scene = _classify_scene(
        model_steps=model_steps,
        tool_calls=tool_calls_total,
        subagent_count=len(spawned_children),
        files_written=files_written,
        commands_run=len(commands),
        peak_context=peak_context,
    )
    weighted_tok = _weighted_tokens(total_input_billed, total_cache_read, total_output_tokens)
    gemini_weighted_tok = _weighted_tokens(gemini_input_billed, gemini_cache_read, gemini_output_tokens)
    current_comp = step_series[-1]["composition"] if step_series else cum

    detail = {
        "conversationId": conv_id,
        "title": title or f"会话 {conv_id[:8]}",
        "transcriptPath": str(path),
        "transcriptUri": _path_to_file_uri(str(path)),
        "firstTs": first_ts,
        "lastTs": last_ts,
        "mtime": st.st_mtime,
        "durationSeconds": dur_s,
        "model": dominant_display,
        "rawModel": dominant_raw,
        "models": [format_model_name(m) for m in models_seen],
        "scene": scene,
        "modelWindow": model_win,
        "occupancyPct": occupancy_pct,
        "stats": {
            "userTurns": user_turns,
            "modelSteps": model_steps,
            "totalSteps": len(rows),
            "toolCalls": tool_calls_total,
            "errors": error_count,
            "currentContext": current_context,
            "peakContext": peak_context,
            "totalInputBilled": total_input_billed,
            "totalCacheRead": total_cache_read,
            "totalOutputTokens": total_output_tokens,
            "totalTokens": total_input_billed + total_cache_read + total_output_tokens,
            "weightedTokens": weighted_tok,
            "geminiWeightedTokens": gemini_weighted_tok,
            "cacheHitRate": cache_hit_rate,
            "subagentCount": len(spawned_children),
            "filesTouched": len(files_list),
            "commandsRun": len(commands),
        },
        "currentComposition": current_comp,
        "stepSeries": step_series[-300:],
        "turnSeries": turn_series[-120:],
        "events": events[-200:],
        "browserItems": browser_items[-400:],
        "files": files_list[:200],
        "commands": commands[-200:],
        "topTools": [{"name": k, "count": v} for k, v in tool_counter.most_common(25)],
        "topSkills": [{"name": k, "count": v} for k, v in skill_counter.most_common(25)],
        "topPrograms": [{"name": k, "count": v} for k, v in program_counter.most_common(20)],
        "dailyTokens": dict(daily_tokens),
        "dailyCalls": dict(daily_calls),
        "spawnedChildren": spawned_children,
        "fleetEvents": fleet_events[-200:],
        "_geminiStepRecords": gemini_step_records,
    }

    _DETAIL_CACHE[cache_key] = (st.st_mtime_ns, st.st_size, detail)
    return detail


def _build_parent_index(details: list[dict[str, Any]]) -> dict[str, tuple[str, dict[str, Any]]]:
    parent_of: dict[str, tuple[str, dict[str, Any]]] = {}
    for d in details:
        for ch in d.get("spawnedChildren", []):
            cid = ch.get("conversationId")
            if cid:
                parent_of[cid] = (d["conversationId"], ch)
    return parent_of


def _load_recent_details(limit: int = 60) -> list[dict[str, Any]]:
    files = _discover_transcript_files()[:limit]
    return [_parse_session_full(cid, p) for cid, p in files]


def _public_detail(d: dict[str, Any], ls_meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out = {k: v for k, v in d.items() if not k.startswith("_")}
    meta = ls_meta.get(d["conversationId"])
    if meta:
        if meta.get("summary"):
            out["title"] = meta["summary"]
        out["project"] = meta.get("project") or "未绑定项目"
        out["projectKey"] = meta.get("projectKey") or "__unbound__"
    else:
        out["project"] = "未绑定项目"
        out["projectKey"] = "__unbound__"
    return out


def list_sessions_compact(
    limit: int = 50,
    *,
    details: list[dict[str, Any]] | None = None,
    ls_meta: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if details is None:
        details = _load_recent_details(limit=limit)
    if ls_meta is None:
        ls_meta = _fetch_ls_trajectories()
    parent_of = _build_parent_index(details)
    out = []
    for d in details:
        cid = d["conversationId"]
        pinfo = parent_of.get(cid)
        meta = ls_meta.get(cid, {})
        title = meta.get("summary") or d["title"]
        out.append(
            {
                "conversationId": cid,
                "title": (pinfo[1].get("role") + " · " + title) if pinfo else title,
                "project": meta.get("project") or "未绑定项目",
                "isSubagent": pinfo is not None,
                "parentId": pinfo[0] if pinfo else None,
                "role": pinfo[1].get("role") if pinfo else None,
                "subagentType": pinfo[1].get("type") if pinfo else None,
                "model": d["model"],
                "scene": d["scene"],
                "lastTs": d["lastTs"],
                "mtime": d["mtime"],
                "stats": d["stats"],
                "occupancyPct": d["occupancyPct"],
                "currentComposition": d["currentComposition"],
            }
        )
    return out


def get_session_payload(conversation_id: str = "") -> dict[str, Any]:
    files = _discover_transcript_files()
    if not files:
        return {"ok": False, "error": "未找到任何 Antigravity 会话日志", "sessions": []}

    details = [_parse_session_full(cid, p) for cid, p in files[:50]]
    ls_meta = _fetch_ls_trajectories()
    parent_of = _build_parent_index(details)
    by_id = {d["conversationId"]: d for d in details}

    target: dict[str, Any] | None = None
    if conversation_id:
        if conversation_id in by_id:
            target = by_id[conversation_id]
        else:
            cand = BRAIN_DIR / conversation_id / ".system_generated" / "logs" / "transcript.jsonl"
            if cand.is_file():
                target = _parse_session_full(conversation_id, cand)
    if target is None:
        for d in details:
            if d["conversationId"] not in parent_of:
                target = d
                break
        if target is None:
            target = details[0]

    sessions = list_sessions_compact(limit=50, details=details, ls_meta=ls_meta)
    fleet = build_fleet_payload(target["conversationId"], preloaded=by_id, parent_of=parent_of, ls_meta=ls_meta)
    return {
        "ok": True,
        "session": _public_detail(target, ls_meta),
        "fleet": fleet,
        "sessions": sessions,
    }


def build_fleet_payload(
    conversation_id: str,
    *,
    preloaded: dict[str, dict[str, Any]] | None = None,
    parent_of: dict[str, tuple[str, dict[str, Any]]] | None = None,
    ls_meta: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if preloaded is None:
        details = _load_recent_details(limit=50)
        preloaded = {d["conversationId"]: d for d in details}
    if parent_of is None:
        parent_of = _build_parent_index(list(preloaded.values()))
    if ls_meta is None:
        ls_meta = _fetch_ls_trajectories()

    root_id = conversation_id
    visited_up = {root_id}
    while root_id in parent_of and parent_of[root_id][0] not in visited_up:
        root_id = parent_of[root_id][0]
        visited_up.add(root_id)

    def get_detail(cid: str) -> dict[str, Any] | None:
        if cid in preloaded:
            return preloaded[cid]
        cand = BRAIN_DIR / cid / ".system_generated" / "logs" / "transcript.jsonl"
        if cand.is_file():
            d = _parse_session_full(cid, cand)
            preloaded[cid] = d
            return d
        return None

    members: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []
    seen: set[str] = set()

    def walk(cid: str, depth: int, spawn_info: dict[str, Any] | None = None, parent_id: str | None = None):
        if cid in seen or depth > 4:
            return
        seen.add(cid)
        d = get_detail(cid)
        meta = ls_meta.get(cid, {})
        if d:
            members.append(
                {
                    "conversationId": cid,
                    "parentId": parent_id,
                    "depth": depth,
                    "isRoot": depth == 0,
                    "isCurrent": cid == conversation_id,
                    "role": (spawn_info or {}).get("role") or ("主 Agent" if depth == 0 else cid[:8]),
                    "subagentType": (spawn_info or {}).get("type") or ("coordinator" if depth == 0 else "subagent"),
                    "title": meta.get("summary") or d["title"],
                    "model": d["model"],
                    "occupancyPct": d["occupancyPct"],
                    "currentContext": d["stats"]["currentContext"],
                    "peakContext": d["stats"]["peakContext"],
                    "totalTokens": d["stats"]["totalTokens"],
                    "cacheHitRate": d["stats"]["cacheHitRate"],
                    "modelSteps": d["stats"]["modelSteps"],
                    "toolCalls": d["stats"]["toolCalls"],
                    "durationSeconds": d["durationSeconds"],
                    "currentComposition": d["currentComposition"],
                    "lastTs": d["lastTs"],
                    "promptPreview": ((spawn_info or {}).get("prompt") or "")[:360],
                }
            )
            for fe in d.get("fleetEvents", []):
                all_events.append({**fe, "ownerSession": cid})
            for ch in d.get("spawnedChildren", []):
                child_cid = ch.get("conversationId")
                if child_cid:
                    edges.append(
                        {
                            "from": cid,
                            "to": child_cid,
                            "role": ch.get("role") or child_cid[:8],
                            "type": ch.get("type") or "subagent",
                            "step": ch.get("spawnStep", 0),
                        }
                    )
                    walk(child_cid, depth + 1, spawn_info=ch, parent_id=cid)
        else:
            members.append(
                {
                    "conversationId": cid,
                    "parentId": parent_id,
                    "depth": depth,
                    "isRoot": depth == 0,
                    "isCurrent": cid == conversation_id,
                    "role": (spawn_info or {}).get("role") or cid[:8],
                    "subagentType": (spawn_info or {}).get("type") or "subagent",
                    "title": (spawn_info or {}).get("role") or f"子 Agent {cid[:8]}",
                    "model": format_model_name((spawn_info or {}).get("requestedModel") or "unknown"),
                    "occupancyPct": 0.0,
                    "currentContext": 0,
                    "peakContext": 0,
                    "totalTokens": 0,
                    "cacheHitRate": 0.0,
                    "modelSteps": 0,
                    "toolCalls": 0,
                    "durationSeconds": 0,
                    "currentComposition": {"system": 0, "user": 0, "skills": 0, "assistant": 0, "tools": 0, "events": 0},
                    "lastTs": (spawn_info or {}).get("spawnTs") or "",
                    "promptPreview": ((spawn_info or {}).get("prompt") or "")[:360],
                }
            )

    walk(root_id, 0)
    all_events.sort(key=lambda e: str(e.get("ts") or ""))

    family_tokens = sum(m["totalTokens"] for m in members)
    family_tools = sum(m["toolCalls"] for m in members)
    family_steps = sum(m["modelSteps"] for m in members)

    return {
        "rootId": root_id,
        "currentId": conversation_id,
        "memberCount": len(members),
        "subagentCount": max(0, len(members) - 1),
        "familyTokens": family_tokens,
        "familyTools": family_tools,
        "familySteps": family_steps,
        "members": members,
        "edges": edges,
        "timeline": all_events[-160:],
    }


def get_insights_payload(range_key: str = "30d", day_filter: str = "") -> dict[str, Any]:
    details = _load_recent_details(limit=80)
    ls_meta = _fetch_ls_trajectories()
    live_quota = _fetch_live_gemini_quota()
    parent_of = _build_parent_index(details)
    by_id = {d["conversationId"]: d for d in details}

    # Calibrate weighted Gemini tokens per 1% of a 5h quota window using live GetUserStatus
    tokens_per_1pct = 380_000.0
    calibrated = False
    win_start_dt = _parse_iso(live_quota.get("windowStartIso") or "")
    win_end_dt = _parse_iso(live_quota.get("windowEndIso") or "")
    session_window_weighted: dict[str, int] = defaultdict(int)
    if live_quota.get("available") and win_start_dt and win_end_dt:
        total_win_weighted = 0
        for d in details:
            cid = d["conversationId"]
            for step_ts, w_tok in d.get("_geminiStepRecords", []):
                sdt = _parse_iso(step_ts)
                if sdt and win_start_dt <= sdt <= win_end_dt:
                    session_window_weighted[cid] += w_tok
                    total_win_weighted += w_tok
        consumed_pct = float(live_quota.get("consumedPct") or 0.0)
        if consumed_pct >= 1.0 and total_win_weighted >= 50_000:
            raw_unit = total_win_weighted / consumed_pct
            tokens_per_1pct = max(120_000.0, min(1_800_000.0, raw_unit))
            calibrated = True

    now_local = datetime.now().astimezone()
    today_str = now_local.strftime("%Y-%m-%d")
    if range_key == "today":
        cutoff_str = today_str
    elif range_key == "7d":
        cutoff_str = (now_local - timedelta(days=6)).strftime("%Y-%m-%d")
    elif range_key == "30d":
        cutoff_str = (now_local - timedelta(days=29)).strftime("%Y-%m-%d")
    else:
        cutoff_str = ""

    heatmap_totals: defaultdict[str, int] = defaultdict(int)
    heatmap_calls: defaultdict[str, int] = defaultdict(int)
    for d in details:
        for dk, v in d.get("dailyTokens", {}).items():
            heatmap_totals[dk] += v
        for dk, v in d.get("dailyCalls", {}).items():
            heatmap_calls[dk] += v

    heatmap: list[dict[str, Any]] = []
    for i in range(55, -1, -1):
        day = (now_local - timedelta(days=i)).strftime("%Y-%m-%d")
        heatmap.append({"day": day, "tokens": heatmap_totals.get(day, 0), "calls": heatmap_calls.get(day, 0)})

    last7: list[dict[str, Any]] = [
        {"day": h["day"], "label": h["day"][5:], "tokens": h["tokens"], "calls": h["calls"]}
        for h in heatmap[-7:]
    ]

    filtered: list[dict[str, Any]] = []
    for d in details:
        s_days = set(d.get("dailyTokens", {}).keys())
        if not s_days and d.get("lastTs"):
            ld = _local_day(d["lastTs"])
            if ld:
                s_days.add(ld)
        if day_filter:
            if day_filter not in s_days:
                continue
        elif cutoff_str:
            if not any(dk >= cutoff_str for dk in s_days):
                continue
        filtered.append(d)

    total_tokens = 0
    total_in = 0
    total_cache = 0
    total_out = 0
    total_calls = 0
    total_tools = 0
    total_turns = 0
    total_subagents = 0
    agg_comp = Counter()
    agg_tools = Counter()
    agg_skills = Counter()
    agg_programs = Counter()

    def build_row(d: dict[str, Any], *, role_override: str | None = None, parent_id: str | None = None) -> dict[str, Any]:
        cid = d["conversationId"]
        st = d["stats"]
        meta = ls_meta.get(cid, {})
        proj = meta.get("project") or "未绑定项目"
        proj_key = meta.get("projectKey") or "__unbound__"
        if proj_key == "__unbound__" and parent_id and parent_id in ls_meta:
            proj = ls_meta[parent_id].get("project") or proj
            proj_key = ls_meta[parent_id].get("projectKey") or proj_key

        gw = st["geminiWeightedTokens"]
        g_pct = round(gw / tokens_per_1pct, 1) if gw > 0 else 0.0
        win_w = session_window_weighted.get(cid, 0)
        win_pct = round(win_w / tokens_per_1pct, 1) if win_w > 0 else 0.0

        return {
            "conversationId": cid,
            "shortId": cid[:8],
            "title": role_override or meta.get("summary") or d["title"],
            "project": proj,
            "projectKey": proj_key,
            "isSubagent": parent_id is not None,
            "parentId": parent_id,
            "role": role_override,
            "model": d["model"],
            "scene": d["scene"],
            "lastTs": d["lastTs"],
            "durationSeconds": d["durationSeconds"],
            "occupancyPct": d["occupancyPct"],
            "calls": st["modelSteps"],
            "totalTokens": st["totalTokens"],
            "weightedTokens": st["weightedTokens"],
            "inputBilled": st["totalInputBilled"],
            "cacheRead": st["totalCacheRead"],
            "outputTokens": st["totalOutputTokens"],
            "cacheHitRate": st["cacheHitRate"],
            "peakContext": st["peakContext"],
            "geminiQuotaPct": g_pct,
            "windowQuotaPct": win_pct,
            "inCurrentWindow": win_w > 0,
            "stats": st,
            "currentComposition": d["currentComposition"],
            "children": [],
            "childCount": 0,
        }

    # Build top-level rows (root sessions roll up their child subagents into expandable rows!)
    filtered_ids = {d["conversationId"] for d in filtered}
    children_by_parent: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in details:
        cid = d["conversationId"]
        if cid in parent_of:
            pid, spawn_info = parent_of[cid]
            children_by_parent[pid].append(build_row(d, role_override=spawn_info.get("role") or cid[:8], parent_id=pid))

    for d in filtered:
        st = d["stats"]
        total_tokens += st["totalTokens"]
        total_in += st["totalInputBilled"]
        total_cache += st["totalCacheRead"]
        total_out += st["totalOutputTokens"]
        total_calls += st["modelSteps"]
        total_tools += st["toolCalls"]
        total_turns += st["userTurns"]
        total_subagents += st["subagentCount"]
        for k, v in d["currentComposition"].items():
            agg_comp[k] += v
        for item in d["topTools"]:
            agg_tools[item["name"]] += item["count"]
        for item in d["topSkills"]:
            agg_skills[item["name"]] += item["count"]
        for item in d["topPrograms"]:
            agg_programs[item["name"]] += item["count"]

    root_rows: list[dict[str, Any]] = []
    for d in filtered:
        cid = d["conversationId"]
        # Skip child subagents at top level if their parent is also in filtered
        if cid in parent_of and parent_of[cid][0] in filtered_ids:
            continue
        pinfo = parent_of.get(cid)
        row = build_row(d, role_override=(pinfo[1].get("role") if pinfo else None), parent_id=(pinfo[0] if pinfo else None))
        ch_list = children_by_parent.get(cid, [])
        if ch_list:
            # Roll up parent + children into parent's summary row (just like Image 1!)
            row["children"] = sorted(ch_list, key=lambda x: x["totalTokens"], reverse=True)
            row["childCount"] = len(ch_list)
            roll_calls = row["calls"] + sum(c["calls"] for c in ch_list)
            roll_in = row["inputBilled"] + sum(c["inputBilled"] for c in ch_list)
            roll_cache = row["cacheRead"] + sum(c["cacheRead"] for c in ch_list)
            roll_out = row["outputTokens"] + sum(c["outputTokens"] for c in ch_list)
            roll_total = roll_in + roll_cache + roll_out
            roll_weighted = row["weightedTokens"] + sum(c["weightedTokens"] for c in ch_list)
            roll_gpct = round(row["geminiQuotaPct"] + sum(c["geminiQuotaPct"] for c in ch_list), 1)
            roll_wpct = round(row["windowQuotaPct"] + sum(c["windowQuotaPct"] for c in ch_list), 1)
            roll_prompt = roll_in + roll_cache
            row["calls"] = roll_calls
            row["inputBilled"] = roll_in
            row["cacheRead"] = roll_cache
            row["outputTokens"] = roll_out
            row["totalTokens"] = roll_total
            row["weightedTokens"] = roll_weighted
            row["cacheHitRate"] = round((roll_cache / roll_prompt) * 100.0, 1) if roll_prompt > 0 else 0.0
            row["geminiQuotaPct"] = roll_gpct
            row["windowQuotaPct"] = roll_wpct
            row["inCurrentWindow"] = row["inCurrentWindow"] or any(c["inCurrentWindow"] for c in ch_list)
            if ch_list:
                latest_child_ts = max((c["lastTs"] for c in ch_list if c["lastTs"]), default="")
                if latest_child_ts > row["lastTs"]:
                    row["lastTs"] = latest_child_ts
        root_rows.append(row)

    # Project rollup ("项目汇总")
    proj_map: dict[str, dict[str, Any]] = {}
    for r in root_rows:
        pk = r["projectKey"]
        p = proj_map.setdefault(
            pk,
            {
                "projectKey": pk,
                "project": r["project"],
                "sessionCount": 0,
                "subagentCount": 0,
                "calls": 0,
                "inputBilled": 0,
                "cacheRead": 0,
                "outputTokens": 0,
                "totalTokens": 0,
                "weightedTokens": 0,
                "geminiQuotaPct": 0.0,
                "peakContext": 0,
                "lastTs": "",
                "_models": Counter(),
            },
        )
        p["sessionCount"] += 1
        p["subagentCount"] += r["childCount"]
        p["calls"] += r["calls"]
        p["inputBilled"] += r["inputBilled"]
        p["cacheRead"] += r["cacheRead"]
        p["outputTokens"] += r["outputTokens"]
        p["totalTokens"] += r["totalTokens"]
        p["weightedTokens"] += r["weightedTokens"]
        p["geminiQuotaPct"] = round(p["geminiQuotaPct"] + r["geminiQuotaPct"], 1)
        p["peakContext"] = max(p["peakContext"], r["peakContext"])
        if r["lastTs"] > p["lastTs"]:
            p["lastTs"] = r["lastTs"]
        p["_models"][r["model"]] += max(1, r["calls"])

    projects = []
    for p in proj_map.values():
        prompt_sum_p = p["inputBilled"] + p["cacheRead"]
        dom_model = p["_models"].most_common(1)[0][0] if p["_models"] else "Unknown"
        projects.append(
            {
                "projectKey": p["projectKey"],
                "project": p["project"],
                "sessionCount": p["sessionCount"],
                "subagentCount": p["subagentCount"],
                "dominantModel": dom_model,
                "calls": p["calls"],
                "inputBilled": p["inputBilled"],
                "cacheRead": p["cacheRead"],
                "outputTokens": p["outputTokens"],
                "totalTokens": p["totalTokens"],
                "weightedTokens": p["weightedTokens"],
                "cacheHitRate": round((p["cacheRead"] / prompt_sum_p) * 100.0, 1) if prompt_sum_p > 0 else 0.0,
                "geminiQuotaPct": p["geminiQuotaPct"],
                "peakContext": p["peakContext"],
                "lastTs": p["lastTs"],
            }
        )
    projects.sort(key=lambda x: (x["projectKey"] == "__unbound__", -x["totalTokens"]))

    prompt_sum = total_in + total_cache
    cache_rate = round((total_cache / prompt_sum) * 100, 1) if prompt_sum > 0 else 0.0

    return {
        "ok": True,
        "range": range_key,
        "dayFilter": day_filter,
        "quota": {
            **live_quota,
            "calibrated": calibrated,
            "tokensPer1Pct": int(round(tokens_per_1pct)),
        },
        "kpi": {
            "sessions": len(filtered),
            "rootSessions": len(root_rows),
            "totalTokens": total_tokens,
            "inputBilled": total_in,
            "cacheRead": total_cache,
            "outputTokens": total_out,
            "cacheHitRate": cache_rate,
            "modelSteps": total_calls,
            "toolCalls": total_tools,
            "userTurns": total_turns,
            "subagents": total_subagents,
        },
        "last7Days": last7,
        "heatmap": heatmap,
        "composition": dict(agg_comp),
        "topTools": [{"name": k, "count": v} for k, v in agg_tools.most_common(12)],
        "topSkills": [{"name": k, "count": v} for k, v in agg_skills.most_common(12)],
        "topPrograms": [{"name": k, "count": v} for k, v in agg_programs.most_common(12)],
        "projects": projects,
        "sessions": root_rows,
    }
