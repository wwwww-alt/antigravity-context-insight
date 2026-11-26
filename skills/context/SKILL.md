---
name: context
description: >-
  Open the interactive Antigravity Context Insight dashboard (inspired by dsh-context)
  to inspect context window composition, step-by-step token evolution, cache hit rate,
  file & command activity, cross-session insights, and multi-agent Fleet collaboration.
  Use when the user types /context or asks to inspect context usage, token breakdown,
  prompt evolution, or subagent/multi-agent activity.
---

# Context Insight (`/context`)

Call the `open_context_insight` tool from the `agy-context` plugin MCP server to open the interactive Context Insight panel in the side pane.

## Parameters

- `conversation_id` (optional): Pass the current conversation ID if you want to focus directly on this conversation; leave empty to auto-select the most recently active conversation.
- `tab` (optional): One of `"context"` (default — composition, trend, browser, files, commands), `"insights"` (cross-session KPIs, 7-day chart, 8-week heatmap), or `"fleet"` (multi-agent family network & cross-agent collaboration timeline).

## Tips

- When the user asks about "当前上下文 / `/context` / token 占用", pass the current conversation ID with `tab="context"`.
- When the user asks about "多 Agent / 子代理 / 编队 / Fleet", open with `tab="fleet"`.
- When the user asks about "全局统计 / 近 7 天 / 热力图 / 跨会话洞察", open with `tab="insights"`.
