"""MCP capability loader — extension point.

Once the provider layer (Phase 2) can reach configured MCP servers, this loader
will introspect each connected server's ``tools/list`` and emit one ``Capability``
per tool, with ``provenance="mcp:<server>"``. Until then it returns the empty set
so the registry stays honest about what is actually wired.

The shape is fixed now so the registry does not change when MCP lands:
    for server in connected_servers:
        for tool in mcp_list_tools(server):
            yield Capability.build(
                id=f"mcp.{server}.{tool.name}",
                kind="tool",
                summary=tool.description.splitlines()[0][:100],
                risk=infer_risk(tool),
                schema_in=tool.inputSchema,
                provenance=f"mcp:{server}",
                tags=("mcp", server, *tool.tags),
            )
"""
from __future__ import annotations

from ..capability import Capability


def load() -> list[Capability]:
    """No MCP servers are introspected yet; return an empty set."""
    return []
