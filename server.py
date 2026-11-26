from __future__ import annotations

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

import analytics

PLUGIN_ROOT = Path(__file__).resolve().parent
APP_HTML_PATH = Path(os.environ.get("AGY_CONTEXT_APP_HTML", str(PLUGIN_ROOT / "ui" / "app.html")))
APP_URI = "ui://agy-context/app.html"

mcp = MCPServer("agy-context")

PANE_META = {
    "ui": {"resourceUri": APP_URI},
    "com.google.antigravity/ui": {
        "entrypoints": [
            {"type": "aux_pane", "title": "Context Insight"},
            {"type": "global", "title": "Context Insight"},
        ]
    },
}

APP_ONLY_META = {"ui": {"visibility": ["app"]}}


@mcp.resource(
    APP_URI,
    name="Context Insight UI",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": False}},
)
def context_insight_html() -> str:
    if not APP_HTML_PATH.is_file():
        return "<!doctype html><html><body><p>Context Insight UI bundle missing.</p></body></html>"
    return APP_HTML_PATH.read_text(encoding="utf-8")


@mcp.tool(
    name="open_context_insight",
    title="Context Insight",
    description=(
        "Open the interactive Antigravity Context Insight dashboard (adapted from dsh-context) "
        "to inspect context composition, token evolution, cache hit rate, file/command activity, "
        "cross-session insights, and multi-agent Fleet collaboration."
    ),
    meta=PANE_META,
)
def open_context_insight(conversation_id: str = "", tab: str = "context") -> CallToolResult:
    valid_tab = tab if tab in ("insights", "context", "fleet") else "context"
    payload = analytics.get_session_payload(conversation_id=conversation_id)
    insights = analytics.get_insights_payload(range_key="30d")

    # Keep initial trajectory payload compact (<1 MiB); full browser items fetched on demand if large
    if payload.get("ok") and payload.get("session"):
        s = payload["session"]
        st = s["stats"]
        summary = (
            f"Opened Context Insight ({valid_tab}) for '{s['title']}' ({s['conversationId'][:8]}): "
            f"current context {st['currentContext']:,} tokens ({s['occupancyPct']}%), "
            f"cache hit {st['cacheHitRate']}%, {st['modelSteps']} model steps, "
            f"{st['toolCalls']} tool calls, {st['subagentCount']} subagents."
        )
        # Trim heavy content strings in initial push to stay tiny; app calls app_get_session for full detail
        lite_session = {**s}
        lite_session["browserItems"] = [
            {k: v for k, v in item.items() if k not in ("content", "thinking", "answer")}
            for item in s.get("browserItems", [])[-160:]
        ]
        lite_session["commands"] = [
            {k: v for k, v in c.items() if k != "outputPreview"}
            for c in s.get("commands", [])[-120:]
        ]
        structured = {
            "ok": True,
            "initialTab": valid_tab,
            "session": lite_session,
            "fleet": payload["fleet"],
            "sessions": payload["sessions"],
            "insights": insights,
        }
    else:
        summary = "Opened Context Insight (no transcripts found yet)."
        structured = {
            "ok": False,
            "initialTab": "insights",
            "error": payload.get("error", "No sessions found"),
            "sessions": [],
            "insights": insights,
        }

    return CallToolResult(
        content=[TextContent(type="text", text=summary)],
        structured_content=structured,
    )


@mcp.tool(name="app_get_session", meta=APP_ONLY_META)
def app_get_session(conversation_id: str = "") -> CallToolResult:
    payload = analytics.get_session_payload(conversation_id=conversation_id)
    return CallToolResult(
        content=[TextContent(type="text", text="Session loaded")],
        structured_content=payload,
    )


@mcp.tool(name="app_get_insights", meta=APP_ONLY_META)
def app_get_insights(range_key: str = "30d", day_filter: str = "") -> CallToolResult:
    payload = analytics.get_insights_payload(range_key=range_key, day_filter=day_filter)
    return CallToolResult(
        content=[TextContent(type="text", text="Insights loaded")],
        structured_content=payload,
    )


@mcp.tool(name="app_get_fleet", meta=APP_ONLY_META)
def app_get_fleet(conversation_id: str = "") -> CallToolResult:
    sess = analytics.get_session_payload(conversation_id=conversation_id)
    fleet = sess.get("fleet") if sess.get("ok") else {"members": [], "edges": [], "timeline": []}
    return CallToolResult(
        content=[TextContent(type="text", text="Fleet loaded")],
        structured_content={"ok": True, "fleet": fleet},
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
