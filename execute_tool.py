import sys
import json
import asyncio
import inspect
from pathlib import Path

# Dynamically resolve the MCP server directory relative to this script
M_DIR = Path(__file__).resolve().parent
sys.path.append(str(M_DIR))

import server

# ============================================================
# SECURITY FIX: Whitelist of registered MCP tool functions.
# Prevents unrestricted getattr() dispatch from invoking
# internal Python builtins, module attributes, or private state.
# ============================================================
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
    # SECURITY: execute_code, execute_shell, update_memory PERMANENTLY REMOVED
    # These bypass the Tauri sandbox and allow arbitrary OS-level code execution.
    # create_prediction, grade_prediction REMOVED — functions never implemented.
    "self_reflect", "query_ollama", "web_search", "run_security_audit",
    "generate_music", "analyze_beats",
    "market_depth_analysis", "monte_carlo_simulation",
})

async def run():
    try:
        payload_str = sys.stdin.read()
        if not payload_str.strip():
            print(json.dumps({"error": "Empty payload received on stdin."}))
            return

        payload = json.loads(payload_str)
        tool_name = payload.get("tool_name")
        args = payload.get("args", {})

        # SECURITY: Prevent Python MRO traversal / dunder method escapes
        if not isinstance(tool_name, str) or tool_name.startswith('_'):
            print(json.dumps({"error": "Security Error: Malicious dynamic invocation attempt blocked (dunder methods restricted)."}))
            return

        # SECURITY: Enforce strict whitelist before dynamic dispatch
        if not tool_name or tool_name not in ALLOWED_TOOLS:
            print(json.dumps({"error": f"Security Error: '{tool_name}' is not a registered MCP tool. Access denied."}))
            return
        
        func = getattr(server, tool_name, None)
        if not func or not callable(func):
            print(json.dumps({"error": f"Tool '{tool_name}' not found natively in server.py"}))
            return
            
        # Dynamically execute as Coroutine or Sync based on the server.py signature
        # SECURITY (CRIT-1): Filter args to only include keys matching the function's
        # actual parameter signature. Prevents kwargs injection attacks.
        sig = inspect.signature(func)
        allowed_params = set(sig.parameters.keys())
        

        filtered_args = {k: v for k, v in args.items() if k in allowed_params}
        rejected_keys = set(args.keys()) - allowed_params
        if rejected_keys:
            print(json.dumps({"warning": f"Rejected unknown parameters: {rejected_keys}"}), file=sys.stderr)

        if asyncio.iscoroutinefunction(func):
            res = await func(**filtered_args)
        else:
            res = func(**filtered_args)
            
        print(json.dumps({"result": res}))

    except Exception as e:
        print(json.dumps({"error": str(e)}))

if __name__ == "__main__":
    # Ensure asyncio uses standard loop policy
    asyncio.run(run())
