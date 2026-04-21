import sys
import json
import asyncio
import inspect
import io
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import uvicorn

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

app = FastAPI()

def synthesize_sync(text: str, kwargs: dict):
    from voice_engine import _get_tts, soul_to_voice_preset
    import numpy as np
    import soundfile as sf
    import logging

    traits = {
        "openness": kwargs.get("soul_openness", 50),
        "conscientiousness": kwargs.get("soul_conscientiousness", 50),
        "extraversion": kwargs.get("soul_extraversion", 50),
        "agreeableness": kwargs.get("soul_agreeableness", 50),
        "neuroticism": kwargs.get("soul_neuroticism", 50),
    }
    preset = soul_to_voice_preset(traits)
    
    pipeline = _get_tts()
    if pipeline is None:
        raise RuntimeError("Kokoro TTS not installed")

    MAX_TTS_TEXT = 5000
    if len(text) > MAX_TTS_TEXT:
        text = text[:MAX_TTS_TEXT]

    speed = max(0.7, min(1.4, preset.get("speed", 1.0)))

    all_audio = []
    # Generate audio
    for _, _, audio in pipeline(text, voice=preset["voice"], speed=speed):
        all_audio.append(audio)

    if not all_audio:
        raise RuntimeError("No audio generated")

    full_audio = np.concatenate(all_audio)
    
    buf = io.BytesIO()
    sf.write(buf, full_audio, 24000, format='WAV')
    return buf.getvalue()


@app.post("/mcp/speak")
async def speak(request: Request):
    try:
        payload = await request.json()
        
        # Offload the heavy TTS to a background thread to prevent blocking 
        # the FastAPI async event loop
        wav_bytes = await asyncio.to_thread(synthesize_sync, payload.get("text", ""), payload)
        
        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/")
async def mcp_handler(request: Request):
    """Standard MCP RPC handler over HTTP"""
    try:
        payload = await request.json()
        tool_name = payload.get("tool_name")
        args = payload.get("args", {})

        # SECURITY: Prevent MRO traversing
        if not isinstance(tool_name, str) or tool_name.startswith('_'):
            return JSONResponse({"error": "Security Error: Malicious dynamic invocation attempt blocked."}, status_code=403)

        if not tool_name or tool_name not in ALLOWED_TOOLS:
            return JSONResponse({"error": f"Security Error: '{tool_name}' is not a registered MCP tool."}, status_code=403)

        func = getattr(server, tool_name, None)
        if not func or not callable(func):
            return JSONResponse({"error": f"Tool '{tool_name}' not found natively in server.py"}, status_code=404)

        # Validate parameters
        sig = inspect.signature(func)
        allowed_params = set(sig.parameters.keys())
        filtered_args = {k: v for k, v in args.items() if k in allowed_params}

        # Execute
        if asyncio.iscoroutinefunction(func):
            res = await func(**filtered_args)
        else:
            # We run native sync MCP tools in a threadpool so they don't block either
            res = await asyncio.to_thread(func, **filtered_args)

        return JSONResponse({"result": res})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

def main():
    print("Starting Persistent FastAPI MCP Server on port 8740...")
    server.enable_memory_lock()
    server.main()
    
    # Run uvicorn server mapping to the same port the frontend expects
    uvicorn.run(app, host="127.0.0.1", port=8740, log_level="error")

if __name__ == '__main__':
    main()
