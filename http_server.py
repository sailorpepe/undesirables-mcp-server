import sys
import json
import asyncio
import inspect
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Dynamically resolve the MCP server directory
M_DIR = Path(__file__).resolve().parent
sys.path.append(str(M_DIR))

import server

# Same strict security whitelist from execute_tool.py
ALLOWED_TOOLS = frozenset({
    "create_banner", "remove_background", "invoke_council", "grade_tcg_card", "search_ebay_market",
    "get_skill", "list_skills", "generate_meme", "produce_video",
    "video_production_beat_sync", "viral_clip_extractor",
    "detect_emotion", "soul_speak", "soul_listen", "soul_rap", "get_voice_preset",
    "generate_3d_object", "image_to_3d",
    "index_soul_workspace", "get_rag_context",
    "upsert_memory_node", "create_memory_relation", "query_memory_graph",
    "search_soul_memory", "get_memory_subgraph", "memory_save", "memory_recall",
    "scan_media_file",
    "self_reflect", "query_ollama", "web_search", "run_security_audit",
    "generate_music", "analyze_beats",
    "market_depth_analysis", "monte_carlo_simulation",
})

class MCPHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self._send_error("Empty payload")
                return

            post_data = self.rfile.read(content_length)
            payload = json.loads(post_data.decode('utf-8'))

            tool_name = payload.get("tool_name")
            args = payload.get("args", {})

            # SECURITY: Prevent MRO traversing
            if not isinstance(tool_name, str) or tool_name.startswith('_'):
                self._send_error("Security Error: Malicious dynamic invocation attempt blocked.")
                return

            if not tool_name or tool_name not in ALLOWED_TOOLS:
                self._send_error(f"Security Error: '{tool_name}' is not a registered MCP tool.")
                return

            func = getattr(server, tool_name, None)
            if not func or not callable(func):
                self._send_error(f"Tool '{tool_name}' not found natively in server.py")
                return

            # Validate parameters
            sig = inspect.signature(func)
            allowed_params = set(sig.parameters.keys())
            filtered_args = {k: v for k, v in args.items() if k in allowed_params}

            # Execute
            if asyncio.iscoroutinefunction(func):
                res = asyncio.run(func(**filtered_args))
            else:
                res = func(**filtered_args)

            self._send_success({"result": res})

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_error(str(e))

    def _send_success(self, data):
        data_bytes = json.dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data_bytes)))
        self.end_headers()
        self.wfile.write(data_bytes)

    def _send_error(self, err_msg):
        print(f"[HTTP] Error: {err_msg}", file=sys.stderr)
        data_bytes = json.dumps({"error": err_msg}).encode('utf-8')
        self.send_response(500)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data_bytes)))
        self.end_headers()
        self.wfile.write(data_bytes)
        
    def log_message(self, format, *args):
        # Mute standard HTTP logs
        pass

def main():
    print("Starting Persistent MCP HTTP Server on port 8740...")
    server.enable_memory_lock()
    server.main()
    
    server_address = ('127.0.0.1', 8740)
    # Using basic HTTPServer which processes one request at a time sequentially.
    # This guarantees thread-safety for global ML models (Kokoro, RAG, etc).
    httpd = HTTPServer(server_address, MCPHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

if __name__ == '__main__':
    main()
