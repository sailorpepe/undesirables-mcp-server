# The Undesirables — MCP Server
# Lightweight Dockerfile for Glama registry validation
# Installs core deps only (no ML/GPU packages) — enough to start
# the server and respond to MCP introspection (initialize, tools/list)

FROM python:3.12-slim

WORKDIR /app

# Install only the core dependencies needed for server startup
RUN pip install --no-cache-dir \
    "fastmcp>=3.1.0" \
    "pydantic>=2.0" \
    "requests>=2.31" \
    "numpy>=2.0" \
    "pillow>=10.0" \
    "ijson>=3.0" \
    "typing_extensions>=4.0"

COPY server.py .
COPY smithery.yaml .

# MCP stdio transport
ENTRYPOINT ["python", "server.py"]
