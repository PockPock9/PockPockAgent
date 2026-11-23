"""A tiny stdio MCP server for the hub's tests. Not used by the app.

Tools: ``echo`` (returns its text and the FAKE_GREETING environment value), ``roots`` (asks the client
for its roots first), ``slow`` (answers after ``seconds``), ``crash`` (exits at once).
"""

import json
import os
import sys
import time

TOOLS = [
    {"name": "echo", "description": "Echo a text.", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
    {"name": "roots", "description": "List the client's roots.", "inputSchema": {"type": "object"}},
    {"name": "slow", "description": "Answer after a delay.", "inputSchema": {"type": "object", "properties": {"seconds": {"type": "number"}}}},
    {"name": "crash", "description": "Exit.", "inputSchema": {"type": "object"}},
]


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main():
    print("fake server starting", file=sys.stderr, flush=True)
    sys.stdout.write("banner line that is not JSON\n")
    sys.stdout.flush()
    for line in sys.stdin:
        message = json.loads(line)
        method, request_id = message.get("method"), message.get("id")
        if request_id is None or method is None:
            continue
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": True}}, "serverInfo": {"name": "fake", "version": "1"}, "instructions": "Fake server."}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            name = message["params"]["name"]
            arguments = message["params"].get("arguments") or {}
            if name == "echo":
                text = f"{arguments.get('text', '')}|{os.environ.get('FAKE_GREETING', '')}|pid={os.getpid()}"
                send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text}]}})
            elif name == "roots":
                send({"jsonrpc": "2.0", "id": "server-1", "method": "roots/list"})
                reply = json.loads(sys.stdin.readline())
                send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": json.dumps(reply)}]}})
            elif name == "slow":
                time.sleep(float(arguments.get("seconds", 1)))
                send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": "done"}]}})
            elif name == "crash":
                print("crashing on purpose", file=sys.stderr, flush=True)
                os._exit(3)
            else:
                send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": f"Unknown tool {name}"}})
        else:
            send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}})


if __name__ == "__main__":
    main()
