"""Small real MCP stdio server used by the integration test."""

from mcp.server import MCPServer

server = MCPServer("MASP test")


@server.tool()
def echo(value: str) -> str:
    """Return a value to the caller."""
    return value


if __name__ == "__main__":
    server.run(transport="stdio")
