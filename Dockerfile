# The MCP server, containerised so registries can introspect it.
#
# This image runs `stipend mcp` — the local stdio server — with no wallet and no
# key. That is deliberate and it is the whole point: introspection needs to see
# the tool list, and seeing the tool list must never require a keystore. Nothing
# in this container can move money, because there is nothing here to move.
#
#   docker build -t stipend .
#   docker run -i --rm stipend
#
# Speaks JSON-RPC over stdin/stdout. Nothing listens on a port.

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY stipend/ ./stipend/

# Unbuffered, or a stdio transport deadlocks waiting on a flush that never comes.
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "stipend", "mcp"]
