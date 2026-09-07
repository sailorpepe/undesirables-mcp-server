# The Undesirables — MCP Server
# Lightweight Dockerfile for Glama registry validation
# Runs the ORACLE server (oracle_server.py, 23 tools), the default entry point since v2.0.0.
# Enough to start and answer MCP introspection (initialize, tools/list). No ML/GPU packages.

FROM python:3.12-slim

WORKDIR /app

# Install only the core dependencies needed for server startup
RUN pip install --no-cache-dir \
    "mcp>=1.10,<2" \
    "httpx>=0.27" \
    "pydantic>=2.0"

# the oracle server: 23 tools over stdio, backed by the public oracle API
COPY oracle_server.py mcp_remote.py tccensus_client.py ./
COPY smithery.yaml .

# MCP stdio transport
ENTRYPOINT ["python", "oracle_server.py"]
