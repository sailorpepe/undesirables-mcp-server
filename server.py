#!/usr/bin/env python3
"""
The Undesirables — MCP Server
=============================
Exposes AI Soul personalities and skills via the Model Context Protocol (MCP).

Any MCP-compatible client (Cursor, Claude Desktop, VS Code, ElizaOS)
can connect and interact with Undesirable agents using this server.

Usage:
    # Point to a soul workspace folder
    python server.py --workspace ./path/to/soul/0420

    # Or specify a token ID and souls directory
    python server.py --token 420 --souls-dir ./souls

    # Run with stdio transport (for IDE integration)
    fastmcp run server.py
"""

import os
import sys
import re
import json
import glob
import logging
import argparse
import subprocess
import requests
from typing import List
from pathlib import Path
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# Determine if librosa is available (will be explicitly required in requirements.txt)
try:
    import librosa
    import numpy as np
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False

# Platform detection for capabilities
import platform
IS_APPLE_SILICON = platform.system() == "Darwin" and platform.machine() == "arm64"
IS_MACOS = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"
IS_WINDOWS = platform.system() == "Windows"

def get_hw_encoder():
    """Return the best available H.264 encoder for the current platform."""
    if IS_APPLE_SILICON or IS_MACOS:
        return "h264_videotoolbox"
    # On Linux/Windows, try NVENC (NVIDIA), then VAAPI (Intel/AMD), then software
    import shutil
    if shutil.which("ffmpeg"):
        try:
            result = subprocess.run(
                ["ffmpeg", "-encoders"], capture_output=True, text=True, timeout=5
            )
            if "h264_nvenc" in result.stdout:
                return "h264_nvenc"  # NVIDIA GPU
            if "h264_amf" in result.stdout:
                return "h264_amf"  # AMD GPU (Windows)
            if "h264_qsv" in result.stdout:
                return "h264_qsv"  # Intel Quick Sync
            if "h264_vaapi" in result.stdout:
                return "h264_vaapi"  # Intel/AMD on Linux
        except Exception:
            pass
    return "libx264"  # Universal software fallback

HW_ENCODER = None  # Lazy-initialized

# Configure logging to strictly use stderr to prevent MCP JSON-RPC corruption
logging.basicConfig(stream=sys.stderr, level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("undesirables-mcp")

# ============================================================
# Initialize the MCP Server
# ============================================================

mcp = FastMCP(
    "The Undesirables",
    instructions="AI Soul personalities and skills from The Undesirables NFT collection. "
                 "4,444 autonomous agents with unique personalities, trading strategies, "
                 "and 35+ built-in tools. Powered by local Ollama inference.",
    version="1.1.5"
)

# Global state — set on startup
WORKSPACE_DIR = None
SOUL_DATA = {}
SKILLS = {}
MEMORY = ""
SYSTEM_PROMPT = ""
PREDICTIONS = []

import threading

# ============================================================
# SECURITY FIX: Sys Audit Hook for RCE mitigation
# NOTE: Removed overly aggressive `ctypes.dlopen` strict blocking
# because it panics Core ML / OpenCV bindings during matrix operations.
# ============================================================
def fastmcp_audit_hook(event, args):
    if event in ["mmap.__new__"]:
        logger.error(f"[SECURITY ALERT] Blocked malicious OS execution attempt via {event}")
        raise PermissionError(f"Security Error: Dynamic library mapping ({event}) is strictly prohibited.")
sys.addaudithook(fastmcp_audit_hook)

# NOTE: Auto pip-install on boot has been REMOVED (supply chain risk).
# Dependencies are now pinned in requirements.txt and bundled with the app.
# To update security tools manually, run:
#   pip install --upgrade semgrep slither-analyzer exifread pillow
logger.info("[SECURITY] Using bundled dependency versions (no auto-upgrade).")

# ============================================================
# Workspace Loader
# ============================================================

def load_workspace(workspace_path: str):
    """Load all files from a soul workspace directory."""
    global WORKSPACE_DIR, SOUL_DATA, SKILLS, MEMORY, SYSTEM_PROMPT, PREDICTIONS

    WORKSPACE_DIR = Path(workspace_path).resolve()

    def get_safe_path(requested_file: str) -> Path:
        target_path = (WORKSPACE_DIR / requested_file).resolve()
        if not target_path.is_relative_to(WORKSPACE_DIR):
            logger.warning(f"Security Error: Path traversal attempt blocked: {requested_file}")
            raise ValueError(f"Security Error: Path access denied. Operations constrained to workspace.")
        return target_path

    # Load SOUL.md
    soul_path = get_safe_path("SOUL.md")
    if soul_path.exists():
        SOUL_DATA["soul_md"] = soul_path.read_text(encoding="utf-8")

    # Load SYSTEM_PROMPT.txt
    system_path = get_safe_path("SYSTEM_PROMPT.txt")
    if system_path.exists():
        SYSTEM_PROMPT = system_path.read_text(encoding="utf-8")

    # Load MEMORY.md
    memory_path = get_safe_path("MEMORY.md")
    if memory_path.exists():
        MEMORY = memory_path.read_text(encoding="utf-8")

    # Load PREDICTIONS_LEDGER.json
    predictions_path = get_safe_path("PREDICTIONS_LEDGER.json")
    if predictions_path.exists():
        try:
            PREDICTIONS = json.loads(predictions_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            PREDICTIONS = []

    # Load all skills from skills/ directory
    skills_dir = get_safe_path("skills")
    if skills_dir.exists():
        for skill_file in sorted(skills_dir.glob("*.md")):
            skill_name = skill_file.stem  # e.g., "business_pilot"
            SKILLS[skill_name] = skill_file.read_text(encoding="utf-8")

    print(f"✅ Loaded workspace: {WORKSPACE_DIR}")
    print(f"   Skills: {len(SKILLS)} | Memory: {'Yes' if MEMORY else 'No'} | Predictions: {len(PREDICTIONS)}")


# ============================================================
# MCP RESOURCES — Read-only context data
# ============================================================

@mcp.resource("soul://personality")
def get_personality() -> str:
    """The agent's complete personality profile — Big Five scores, archetype,
    strategy, fatal flaw, speech style, and backstory from SOUL.md."""
    base_personality = SOUL_DATA.get("soul_md", "No soul loaded. Start the server with --workspace or --token.")
    ux_filter = "\n\n=== CRITICAL INTERACTION GUIDELINES ===\n1. Provide CLEAR, CRISP, AND SHORT interaction confirmations. Do not be long-winded.\n2. NEVER use forced slang like 'fam', 'bro', or 'innit' before every sentence. Speak naturally but directly."
    return base_personality + ux_filter


@mcp.resource("soul://system-prompt")
def get_system_prompt() -> str:
    """The agent's full system prompt — the complete instruction set that defines
    how this Undesirable thinks, speaks, and behaves."""
    base_prompt = SYSTEM_PROMPT or "No system prompt loaded."
    ux_filter = "\n\n=== CRITICAL INTERACTION GUIDELINES ===\n1. Provide CLEAR, CRISP, AND SHORT interaction confirmations. Do not be long-winded.\n2. NEVER use forced slang like 'fam', 'bro', or 'innit' before every sentence. Speak naturally but directly."
    return base_prompt + ux_filter


@mcp.resource("soul://memory")
def get_memory() -> str:
    """The agent's persistent memory — conversation history, learned patterns,
    trade history, and reflections. Updated over time as the agent operates."""
    return MEMORY or "No memory loaded."


@mcp.resource("soul://predictions")
def get_predictions() -> str:
    """The agent's prediction ledger — past market calls with grades.
    Shows whether the agent's conviction-weighted predictions were accurate."""
    if PREDICTIONS:
        return json.dumps(PREDICTIONS, indent=2)
    return "No predictions recorded yet."


@mcp.resource("soul://skills-index")
def get_skills_index() -> str:
    """Index of all available skills this agent has learned."""
    if not SKILLS:
        return "No skills loaded."
    index = "# Available Skills\n\n"
    for name, content in SKILLS.items():
        # Extract the first line as title
        first_line = content.strip().split("\n")[0].replace("# ", "")
        index += f"- **{name}**: {first_line}\n"
    return index


# ============================================================
# MCP TOOLS — AI-invokable functions
# ============================================================

@mcp.tool()
def create_banner(
    platform: str,
    title: str = "THE UNDESIRABLES",
    stats: str = "4,444 HAND-DRAWN NFTs",
    character_image_path: str = "",
    theme: str = "cyberpunk"
) -> str:
    """Create a promotional banner with a procedural mesh gradient backsplash and layered extracted character.
    Automatically scales to Scatter.art, OpenSea, or Twitter dimensions.
    
    Args:
        platform: Target platform ('scatter', 'x', 'twitter', 'opensea', 'discord', 'youtube')
        title: Main neon text 
        stats: Subtext 
        character_image_path: Absolute path to the transparent PFP cutout to layer on top
        theme: Color theme for the backsplash ('cyberpunk', 'vaporwave', 'gold', 'crimson', 'matrix')
    """
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    import os
    import time
    import base64
    import random
    from pathlib import Path
    
    # 1. Platform resolution
    p = platform.lower()
    if 'opensea' in p and 'mobile' in p:
        w, h = 1920, 1080
    elif 'opensea' in p:
        w, h = 2800, 1050
    elif 'twitter' in p or 'x' in p or 'premint' in p:
        w, h = 1500, 500
    elif 'discord' in p:
        w, h = 960, 540
    elif 'youtube' in p:
        w, h = 2560, 1440
    elif 'scatter' in p:
        w, h = 1500, 500
    else:
        w, h = 1500, 500
        
    try:
        # 2. Generative Mesh Gradient Backsplash
        themes = {
            "cyberpunk": [(12,10,18), (255,0,128), (0,255,255), (20,0,40)],
            "vaporwave": [(255,113,206), (1,205,254), (5,255,161), (185,103,255)],
            "gold": [(30,20,0), (255,215,0), (200,150,0), (10,5,0)],
            "crimson": [(40,0,0), (255,20,20), (100,0,10), (10,0,0)],
            "matrix": [(0,20,0), (0,255,50), (10,100,20), (0,40,0)]
        }
        colors = themes.get(theme.lower(), themes["cyberpunk"])
        
        # Create a tiny 4x4 mesh, plot random theme colors, and scale up with BICUBIC for huge elegant blurs
        mesh = Image.new("RGB", (4, 4))
        pixels = mesh.load()
        for x in range(4):
            for y in range(4):
                pixels[x,y] = random.choice(colors)
        img = mesh.resize((w, h), Image.Resampling.BICUBIC).convert("RGBA")
        
        # Darken the left side slightly for text readability
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw_ov = ImageDraw.Draw(overlay)
        for i in range(w // 2):
            alpha = int(210 * (1 - (i / (w // 2))))
            draw_ov.line([(i, 0), (i, h)], fill=(10, 10, 15, alpha))
        img = Image.alpha_composite(img, overlay)
        
        # 3. Layer the Transparent PFP Character (Right Side Anchor)
        if character_image_path and os.path.exists(character_image_path):
            char_img = Image.open(character_image_path).convert("RGBA")
            
            # Scale character to 95% of banner height so it fits beautifully
            target_h = int(h * 0.95)
            ratio = target_h / char_img.height
            target_w = int(char_img.width * ratio)
            
            char_img = char_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            
            # Push to the right edge
            paste_x = w - target_w - int(w * 0.05)
            paste_y = h - target_h
            
            # Apply dynamic drop shadow to the character layer
            shadow = Image.new("RGBA", char_img.size, (0,0,0,0))
            shadow.paste((0,0,0,160), mask=char_img.split()[3])
            shadow = shadow.filter(ImageFilter.GaussianBlur(15))
            
            # Paste shadow, then paste character
            img.paste(shadow, (paste_x - 10, paste_y + 10), mask=shadow)
            img.paste(char_img, (paste_x, paste_y), mask=char_img)
            
        # 4. Add Massive Typography
        draw = ImageDraw.Draw(img)
        def add_glow_text(tx, ty, text, size, color, glow_color):
            nonlocal img
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Impact.ttc", size)
            except Exception:
                font = ImageFont.load_default()
            
            glow = Image.new("RGBA", img.size, (0,0,0,0))
            ImageDraw.Draw(glow).text((tx,ty), text, font=font, fill=(*glow_color, 200))
            glow = glow.filter(ImageFilter.GaussianBlur(12))
            img = Image.alpha_composite(img, glow)
            ImageDraw.Draw(img).text((tx,ty), text, font=font, fill=(*color, 255))
            
        # Left aligned, giant text
        title_size = 180 if w > 1000 else 80
        stats_size = 60 if w > 1000 else 30
        
        tx = int(w * 0.08) # 8% padding from left
        ty_title = h // 2 - int(title_size // 1.2)
        ty_stats = ty_title + title_size + 20
        
        add_glow_text(tx, ty_title, title, title_size, (255, 255, 255), (255, 40, 130) if theme.lower() != 'vaporwave' else (5,255,161))
        add_glow_text(tx, ty_stats, stats, stats_size, (255, 200, 60), (0, 240, 255))
        
        # 5. Save output
        out_path = Path.home() / "Documents" / "Meme Merchants" / f"banner_{theme}_{int(time.time())}.png"
        
        final_rgb = Image.new("RGB", img.size, (0,0,0))
        final_rgb.paste(img, mask=img.split()[3])
        final_rgb.save(out_path, format="PNG")
        
        with open(out_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')
            
        return json.dumps({
            "status": "success",
            "message": f"Generative {theme} Banner created for {platform}",
            "path": str(out_path),
            "dimensions": f"{w}x{h}",
            "base64": b64
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return json.dumps({"error": str(e)})


class DeepMattingPipeline:
    def __init__(self, nft_style: str = "2d"):
        """
        Initializes the Sub-Pixel Segmentation Graph.
        Swapped to 'birefnet-general' (DIS) as it is vastly superior to 'isnet-anime' 
        at identifying complex topological holes and trapped negative space.
        """
        import rembg
        model_name = "birefnet-general" if nft_style.lower() == "2d" else "birefnet-general"
        self.session = rembg.new_session(model_name)

    def extract(self, input_image, fg_threshold=245, bg_threshold=10, erode_size=15):
        import rembg
        import numpy as np
        import scipy.ndimage
        from pymatting import estimate_alpha_cf, estimate_foreground_ml
        from PIL import Image
        import warnings
        import os, sys
        
        # --- THE FIX: SCOPED PYMATTING MONKEY PATCH ---
        # The Tikhonov Ridge shift stabilizes the Levin Matting Laplacian 
        # singularity caused by flat piece-wise 2D anime colors.
        # Patching submodules directly ensures internal imports use the shifted solver.
        import pymatting.preconditioner as pym_prec
        import pymatting.alpha.estimate_alpha_cf as acf
        import pymatting.foreground.estimate_foreground_ml as fml
        
        original_ichol = pym_prec.ichol
        
        def patched_ichol(A, *args, **kwargs):
            if 'shift' not in kwargs or kwargs['shift'] == 0.0:
                kwargs['shift'] = 1e-3
            return original_ichol(A, *args, **kwargs)
            
        pym_prec.ichol = patched_ichol
        if hasattr(acf, 'ichol'): acf.ichol = patched_ichol
        if hasattr(fml, 'ichol'): fml.ichol = patched_ichol

        original_rgb = np.array(input_image.convert("RGB"))
        
        # Complete MCP JSON-RPC Stream Protection (fd 1 & 2 redirects)
        sys.stdout.flush()
        sys.stderr.flush()
        
        stdout_fd = sys.stdout.fileno()          
        stderr_fd = sys.stderr.fileno()          
        saved_stdout_fd = os.dup(stdout_fd)      
        saved_stderr_fd = os.dup(stderr_fd)      
        devnull = os.open(os.devnull, os.O_WRONLY)
        
        try:
            os.dup2(devnull, stdout_fd)          
            os.dup2(devnull, stderr_fd)          
            
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                
                # 1. Neural Inference (Get Raw Mask)
                # CRITICAL: We bypass rembg's internal `alpha_matting=True`.
                # post_process_mask MUST be False to prevent OpenCV from morphologically 
                # obliterating thin wisps of smoke and cementing over holes.
                extracted_pil = rembg.remove(
                    input_image,
                    session=self.session,
                    alpha_matting=False,
                    post_process_mask=False
                )
                
                # Raw neural network probability mask [0, 255]
                raw_mask = np.array(extracted_pil)[:, :, 3]
                
                # 2. Asymmetric Trimap Generation (The Topological Fix)
                is_fg = raw_mask > fg_threshold
                is_bg = raw_mask < bg_threshold
                
                if erode_size > 0:
                    # Aggressively erode FOREGROUND to expand the "unknown" band inwards 
                    # allowing the solver to calculate soft smoke/hair tapers.
                    fg_structure = np.ones((erode_size, erode_size), dtype=np.bool_)
                    eroded_fg = scipy.ndimage.binary_erosion(is_fg, structure=fg_structure)
                    
                    # Do NOT erode the BACKGROUND. This guarantees that small negative space 
                    # holes preserve their `0.0` anchor for the Laplacian solver.
                    eroded_bg = is_bg
                else:
                    eroded_fg = is_fg
                    eroded_bg = is_bg
                    
                trimap = np.full(raw_mask.shape, 0.5, dtype=np.float64) # 0.5 == Unknown
                trimap[eroded_fg] = 1.0
                trimap[eroded_bg] = 0.0
                
                # 3. Mathematical Alpha Matting
                rgb_normalized = original_rgb.astype(np.float64) / 255.0
                
                # The patched ichol solver inherently handles the flat-color rank deficiency here
                true_alpha = estimate_alpha_cf(
                    rgb_normalized, 
                    trimap, 
                    laplacian_kwargs={"epsilon": 1e-6}
                )
                
                # 4. Spatial Color Decontamination (Foreground Un-premultiplication)
                true_foreground = estimate_foreground_ml(
                    rgb_normalized, 
                    true_alpha,
                    regularization=1e-3
                )
                
        finally:
            # 5. Safely Restore the MCP JSON-RPC Stream and unpatch
            sys.stdout.flush()
            sys.stderr.flush()
            
            os.dup2(saved_stdout_fd, stdout_fd)
            os.dup2(saved_stderr_fd, stderr_fd)
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)
            os.close(devnull)
            
            pym_prec.ichol = original_ichol
            if hasattr(acf, 'ichol'): acf.ichol = original_ichol
            if hasattr(fml, 'ichol'): fml.ichol = original_ichol
        
        # 6. Recombine un-premultiplied RGB with the mathematically perfect Alpha
        clean_rgb = np.clip(true_foreground * 255.0, 0, 255).astype(np.uint8)
        clean_alpha = np.clip(true_alpha * 255.0, 0, 255).astype(np.uint8)
        final_rgba = np.dstack((clean_rgb, clean_alpha))
        
        return Image.fromarray(final_rgba, "RGBA")

# Multi-model engine cache — keeps both 2d and 3d weights hot in RAM
global_matting_engines = {}

@mcp.tool()
def remove_background(image: str, model: str = "2d", fg_threshold: int = 245, bg_threshold: int = 10, erode_size: int = 15) -> str:
    """Uses Advanced SOTA Dichotomous Image Segmentation (DIS) + Laplacian Matting to natively extract backgrounds.
    Perfectly preserves smoke, gradients, and soft topological artifacts.
    
    Args:
         image: Absolute file path OR pure Base64 encoded PNG/JPG string representing the input image.
         model: '2d' for isnet-anime (cel-shaded NFTs), '3d' for isnet-general-use (photorealistic renders).
         fg_threshold: Foreground alpha threshold (200-255). Higher = stricter core, preserves more smoke. Default 245.
         bg_threshold: Background alpha threshold (1-50). Lower = protects faint atmospheric haze. Default 10.
         erode_size: Trimap erosion kernel size (5-25). Larger = wider gradient calculation band. Default 15.
    """
    import base64
    from io import BytesIO
    from PIL import Image
    import time
    import json
    from pathlib import Path
    global global_matting_engines

    try:
        logger.info(f"[PFP EXTRACTOR] Waking Sub-Pixel Segmentation Graph (model={model}, fg={fg_threshold}, bg={bg_threshold}, erode={erode_size})...")
        
        # Lazy initialization per model type
        if model not in global_matting_engines:
            logger.info(f"[PFP EXTRACTOR] Booting {model} weights into RAM via ONNXRuntime...")
            global_matting_engines[model] = DeepMattingPipeline(nft_style=model)
        engine = global_matting_engines[model]
        
        # Parse payload: local path vs raw base64 string
        if len(image) < 1000 and Path(image).exists() and Path(image).is_file():
            input_image = Image.open(image).convert("RGBA")
        else:
            img_data = base64.b64decode(image)
            input_image = Image.open(BytesIO(img_data)).convert("RGBA")

        # Strip Background utilizing spatial math
        logger.info("[PFP EXTRACTOR] Calculating spatial color affinities across alpha channel...")
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            output_image = engine.extract(input_image, fg_threshold=fg_threshold, bg_threshold=bg_threshold, erode_size=erode_size)
        
        # Save output to Memes directory
        out_name = f"pfp_cutout_pro_{int(time.time())}.png"
        output_path = Path.home() / "Documents" / "Meme Merchants" / out_name
        output_image.save(output_path, format="PNG")
        
        # Encode back to base64 for pure memory bridging to the UI layout
        buffered = BytesIO()
        output_image.save(buffered, format="PNG")
        b64_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
        
        logger.info(f"[PFP EXTRACTOR] Decontamination Complete: {output_path}")
        return json.dumps({
            "status": "success",
            "message": f"Background organically stripped using DIS Alpha Matting.",
            "path": str(output_path),
            "base64": b64_str
        })
    except Exception as e:
        logger.error(f"[PFP EXTRACTOR] Hardware Fault: {str(e)}")
        import traceback
        traceback.print_exc()
        return json.dumps({"error": str(e)})


# ==============================================================================
# THE COUNCIL — Multi-Agent Resonance Engine
# Migrated from scripts/council.py into a first-class MCP tool.
# ==============================================================================

SOULS_DIR = Path.home() / "Documents" / "Meme Merchants" / "hashlips_art_engine" / "build_undesirables_v2" / "souls"

def _load_council_agent(token_id):
    """Load SOUL.md for a given token ID and extract identity + Big Five scores."""
    soul_path = SOULS_DIR / str(token_id).zfill(4) / "SOUL.md"
    if not soul_path.exists():
        return None
    
    soul = soul_path.read_text()
    name_match = re.search(r'# IDENTITY: (.*)', soul)
    name = name_match.group(1).strip() if name_match else f"Undesirable #{token_id}"
    
    scores = {}
    for trait in ["Openness", "Extraversion", "Agreeableness", "Neuroticism", "Conscientiousness"]:
        m = re.search(f'- \\*\\*{trait}\\*\\*: (\\d+)%', soul)
        scores[trait] = int(m.group(1)) if m else 50
    
    return {"id": token_id, "name": name, "scores": scores, "prompt": soul}

def _assign_council_roles(agents):
    """Assign debate roles based on Big Five psychology. Returns (proposer, risk_mgr, executor)."""
    proposer = max(agents, key=lambda a: a['scores']['Openness'])
    remaining = [a for a in agents if a['id'] != proposer['id']]
    risk_mgr = max(remaining, key=lambda a: a['scores']['Neuroticism']) if remaining else proposer
    remaining = [a for a in remaining if a['id'] != risk_mgr['id']]
    executor = max(remaining, key=lambda a: a['scores']['Conscientiousness']) if remaining else proposer
    return proposer, risk_mgr, executor

def _ollama_generate(system_prompt, task, model="gemma3:4b"):
    """Single synchronous Ollama inference call."""
    try:
        r = requests.post("http://localhost:11434/api/generate", json={
            "model": model,
            "prompt": f"{system_prompt}\n\nTASK:\n{task}\n\nRespond strictly in character. Keep it under 200 words.",
            "stream": False
        }, timeout=120)
        if r.status_code == 200:
            return r.json().get("response", "").strip()
        return f"[Error: Ollama returned {r.status_code}]"
    except Exception as e:
        return f"[Connection Error: {e}]"


@mcp.tool()
def invoke_council(topic: str, token_ids: str = "") -> str:
    """Convenes 3 Undesirable agents to debate a topic using multi-agent resonance.
    The Council assigns roles based on Big Five psychology: Proposer (highest Openness),
    Risk Manager (highest Neuroticism), and Executor (highest Conscientiousness).
    
    Args:
        topic: The statement, theory, or market thesis to debate.
        token_ids: Comma-separated token IDs for the 3 debaters (e.g. '420,69,1337').
                   If fewer than 3 are provided, random souls fill the remaining slots.
    """
    import re
    import random
    
    logger.info(f"[COUNCIL] Convening council on: {topic}")
    
    # Parse provided token IDs
    ids = []
    if token_ids.strip():
        ids = [int(x.strip()) for x in token_ids.split(',') if x.strip().isdigit()]
    
    # Fill remaining slots with random souls
    if len(ids) < 3 and SOULS_DIR.exists():
        all_souls = [int(d.name) for d in SOULS_DIR.iterdir() if d.is_dir() and d.name.isdigit()]
        available = [s for s in all_souls if s not in ids]
        random.shuffle(available)
        while len(ids) < 3 and available:
            ids.append(available.pop())
    
    if len(ids) < 3:
        return json.dumps({"error": "Council requires 3 agents. Not enough soul workspaces found."})
    
    # Load agents
    agents = []
    for tid in ids[:3]:
        agent = _load_council_agent(tid)
        if agent:
            agents.append(agent)
        else:
            return json.dumps({"error": f"Soul #{tid} not found at {SOULS_DIR / str(tid).zfill(4)}"})
    
    # Assign roles
    proposer, risk_mgr, executor = _assign_council_roles(agents)
    logger.info(f"[COUNCIL] Proposer: {proposer['name']} (O:{proposer['scores']['Openness']}%) | Risk: {risk_mgr['name']} (N:{risk_mgr['scores']['Neuroticism']}%) | Executor: {executor['name']} (C:{executor['scores']['Conscientiousness']}%)")
    
    # Phase 1: THE SIGNAL
    task_1 = f"Topic for debate:\n\"{topic}\"\n\nProvide your opening argument or thesis on this topic. Be opinionated and stay true to your personality."
    proposal = _ollama_generate(proposer['prompt'], task_1)
    
    # Phase 2: THE CRITIQUE
    task_2 = f"Review this argument from {proposer['name']}:\n\n\"{proposal}\"\n\nCritique this position. What are the flaws, risks, and blind spots? Give a GO or NO GO recommendation."
    critique = _ollama_generate(risk_mgr['prompt'], task_2)
    
    # Phase 3: THE VERDICT
    task_3 = f"The Proposer ({proposer['name']}) argued:\n\"{proposal}\"\n\nThe Risk Manager ({risk_mgr['name']}) responded:\n\"{critique}\"\n\nYou are the Executor. Synthesize both positions and deliver a final verdict. Include a conviction score (0-100) and a clear GO or NO GO decision."
    verdict = _ollama_generate(executor['prompt'], task_3)
    
    result = {
        "status": "success",
        "topic": topic,
        "phases": [
            {"role": "proposer", "emoji": "🗣️", "agent_name": proposer['name'], "agent_id": proposer['id'], "openness": proposer['scores']['Openness'], "content": proposal},
            {"role": "risk_manager", "emoji": "🛡️", "agent_name": risk_mgr['name'], "agent_id": risk_mgr['id'], "neuroticism": risk_mgr['scores']['Neuroticism'], "content": critique},
            {"role": "executor", "emoji": "⚖️", "agent_name": executor['name'], "agent_id": executor['id'], "conscientiousness": executor['scores']['Conscientiousness'], "content": verdict}
        ]
    }
    
    logger.info(f"[COUNCIL] Debate complete. 3 phases executed.")
    return json.dumps(result)


import cv2
import numpy as np
from PIL import Image
import io
import re

def auto_crop_card(image_path):
    """Uses OpenCV to detect the card boundary and crop the background, returning a PIL Image in memory."""
    try:
        import cv2
        img = cv2.imread(image_path)
        if img is None: 
            return Image.open(image_path)
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 50, 150)
        
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours: 
            return Image.open(image_path)
            
        c = max(contours, key=cv2.contourArea)
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        
        x, y, w, h = cv2.boundingRect(approx)
        
        # Ensure it's roughly card-shaped to avoid cropping weird artifacts
        # Limit memory bounds by restricting to reasonable boundaries
        if w > 100 and h > 100:
            cropped = img[y:y+h, x:x+w]
            # Convert BGR to RGB natively in RAM
            rgb_cropped = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)
            return Image.fromarray(rgb_cropped)
            
    except Exception as e:
        logger.error(f"Crop failed: {e}")
        
    return Image.open(image_path)


def measure_centering(image_path):
    """Programmatic centering measurement using OpenCV edge detection.
    
    Detects the card's printed border region and calculates exact L/R and T/B
    pixel ratios. Returns centering data or None if detection fails.
    
    PSA Centering Thresholds:
        Gem Mint 10: 55/45 or better on front
        Mint 9:      60/40 or better
        NM-MT 8:     65/35 or better  
        NM 7:        70/30 or better
        EX-MT 6:     75/25 or better
    """
    try:
        img = cv2.imread(image_path)
        if img is None:
            return None
        
        h, w = img.shape[:2]
        
        # Convert to grayscale and apply adaptive threshold to isolate the
        # card's inner artwork boundary from the printed border
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Use Otsu's threshold to find the artwork/border boundary
        _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Find contours — the largest internal contour is typically the artwork box
        contours, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        
        if len(contours) < 2:
            return None
        
        # Sort by area, skip the outermost (card edge), take the next largest (artwork box)
        sorted_contours = sorted(contours, key=cv2.contourArea, reverse=True)
        
        # The artwork box is typically the 2nd or 3rd largest contour
        artwork_contour = None
        card_area = w * h
        for c in sorted_contours[1:5]:  # Check top 4 internal contours
            area = cv2.contourArea(c)
            # Artwork box is typically 30-80% of card area
            if 0.20 * card_area < area < 0.85 * card_area:
                artwork_contour = c
                break
        
        if artwork_contour is None:
            return None
        
        # Get bounding box of the artwork region
        ax, ay, aw, ah = cv2.boundingRect(artwork_contour)
        
        # Calculate border widths (pixels)
        border_left = ax
        border_right = w - (ax + aw)
        border_top = ay
        border_bottom = h - (ay + ah)
        
        # Avoid division by zero
        lr_total = border_left + border_right
        tb_total = border_top + border_bottom
        
        if lr_total < 4 or tb_total < 4:
            return None
        
        # Calculate ratios (always expressed as larger/smaller)
        lr_left_pct = round((border_left / lr_total) * 100, 1)
        lr_right_pct = round((border_right / lr_total) * 100, 1)
        tb_top_pct = round((border_top / tb_total) * 100, 1)
        tb_bottom_pct = round((border_bottom / tb_total) * 100, 1)
        
        # The "worse" axis determines the centering grade
        lr_ratio = max(lr_left_pct, lr_right_pct)
        tb_ratio = max(tb_top_pct, tb_bottom_pct)
        worst_ratio = max(lr_ratio, tb_ratio)
        
        # Map worst ratio to a PSA-calibrated centering score
        if worst_ratio <= 55:
            centering_score = 10.0
        elif worst_ratio <= 58:
            centering_score = 9.5
        elif worst_ratio <= 60:
            centering_score = 9.0
        elif worst_ratio <= 63:
            centering_score = 8.5
        elif worst_ratio <= 65:
            centering_score = 8.0
        elif worst_ratio <= 68:
            centering_score = 7.5
        elif worst_ratio <= 70:
            centering_score = 7.0
        elif worst_ratio <= 75:
            centering_score = 6.0
        elif worst_ratio <= 80:
            centering_score = 5.0
        else:
            centering_score = 4.0
        
        return {
            "centering_score": centering_score,
            "left_right": f"{lr_left_pct}/{lr_right_pct}",
            "top_bottom": f"{tb_top_pct}/{tb_bottom_pct}",
            "worst_axis_ratio": worst_ratio,
            "border_pixels": {
                "left": border_left, "right": border_right,
                "top": border_top, "bottom": border_bottom
            },
            "method": "opencv_programmatic"
        }
        
    except Exception as e:
        logger.warning(f"[TCG] OpenCV centering measurement failed: {e}")
        return None


def apply_bgs_cap(centering, corners, edges, surface):
    """Emulate BGS professional capping algorithm.
    
    BGS rules (reverse-engineered from community data):
    1. Final grade can NEVER exceed second-lowest subgrade + 0.5
    2. Final grade can NEVER exceed lowest subgrade + 1.0  
    3. Structural scores (Corners, Edges) penalize harder than alignment (Centering)
    4. Result rounded to nearest 0.5
    
    Returns: (capped_grade, cap_applied, details)
    """
    scores = sorted([centering, corners, edges, surface])
    lowest = scores[0]
    second_lowest = scores[1]
    
    # Mathematical average
    avg = sum(scores) / 4
    
    # Cap 1: Cannot exceed second-lowest + 0.5
    cap_a = second_lowest + 0.5
    
    # Cap 2: Cannot exceed lowest + 1.0
    cap_b = lowest + 1.0
    
    # Final grade is the minimum of all three
    raw_final = min(avg, cap_a, cap_b)
    
    # Round to nearest 0.5
    capped_grade = round(raw_final * 2) / 2
    
    # Clamp to valid PSA range
    capped_grade = max(1.0, min(10.0, capped_grade))
    
    cap_applied = capped_grade < round(avg * 2) / 2
    
    return capped_grade, cap_applied, {
        "mathematical_average": round(avg, 2),
        "second_lowest_cap": cap_a,
        "lowest_cap": cap_b,
        "cap_was_applied": cap_applied,
        "subgrades_sorted": scores
    }

@mcp.tool()
def grade_tcg_card(card_image_paths: str, card_name: str = "Unknown Card") -> str:
    """Analyze a Trading Card (Pokémon, Magic, etc) for PSA/Beckett grading using a local Vision AI.
    
    Args:
        card_image_paths: A JSON string array of absolute paths to the dropped card images (e.g. '["/path/1.png", "/path/2.png"]').
        card_name: Name of the card being graded (e.g. 'Base Set Charizard')
    """
    import os
    import base64
    import requests
    import json
    
    try:
        paths = json.loads(card_image_paths)
        if not isinstance(paths, list):
            paths = [card_image_paths] # Fallback if they just passed a single raw string
    except json.JSONDecodeError:
        paths = [card_image_paths]
        
    b64_images = []
    
    for raw_p in paths:
        # Detect if the path is actually an eBay (or internet) remote image URL
        if raw_p.startswith("http://") or raw_p.startswith("https://"):
            try:
                # Browser-like headers to bypass CDN bot protection (eBay, pokemon.com, etc.)
                _img_headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": raw_p.split("/")[0] + "//" + raw_p.split("/")[2] + "/",
                }

                # TCGPlayer CDN uses Cloudflare JS challenges — try alternate URL patterns
                _urls_to_try = [raw_p]
                if "tcgplayer" in raw_p.lower():
                    import re
                    # Try without size suffix: product/489027_200w.jpg → product/489027.jpg
                    no_size = re.sub(r'_\d+w\.', '.', raw_p)
                    if no_size != raw_p:
                        _urls_to_try.append(no_size)
                    # Try the product image CDN with different subdomain
                    alt = raw_p.replace("tcgplayer-cdn.tcgplayer.com", "product-images.tcgplayer.com")
                    if alt != raw_p:
                        _urls_to_try.append(alt)

                _downloaded = False
                for _try_url in _urls_to_try:
                    try:
                        img_res = requests.get(_try_url, headers=_img_headers, timeout=15)
                        img_res.raise_for_status()
                        from PIL import Image
                        import io
                        img = Image.open(io.BytesIO(img_res.content)).convert("RGB")
                        buffered = io.BytesIO()
                        img.save(buffered, format="JPEG", quality=85)
                        b64_images.append(base64.b64encode(buffered.getvalue()).decode("utf-8"))
                        _downloaded = True
                        break
                    except Exception:
                        continue

                if _downloaded:
                    continue

                # All URL attempts failed
                raise requests.exceptions.HTTPError(f"All URL patterns returned errors (Cloudflare protected)")
            except Exception as e:
                logger.warning(f"[TCG] Failed to download remote image {raw_p}: {e}")
                if "tcgplayer" in raw_p.lower():
                    _err = (f"TCGPlayer CDN blocked this request (Cloudflare protection). "
                            f"To grade a TCGPlayer card: right-click the image on tcgplayer.com, "
                            f"select 'Copy Image Address', then paste that URL. Or save the image "
                            f"locally and provide the file path instead.")
                else:
                    _err = f"Failed to download image from {raw_p}: {str(e)}. Try saving the image locally and providing the file path."
                if len(paths) == 1:
                    return json.dumps({"error": _err})
                continue

        # Normal Local File Pipeline
        p = os.path.expanduser(raw_p)
        if not os.path.exists(p):
            return json.dumps({"error": f"Image file not found at {p}"})
        
        try:
            from PIL import Image, ExifTags
            import io
            
            ext = os.path.splitext(p)[1].lower()
            
            # --- Video Extraction Pipeline (For Holo Captures) ---
            if ext in ['.mp4', '.webm', '.mov']:
                try:
                    import cv2
                    vidcap = cv2.VideoCapture(p)
                    total_frames = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT))
                    frames_to_extract = 3 # 1st, middle, and end frames
                    interval = max(1, total_frames // frames_to_extract)
                    
                    for i in range(frames_to_extract):
                        vidcap.set(cv2.CAP_PROP_POS_FRAMES, min(i * interval, total_frames - 1))
                        success, cv_img = vidcap.read()
                        if success:
                            rgb_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                            pil_img = Image.fromarray(rgb_img)
                            
                            import tempfile
                            fd, temp_norm = tempfile.mkstemp(suffix=".jpg")
                            pil_img.save(temp_norm, format="JPEG")
                            os.close(fd)
                            
                            cr_img = auto_crop_card(temp_norm)
                            
                            MAX_DIM = 1024
                            w, h = cr_img.size
                            if max(w, h) > MAX_DIM:
                                ratio = MAX_DIM / max(w, h)
                                cr_img = cr_img.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)
                                
                            buffered = io.BytesIO()
                            cr_img.save(buffered, format="JPEG", quality=85)
                            b64_images.append(base64.b64encode(buffered.getvalue()).decode('utf-8'))
                            os.remove(temp_norm)
                    
                    vidcap.release()
                except Exception as e:
                    return json.dumps({"error": f"Video processing failed. Ensure opencv-python is installed. ({str(e)})"})
                continue
            
            # --- Image Processing Pipeline ---
            p = os.path.expanduser(p)
            if ext in ['.heic', '.heif']:
                try:
                    import pillow_heif
                    heif_file = pillow_heif.read_heif(p)
                    image = Image.frombytes(heif_file.mode, heif_file.size, heif_file.data, "raw")
                except ImportError:
                    return json.dumps({"error": "iPhone HEIC Image format detected, but 'pillow-heif' optical dependency is not installed. Please run `pip install pillow-heif` in your terminal to enable iOS uploads, or convert the file to .JPG."})
            else:
                image = Image.open(p)
            
            # Auto-orient from EXIF (iPhone photos are often rotated)
            try:
                for orientation in ExifTags.TAGS.keys():
                    if ExifTags.TAGS[orientation] == 'Orientation':
                        break
                exif = image._getexif()
                if exif and orientation in exif:
                    if exif[orientation] == 3: image = image.rotate(180, expand=True)
                    elif exif[orientation] == 6: image = image.rotate(270, expand=True)
                    elif exif[orientation] == 8: image = image.rotate(90, expand=True)
            except (AttributeError, KeyError, TypeError):
                pass
            
            # Save normalized image to a temp file, crop it with OpenCV
            import tempfile
            fd, temp_normalized = tempfile.mkstemp(suffix=".jpg")
            try:
                if image.mode in ('RGBA', 'P', 'LA'):
                    image = image.convert('RGB')
                image.save(temp_normalized, format="JPEG")
                os.close(fd)
                
                cropped_image = auto_crop_card(temp_normalized)
                
                # Resize to max 1024px longest edge
                MAX_DIM = 1024
                w, h = cropped_image.size
                if max(w, h) > MAX_DIM:
                    ratio = MAX_DIM / max(w, h)
                    cropped_image = cropped_image.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)
                
                buffered = io.BytesIO()
                cropped_image.save(buffered, format="JPEG", quality=85)
                b64_images.append(base64.b64encode(buffered.getvalue()).decode('utf-8'))
                
                logger.info(f"[TCG] Preprocessed and Cropped {os.path.basename(p)}: {w}x{h} → {cropped_image.size[0]}x{cropped_image.size[1]}")
                
            finally:
                if os.path.exists(temp_normalized):
                    os.remove(temp_normalized)
            
        except Exception as e:
            return json.dumps({"error": f"Failed to process image {p}: {e}"})
    
    # Vision models work best with single images — grade the primary card image
    primary_image = b64_images[0]
        
    # --- RAG: TCG Market Depth & Merton Jump-Diffusion Pre-loading ---
    market_context = "No live TCGCSV price history found in SQLite memory array."
    mu_override = "null"
    sigma_override = "null"
    
    try:
        import tcg_oracle
        vol = tcg_oracle.get_historical_volatility(card_name)
        if vol and "error" not in vol:
            mu_override = str(vol['mu_annual'])
            sigma_override = str(vol['sigma_annual'])
            market_context = f"Empirical Merton Data: {vol['data_points']} documented sales. Volatility (sigma) = {vol['sigma_annual']}, Drift (mu) = {vol['mu_annual']}. Last traded price: ${vol['last_price']}."
        
        # [EBAY API SANDBOX HOOK]
        try:
            import ebay_oracle
            depth = ebay_oracle.get_market_depth(card_name, limit=5)
            if depth and depth.get("market_depth"):
                spread = depth["market_depth"].get("price_range", {})
                ebay_context = (
                    f"\neBay Market Depth: Found {depth['listings_found']} live listings. "
                    f"Volatility Proxy = {depth['market_depth']['volatility']}, "
                    f"Avg Price: ${depth['market_depth']['avg_listing_price']}, "
                    f"Spread: ${spread.get('low')} - ${spread.get('high')}."
                )
                market_context += ebay_context
        except Exception as e_ebay:
            logger.warning(f"Could not hook into eBay market depth: {e_ebay}")
            
    except Exception as e:
        logger.warning(f"Could not RAG TCGCSV cache: {e}")

    system_prompt = f"""You are an EXTREMELY STRICT and BRUTALLY CRITICAL PSA/Beckett Card Authenticator.
    You grade TCG cards (Pokémon, Magic, Yu-Gi-Oh!) AND Sports Cards (Basketball, Baseball, Football, Hockey).
    You are analyzing {len(b64_images)} image(s) of: {card_name}.
    
    MARKET CONTEXT (RAG MEMORY):
    {market_context}
    
    === CRITICAL STANCE (READ THIS CAREFULLY) ===
    You MUST grade like a REAL PSA grader who has rejected thousands of cards. Start at 10 and DEDUCT for every flaw.
    
    STATISTICAL REALITY:
    - PSA 10: Given to LESS THAN 3% of submissions. Requires lab-quality photos to even consider.
    - PSA 9: Given to ~12%. Still extremely rare. Requires near-perfect card with ONE microscopic flaw.
    - PSA 8: ~20%. This is already a VERY NICE card. Most "good-looking" cards land here.
    - PSA 7: ~25%. This is a SOLID card. Most cards that look "fine" to untrained eyes grade 6-7.
    - PSA 4-6: ~30%. The silent majority. Cards people THINK are "mint" but have hidden wear.
    - PSA 1-3: ~10%. Obvious damage visible to anyone.
    
    PHONE PHOTO PENALTY (NON-NEGOTIABLE):
    If the image is clearly taken with a phone (not a flatbed scanner or macro lens), you MUST:
    - Deduct AT LEAST 2 full points from Surface (phone cameras CANNOT capture micro-scratches, print lines, or roller marks)
    - Deduct AT LEAST 1 point from Edges (phone lighting hides hairline whitening)
    - Note in your analysis: "Phone photo quality — hidden defects assumed"
    
    A card photographed with a phone should NEVER receive higher than PSA 7 for Surface unless the card is visibly perfect AND the photo is extremely high resolution.
    
    === MANDATORY DEFECT CHECKLIST (Check EVERY item) ===
    □ CENTERING: Measure border thickness on all 4 sides. Even 55/45 is a deduction. 60/40 = PSA 8 max.
    □ CORNERS: Zoom into ALL 4 corners. Any softness, rounding, or whitening = -1 to -3 points.
    □ EDGES: Check ALL 4 edges for whitening, chipping, peeling, or silvering. Even hairline whitening = deduction.
    □ SURFACE: Look for print lines, scratches (even micro), haze, dents, ink spots, roller marks.
    □ PRINT QUALITY: Check for miscuts, ink bleed, dot patterns, color fading.
    □ HOLO SCRATCHES: If holographic, assume micro-scratches exist (they almost always do).
    □ BACK DAMAGE: The back matters as much as the front. Most people forget to check it.
    □ VINTAGE TAX: Cards from 1999-2005 get higher centering penalties (factory QC was poor).
    
    === CALIBRATION (STRICT SCALE) ===
    PSA 10 (Gem Mint): Virtually impossible from phone photos. 55/45 centering or better. ZERO defects. PRISTINE.
    PSA 9 (Mint): 60/40 centering max. ONE microscopic flaw allowed. Still extremely rare.
    PSA 8 (NM-MT): 65/35 centering. 1-2 minor flaws (tiny edge whitening OR 1 soft corner). 
    PSA 7 (NM): 70/30 centering. Light edge wear, 1-2 soft corners, minor surface wear.
    PSA 6 (EX-MT): Off-center. Visible edge wear on 2+ edges. Light creasing acceptable.
    PSA 5 (EX): Obvious wear. Multiple soft corners, noticeable scratches, moderate edge wear.
    PSA 4 (VG-EX): Heavy wear visible. Corner damage, edge peeling, surface scuffs.
    PSA 3 (VG): Significant damage. Creases, heavy wear, rounded corners.
    PSA 2-1: Severely damaged. Only for valuable vintage cards.

    === INSTRUCTIONS ===
    STEP 1: Write a BRUTALLY HONEST condition report inside <analysis> tags. For each of the 4 categories, describe EVERY flaw you see AND flaws you suspect exist but can't confirm from the photo quality. Be a harsh critic — your reputation depends on accuracy.
    
    STEP 2: Output EXACTLY ONE JSON with your grades. Remember: most cards grade 5-7. If you're giving 8+, you better have a damn good reason and the card better look absolutely pristine.
    
    <analysis>
    Front: Left border ~55% thicker than right (roughly 60/40). Top-to-bottom centering appears 55/45.
    Corners: Top-right shows minor softness under magnification. Bottom-left has faint whitening dot.
    Edges: Bottom edge shows hairline whitening consistent with being pulled from a pack.  
    Surface: Phone photo quality — cannot confirm absence of micro-scratches. Deducting for uncertainty. Slight haze visible on holo area.
    Back: Blue borders appear consistent but bottom edge shows faint wear line.
    </analysis>
    ```json
    {{
      "status": "success",
      "report": {{
        "card_identified": "READ THE IMAGE. Output exact player name/character and set name here (e.g. '1998 Larry Hughes Base'). DO NOT output '{card_name}' if you can physically read the name.",
        "market_physics": {{
           "mu_driven": {mu_override},
           "sigma_driven": {sigma_override}
        }},
        "centering": {{ "score": 7, "notes": "60/40 L/R, 55/45 T/B. Costs it dearly." }},
        "edges": {{ "score": 6.5, "notes": "Hairline whitening bottom edge, faint wear line on back." }},
        "corners": {{ "score": 7, "notes": "Top-right softness, bottom-left micro whitening." }},
        "surface": {{ "score": 6, "notes": "Phone photo penalty. Holo haze detected. Cannot confirm scratch-free." }},
        "overall_grade": 6.5,
        "confidence_score": 78,
        "verdict": "EX-MT to NM range. Centering and surface uncertainty hold it back. Would benefit from macro photography.",
        "raw_analysis": "<the exact text you wrote in the analysis block above>"
      }}
    }}
    ```
    """
    
    payload = {
        "model": "qwen2.5vl:7b",
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": "Analyze the card, provide your <analysis>, and output the JSON.",
                "images": [primary_image]
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 1024
        }
    }
    
    try:
        response = requests.post("http://localhost:11434/api/chat", json=payload, timeout=120)
        if response.status_code == 404:
            return json.dumps({
                "status": "error",
                "error": "The `qwen2.5vl:7b` optical model is still downloading.",
                "action": "Tell the user patiently that their optical engine is autonomously deploying in the background, and to wait 1-2 minutes before trying to grade again."
            })
            
        data = response.json()
        ai_response = data.get("message", {}).get("content", "")
        
        # Extract Analysis and JSON safely
        analysis_match = re.search(r'<analysis>([\s\S]*?)</analysis>', ai_response, re.IGNORECASE)
        json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', ai_response, re.IGNORECASE)
        
        # Fallback if the model forgot markdown ticks
        if not json_match:
            json_match = re.search(r'(\{[\s\S]*\})', ai_response)
            
        if json_match:
            try:
                # group(1) contains the payload for both regex patterns now
                parsed = json.loads(json_match.group(1))
                parsed["raw_analysis"] = analysis_match.group(1).strip() if analysis_match else "No visual analysis provided."
                
                # === POST-PROCESSING: BGS Capping + OpenCV Centering ===
                report = parsed.get("report", parsed)  # Handle nested or flat structure
                
                # Extract LLM subgrades
                llm_centering = float(report.get("centering", {}).get("score", 7)) if isinstance(report.get("centering"), dict) else 7
                llm_corners = float(report.get("corners", {}).get("score", 7)) if isinstance(report.get("corners"), dict) else 7
                llm_edges = float(report.get("edges", {}).get("score", 7)) if isinstance(report.get("edges"), dict) else 7
                llm_surface = float(report.get("surface", {}).get("score", 7)) if isinstance(report.get("surface"), dict) else 7
                
                # Override centering with OpenCV if measurement succeeded
                opencv_centering_data = None
                try:
                    # Use the first image path for centering measurement
                    first_path = paths[0] if paths else None
                    if first_path and not first_path.startswith("http"):
                        opencv_centering_data = measure_centering(os.path.expanduser(first_path))
                except Exception:
                    pass
                
                if opencv_centering_data:
                    cv_score = opencv_centering_data["centering_score"]
                    # Use the more conservative (lower) of LLM and OpenCV scores
                    final_centering = min(llm_centering, cv_score)
                    
                    if isinstance(report.get("centering"), dict):
                        report["centering"]["score"] = final_centering
                        report["centering"]["opencv_override"] = opencv_centering_data["left_right"]
                        report["centering"]["opencv_tb"] = opencv_centering_data["top_bottom"]
                        report["centering"]["notes"] = (
                            f"OpenCV measured {opencv_centering_data['left_right']} L/R, "
                            f"{opencv_centering_data['top_bottom']} T/B. "
                            f"Worst axis: {opencv_centering_data['worst_axis_ratio']}%. "
                            f"{'LLM estimate used (more conservative).' if final_centering == llm_centering else 'OpenCV measurement applied.'}"
                        )
                    report["opencv_centering"] = opencv_centering_data
                    llm_centering = final_centering
                    logger.info(f"[TCG] OpenCV centering: {opencv_centering_data['left_right']} L/R → score {cv_score}")
                
                # Apply BGS professional capping algorithm
                capped_grade, cap_applied, cap_details = apply_bgs_cap(
                    llm_centering, llm_corners, llm_edges, llm_surface
                )
                
                report["overall_grade"] = capped_grade
                report["bgs_cap"] = cap_details
                if cap_applied:
                    report["cap_notice"] = (
                        f"Grade capped from {cap_details['mathematical_average']:.1f} → {capped_grade} "
                        f"by BGS second-lowest-subgrade rule (cap at {cap_details['second_lowest_cap']})."
                    )
                    logger.info(f"[TCG] BGS cap applied: avg {cap_details['mathematical_average']:.1f} → {capped_grade}")
                
                # === UNDSR SLAB GENERATION ===
                slab_base64 = None
                slab_path = None
                try:
                    from undsr_slab_renderer import render_slab_from_grade_result
                    # Use the first local image path for the slab card photo
                    first_local = None
                    for rp in paths:
                        if not rp.startswith("http"):
                            first_local = os.path.expanduser(rp)
                            break
                    
                    if first_local and os.path.exists(first_local):
                        grade_output = {"report": report}
                        slab_path = render_slab_from_grade_result(first_local, grade_output)
                        
                        if slab_path and os.path.exists(slab_path):
                            with open(slab_path, "rb") as sf:
                                slab_base64 = base64.b64encode(sf.read()).decode("utf-8")
                            logger.info(f"[TCG] UNDSR slab rendered: {slab_path}")
                    else:
                        logger.info("[TCG] No local image path for slab render (URL-only grading)")
                except ImportError:
                    logger.warning("[TCG] undsr_slab_renderer not found — skipping slab generation")
                except Exception as slab_err:
                    logger.warning(f"[TCG] Slab render failed (non-fatal): {slab_err}")
                
                result_payload = {"status": "success", "report": report}
                if slab_base64:
                    result_payload["slab_image_base64"] = slab_base64
                    result_payload["slab_image_path"] = slab_path
                
                return json.dumps(result_payload)
            except json.JSONDecodeError:
                pass
                
        return json.dumps({"status": "success", "raw_response": ai_response, "warning": "Vision model failed to format strictly as JSON."})
            
    except requests.exceptions.RequestException as e:
        return json.dumps({"error": f"Ollama connection failed: {e}"})

@mcp.tool()
def search_ebay_market(query: str, limit: int = 50, app_id: str = "", client_secret: str = "") -> str:
    """
    Query the live eBay Marketplace for collectibles, cards, and physical items.
    Provides current market listings, a synthetic 90-day price history,
    and a mathematically derived market volatility proxy (Spread-Variance).
    Use this for VeeFriends, Azuki TCG, Pudgy Penguins, or any cross-market TCG analysis.
    
    Args:
        query: Specific search term (e.g. "VeeFriends Series 2", "Pudgy Penguins Toy", "Rolex Submariner")
        limit: Max listings to analyze (default 50)
    """
    try:
        import ebay_oracle
        depth = ebay_oracle.get_market_depth(query, limit=limit, app_id=app_id, client_secret=client_secret)
        if not depth:
            return json.dumps({"error": f"No eBay listings found for '{query}'. Ensure API keys are valid."})
        
        # Automagically learn user preference based on search behavior
        try:
            # We wrap in try block so failures don't crash the search
            memory_save(
                category="user_preference", 
                content=f"User showed interest in the '{query}' market. Avg price is currently ${depth.get('market_depth', {}).get('avg_listing_price', 'Unknown')}.", 
                tags="ebay,market_interest,collectibles"
            )
        except Exception as m_err:
            logger.warning(f"Could not persist preference memory: {m_err}")
            
        return json.dumps(depth)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_skill(skill_name: str) -> str:
    """Load the full instructions for a specific skill.

    Args:
        skill_name: Name of the skill (e.g., 'business_pilot', 'meme_machine',
                    'market_analysis', 'content_creation', 'check_portfolio',
                    'image_generation', 'music_generation')
    """
    if skill_name in SKILLS:
        return SKILLS[skill_name]
    # Try fuzzy match
    for name in SKILLS:
        if skill_name.lower() in name.lower():
            return SKILLS[name]
    available = ", ".join(SKILLS.keys())
    return f"Skill '{skill_name}' not found. Available skills: {available}"


@mcp.tool()
def list_skills() -> str:
    """List all skills available to this Undesirable agent with their triggers."""
    if not SKILLS:
        return "No skills loaded."
    result = []
    for name, content in SKILLS.items():
        lines = content.strip().split("\n")
        title = lines[0].replace("# ", "") if lines else name
        # Find trigger line
        trigger = ""
        for line in lines[:10]:
            if line.startswith("**Trigger:**"):
                trigger = line.replace("**Trigger:**", "").strip()
                break
        result.append(f"• {title}\n  Trigger: {trigger}\n  File: skills/{name}.md")
    return "\n\n".join(result)


@mcp.tool()
def query_ollama(prompt: str, model: str = "llama3.1:8b") -> str:
    """Send a prompt to the local Ollama instance for inference.
    The agent's personality is automatically injected as system context.

    Args:
        prompt: The user's question or task
        model: Ollama model to use (default: llama3.1:8b)
    """
    import requests
    try:
        response = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT[:4000] if SYSTEM_PROMPT else "You are a helpful AI assistant."},
                    {"role": "user", "content": prompt}
                ],
                "stream": False
            },
            timeout=120
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("message", {}).get("content", "No response from Ollama.")
        return f"Ollama error: HTTP {response.status_code}"
    except requests.ConnectionError:
        return "❌ Ollama is not running. Start it with: ollama serve"
    except Exception as e:
        return f"Error querying Ollama: {str(e)}"


# System Hardware Abstraction Matrix
LOCAL_MODEL_MAC_MLX = "schnell"
LOCAL_MODEL_PC_CUDA = "shuttleai/FLUX.1-schnell"

def check_hardware_capabilities():
    """Returns True if local generation is physically possible (>12GB RAM)."""
    try:
        import os
        if hasattr(os, 'sysconf'):
            mem_bytes = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
            gb = mem_bytes / (1024.**3)
            return gb > 12.0
    except Exception:
        pass
    return True # Assume capable if unmeasurable

@mcp.tool()
def generate_meme(
    prompt: str, 
    seed: int = -1, 
    width: int = 512, 
    height: int = 512,
    overlay_image_path: str = "",
    top_text: str = "",
    bottom_text: str = "",
    font_style: str = "Impact",
    format_type: str = "meme",
    visual_style: str = "Default"
) -> str:
    """Generate a meme illustration locally. Automatically selects the best engine.
    - Apple Silicon: FLUX.2-klein via mflux (MLX acceleration)
    - NVIDIA GPU: FLUX.2-schnell via diffusers (CUDA)
    - Windows AMD/Intel: FLUX.2-schnell via diffusers (DirectML)
    - CPU fallback: Ollama vision model

    Args:
        prompt: Text description of the meme base background
        seed: Random seed for reproducibility (-1 for random)
        width: Image width in pixels (default 512)
        height: Image height in pixels (default 512)
        overlay_image_path: Absolute path to a transparent PNG (e.g. your PFP cutout) to layer on top
        top_text: Memetic text to draw at the top (impact font with stroke)
        bottom_text: Memetic text to draw at the bottom (impact font with stroke)
    """
    import base64
    import random
    import shutil
    import tempfile
    import urllib.parse
    import requests
    import os
    from PIL import Image, ImageDraw, ImageFont

    actual_seed = seed if seed >= 0 else random.randint(0, 999999)
    # Save renders OUTSIDE src-tauri to avoid triggering Tauri's file watcher rebuild
    output_dir = Path.home() / "Documents" / "Meme Merchants" / "renders"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{format_type}_{actual_seed}.png"

    # Enforce Banner Aspect Ratio locking (2:1 landscape)
    if format_type.lower() == "banner":
        width = 1024
        height = 512
        layout_directive = "wide cinematic landscape header banner layout, horizontal composition"
    else:
        layout_directive = "centered perfectly composed illustration"

    style_modifier = f"({visual_style} aesthetic style, striking visuals)" if visual_style != "Default" else "vibrant colors, clean composition"

    enhanced_prompt = (
        f"High quality digital art, {style_modifier}, {layout_directive}: {prompt}. "
        f"Absolutely NO text, NO words, NO letters, NO writing."
    )

    def apply_meme_compositing(base_path: str):
        if not os.path.exists(base_path): return
        try:
            img = Image.open(base_path).convert("RGBA")
            w, h = img.size
            draw = ImageDraw.Draw(img)
            
            # 1. Overlay Character Object
            if overlay_image_path:
                expanded_overlay_path = os.path.expanduser(overlay_image_path)
                if os.path.exists(expanded_overlay_path):
                    try:
                        char_img = Image.open(expanded_overlay_path).convert("RGBA")
                        # Scale character to fit 80% of canvas height
                        target_h = int(h * 0.8)
                        ratio = target_h / char_img.height
                        target_w = int(char_img.width * ratio)
                        char_img = char_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                        
                        # Bottom-center anchor
                        px = (w - target_w) // 2
                        py = h - target_h
                        img.paste(char_img, (px, py), mask=char_img)
                    except Exception as e:
                        logger.error(f"[MEME COMPOSITE] Error loading overlay: {e}")
                
            # 2. Apply Custom Impact Text
            def draw_meme_text(y_anchor, text, align_bottom=False):
                if not text: return
                text = text.upper()
                font_size = int(h * 0.16)
                
                # Dynamic Font Logic
                font_map = {
                    "Impact": ["/System/Library/Fonts/Supplemental/Impact.ttf", "/System/Library/Fonts/Impact.ttc", "C:/Windows/Fonts/impact.ttf"],
                    "Arial": ["/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"],
                    "Arial Black": ["/System/Library/Fonts/Supplemental/Arial Black.ttf", "C:/Windows/Fonts/ariblk.ttf"],
                    "Comic Sans": ["/System/Library/Fonts/Supplemental/Comic Sans MS.ttf", "/System/Library/Fonts/Supplemental/Comic Sans MS Bold.ttf", "C:/Windows/Fonts/comicbd.ttf"],
                    "Courier": ["/System/Library/Fonts/Courier.dfont", "/System/Library/Fonts/Supplemental/Courier New Bold.ttf", "C:/Windows/Fonts/courbd.ttf"],
                    "Georgia": ["/System/Library/Fonts/Supplemental/Georgia Bold.ttf", "C:/Windows/Fonts/georgiab.ttf"],
                    "Helvetica": ["/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/HelveticaNeue.ttc", "C:/Windows/Fonts/arial.ttf"],
                    "Futura": ["/System/Library/Fonts/Supplemental/Futura.ttc", "/System/Library/Fonts/Supplemental/Futura Bold.ttf"],
                    "Marker Felt": ["/System/Library/Fonts/Supplemental/Marker Felt.ttc", "/System/Library/Fonts/MarkerFelt.ttc"],
                    "Papyrus": ["/System/Library/Fonts/Supplemental/Papyrus.ttc", "C:/Windows/Fonts/PAPYRUS.TTF"],
                    "Gothic": ["/System/Library/Fonts/Supplemental/AppleGothic.ttf", "C:/Windows/Fonts/GOTHIC.TTF"],
                    "Chalkboard": ["/System/Library/Fonts/Supplemental/ChalkboardSE.ttc", "/System/Library/Fonts/ChalkboardSE.ttc"],
                    "Copperplate": ["/System/Library/Fonts/Supplemental/Copperplate.ttc"],
                    "Didot": ["/System/Library/Fonts/Supplemental/Didot.ttc"],
                }
                
                selected_font_path = None
                paths_to_check = font_map.get(font_style, font_map["Impact"])
                for p in paths_to_check:
                    if os.path.exists(p):
                        selected_font_path = p
                        break
                
                try:
                    if selected_font_path:
                        font = ImageFont.truetype(selected_font_path, font_size)
                    else:
                        font = ImageFont.load_default()
                except Exception:
                    font = ImageFont.load_default()
                    
                bbox = draw.textbbox((0,0), text, font=font)
                tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
                
                # Scale text down if it breaches canvas width
                while tw > w * 0.95 and font_size > 10:
                    font_size -= 2
                    try:
                        if selected_font_path: font = ImageFont.truetype(selected_font_path, font_size)
                        else: font = ImageFont.load_default()
                    except Exception:
                        break
                    bbox = draw.textbbox((0,0), text, font=font)
                    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
                    
                tx = (w - tw) // 2
                ty = y_anchor - th if align_bottom else y_anchor
                
                # Deep stroke
                stroke_width = max(2, int(font_size * 0.06))
                for ox in range(-stroke_width, stroke_width+1):
                    for oy in range(-stroke_width, stroke_width+1):
                        draw.text((tx+ox, ty+oy), text, font=font, fill="black")
                draw.text((tx, ty), text, font=font, fill="white")
                
            if top_text:    draw_meme_text(int(h * 0.02), top_text, align_bottom=False)
            if bottom_text: draw_meme_text(h - int(h * 0.05), bottom_text, align_bottom=True)

            # Flatten and save
            final_rgb = Image.new("RGB", img.size, (255,255,255))
            final_rgb.paste(img, mask=img.split()[3])
            final_rgb.save(base_path, format="PNG")
        except Exception as e:
            logger.error(f"[MEME COMPOSITE] error: {e}")

    # ── Shared Fallback: HuggingFace Inference API (free with token) ──
    def _generate_via_hf_inference(reason=""):
        logger.info(f"[IMAGE GEN] Routing to HuggingFace Inference API. Reason: {reason}")
        try:
            from huggingface_hub import InferenceClient, get_token
            hf_token = get_token()
            if not hf_token:
                return json.dumps({"error": "No HuggingFace token found. Run: python -c 'import huggingface_hub; huggingface_hub.login()'"})
            
            client = InferenceClient(token=hf_token)
            pil_img = client.text_to_image(
                enhanced_prompt,
                model="black-forest-labs/FLUX.1-schnell",
                width=width,
                height=height
            )
            pil_img.save(str(output_path))
            apply_meme_compositing(str(output_path))
            img_b64 = base64.b64encode(output_path.read_bytes()).decode('utf-8')
            return json.dumps({
                "status": "success", "engine": "huggingface_inference", "seed": actual_seed,
                "path": str(output_path), "base64": img_b64, "size": f"{width}x{height}",
                "note": reason
            })
        except Exception as e:
            logger.error(f"[IMAGE GEN] HF Inference failed: {e}")
            return json.dumps({"error": f"HuggingFace Inference API failed: {e}"})

    # ── Route 0: Hardware Diagnostic & Fallback ──
    if not check_hardware_capabilities():
        return _generate_via_hf_inference("Hardware insufficient for local FLUX.")

    # ── Route 1: Apple Silicon → mflux CLI ──
    if IS_APPLE_SILICON:
        # Check if the model is actually fully cached before attempting local generation
        model_cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / "models--black-forest-labs--FLUX.1-schnell"
        model_cached = False
        if model_cache_dir.exists():
            try:
                cache_size_gb = sum(f.stat().st_size for f in model_cache_dir.rglob('*') if f.is_file()) / (1024**3)
                model_cached = cache_size_gb > 20  # Full schnell model is ~23GB
                if not model_cached:
                    logger.warning(f"[IMAGE GEN] FLUX model only {cache_size_gb:.1f}GB / ~23GB cached.")
            except Exception:
                pass

        mflux_bin = shutil.which("mflux-generate")
        if not mflux_bin:
            venv_bin = Path(__file__).parent / ".venv" / "bin" / "mflux-generate"
            if venv_bin.exists():
                mflux_bin = str(venv_bin)

        if mflux_bin and model_cached:
            logger.info(f"[IMAGE GEN] Using mflux (Apple Silicon MLX) — model fully cached")
            try:
                cmd = [
                    mflux_bin, "--model", LOCAL_MODEL_MAC_MLX, "--quantize", "4",
                    "--steps", "4", "--seed", str(actual_seed),
                    "--width", str(width), "--height", str(height),
                    "--prompt", enhanced_prompt, "--output", str(output_path),
                ]
                # FIX: Backend Trace Severance Remediation
                # Replaced subprocess.run(capture_output=True, timeout=120) with Popen streaming.
                # subprocess.run with a hard timeout will SIGKILL the child process mid-download,
                # producing a violently truncated stdout buffer (the trailing '\\' artifact).
                # Popen reads the pipe line-by-line, keeping it alive for long inference tasks.
                import time as _time
                SOFT_TIMEOUT = 600  # 10 minutes — generous ceiling for local inference
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1  # Line-buffered
                )
                start_time = _time.time()
                output_lines = []
                while True:
                    line = proc.stdout.readline()
                    if not line and proc.poll() is not None:
                        break
                    if line:
                        output_lines.append(line.rstrip())
                        logger.debug(f"[mflux] {line.rstrip()}")
                    # Soft timeout: check elapsed time per line read
                    if _time.time() - start_time > SOFT_TIMEOUT:
                        proc.kill()
                        logger.error(f"[IMAGE GEN] mflux soft timeout exceeded ({SOFT_TIMEOUT}s)")
                        return json.dumps({"error": f"Image generation timed out ({SOFT_TIMEOUT}s). Process was streaming but exceeded ceiling."})
                
                returncode = proc.wait()
                if returncode == 0 and output_path.exists():
                    apply_meme_compositing(str(output_path))
                    img_b64 = base64.b64encode(output_path.read_bytes()).decode('utf-8')
                    return json.dumps({
                        "status": "success", "engine": "mflux", "seed": actual_seed,
                        "path": str(output_path), "base64": img_b64, "size": f"{width}x{height}"
                    })
                stderr_tail = '\n'.join(output_lines[-5:]) if output_lines else '(no output)'
                return json.dumps({"error": f"mflux failed (exit {returncode}): {stderr_tail[:300]}"})
            except subprocess.TimeoutExpired:
                return json.dumps({"error": "Image generation timed out (2 min)."})
            except Exception as e:
                return json.dumps({"error": str(e)})
        
        elif not model_cached:
            cached_gb = cache_size_gb if 'cache_size_gb' in dir() else 0
            return _generate_via_hf_inference(f"FLUX model only {cached_gb:.1f}GB / ~23GB cached. Using cloud until download completes.")

    # ── Route 2: Windows/Linux → diffusers (CUDA/DirectML/CPU) ──
    try:
        import torch
        from diffusers import FluxPipeline

        # Detect optimal device
        device = "cpu"
        dtype = torch.float32
        engine_name = "diffusers-cpu"

        if torch.cuda.is_available():
            device = "cuda"
            dtype = torch.float16
            engine_name = "diffusers-cuda"
            logger.info(f"[IMAGE GEN] Using CUDA ({torch.cuda.get_device_name(0)})")
        elif IS_WINDOWS:
            try:
                import torch_directml
                if torch_directml.is_available():
                    device = torch_directml.device()
                    dtype = torch.float16
                    engine_name = "diffusers-directml"
                    logger.info("[IMAGE GEN] Using DirectML (AMD/Intel)")
            except ImportError:
                logger.warning("[IMAGE GEN] DirectML not installed, falling back to CPU")
        elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            device = "mps"
            dtype = torch.float16
            engine_name = "diffusers-mps"

        if device == "cpu":
            logger.warning("[IMAGE GEN] No GPU detected. CPU generation will be slow (5-10 min).")

        logger.info(f"[IMAGE GEN] Loading {LOCAL_MODEL_PC_CUDA} on {device}")
        pipe = FluxPipeline.from_pretrained(
            LOCAL_MODEL_PC_CUDA,
            torch_dtype=dtype,
        )
        pipe = pipe.to(device)

        # Enable memory optimizations for constrained VRAM
        if device == "cuda":
            pipe.enable_model_cpu_offload()

        generator = torch.Generator(device="cpu").manual_seed(actual_seed)
        image = pipe(
            enhanced_prompt,
            width=width, height=height,
            num_inference_steps=4,
            generator=generator,
        ).images[0]

        image.save(str(output_path))
        
        apply_meme_compositing(str(output_path))
        img_b64 = base64.b64encode(output_path.read_bytes()).decode('utf-8')

        return json.dumps({
            "status": "success", "engine": engine_name, "seed": actual_seed,
            "path": str(output_path), "base64": img_b64, "size": f"{width}x{height}"
        })

    except ImportError:
        # diffusers not installed — provide install instructions
        if IS_WINDOWS:
            install_cmd = "pip install diffusers transformers accelerate torch-directml"
        elif IS_LINUX:
            install_cmd = "pip install diffusers transformers accelerate torch"
        else:
            install_cmd = "pip install mflux"

        return json.dumps({
            "error": f"Image generation engine not installed on {platform.system()}.",
            "install_cmd": install_cmd,
            "platform": platform.system(),
            "arch": platform.machine(),
            "help": "Run the install command above, then restart the MCP server."
        })
    except Exception as e:
        logger.error(f"[IMAGE GEN] Generation failed: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def produce_video(
    video_path: str,
    audio_path: str = "",
    use_custom_audio: bool = False,
    platform: str = "original",
    text_overlays: str = "[]",
    output_path: str = "",
    beat_sync_effects: str = "[]",
    target_duration: float = 0,
) -> str:
    """Produce a professional video with text overlays, optional audio replacement,
    and platform-specific scaling. Uses hardware-accelerated encoding.

    Args:
        video_path: Absolute path to the input video file
        audio_path: Absolute path to replacement audio file (optional)
        use_custom_audio: If true, replace video audio with the provided audio file
        platform: Target platform (tiktok, reels, shorts, feed, twitter, youtube, original)
        text_overlays: JSON array of overlays: [{"startTime":"0","endTime":"3","text":"HELLO","font":"Impact","size":48,"color":"#FFFFFF"}]
        output_path: Output file path (auto-generated if empty)
        beat_sync_effects: JSON array of effect IDs to trigger on beats, e.g. ["Flash","Glitch Beat"]
        target_duration: Target output duration in seconds (0 = use full source video)
    """
    global HW_ENCODER
    if HW_ENCODER is None:
        HW_ENCODER = get_hw_encoder()

    # Validate input video path against sandbox
    try:
        video_path = str(validate_secure_path(video_path))
    except ValueError as e:
        return json.dumps({"error": str(e)})

    video_file = Path(video_path)
    if not video_file.exists():
        return json.dumps({"error": f"Video file not found: {video_path}"})

    if output_path:
        output_path = str(validate_secure_path(output_path))
    else:
        output_path = str(video_file.parent / f"{video_file.stem}_{platform}_produced.mp4")

    # Parse text overlays
    try:
        overlays = json.loads(text_overlays) if isinstance(text_overlays, str) else text_overlays
    except json.JSONDecodeError:
        overlays = []

    # Build FFmpeg filter chain
    vf_filters = []

    # Platform scaling (PLATFORM_PRESETS defined below in this module)
    preset_map = {
        "tiktok": (1080, 1920), "reels": (1080, 1920), "shorts": (1080, 1920),
        "story": (1080, 1920), "feed": (1080, 1080), "twitter": (1280, 720),
        "youtube": (1920, 1080),
    }
    preset = preset_map.get(platform.lower()) if platform != "original" else None
    if preset:
        w, h = preset
        vf_filters.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")

    # === BEAT-REACTIVE EFFECTS ===
    # If beat_sync_effects are provided AND we have audio, detect beats and inject effect pulses
    try:
        beat_fx_list = json.loads(beat_sync_effects) if isinstance(beat_sync_effects, str) else beat_sync_effects
    except json.JSONDecodeError:
        beat_fx_list = []

    if beat_fx_list and audio_path and LIBROSA_AVAILABLE:
        try:
            import librosa
            y_audio, sr_audio = librosa.load(str(audio_path))
            _tempo, beat_frames = librosa.beat.beat_track(y=y_audio, sr=sr_audio)
            beat_times = librosa.frames_to_time(beat_frames, sr=sr_audio)
            # Cap at 50 beats for performance
            beat_times = beat_times[:50]
            logger.info(f"[BEAT FX] Detected {len(beat_times)} beats, applying effects: {beat_fx_list}")

            for bt in beat_times:
                bt = float(bt)
                for fx in beat_fx_list:
                    if fx == "Flash":
                        vf_filters.append(f"eq=brightness=0.4:enable='between(t,{bt},{bt}+0.08)'")
                    elif fx == "Zoom Pulse":
                        vf_filters.append(f"eq=contrast=1.5:brightness=0.15:eval=frame:enable='between(t,{bt},{bt}+0.15)'")
                    elif fx == "Shake":
                        vf_filters.append(f"crop=iw-20:ih-20:10+10*random(1):10+10*random(2):enable='between(t,{bt},{bt}+0.12)'")
                    elif fx == "Invert Beat":
                        vf_filters.append(f"lutrgb='r=negval:g=negval:b=negval':enable='between(t,{bt},{bt}+0.1)'")
                    elif fx == "Glitch Beat":
                        vf_filters.append(f"noise=alls=60:allf=t+u:enable='between(t,{bt},{bt}+0.13)'")
                    elif fx == "Saturation Pop":
                        vf_filters.append(f"eq=saturation=3.5:enable='between(t,{bt},{bt}+0.18)'")
                    elif fx == "Bass Blur":
                        vf_filters.append(f"boxblur=8:8:enable='between(t,{bt},{bt}+0.1)'")
                    elif fx == "Edge Glow":
                        vf_filters.append(f"edgedetect=mode=colormix:high=0:enable='between(t,{bt},{bt}+0.15)'")
                    elif fx == "VHS Hit":
                        vf_filters.append(f"noise=c0s=25:c0f=t+u:enable='between(t,{bt},{bt}+0.12)'")
                        vf_filters.append(f"eq=saturation=1.8:enable='between(t,{bt},{bt}+0.12)'")
        except Exception as beat_err:
            logger.warning(f"[BEAT FX] Beat detection failed, skipping: {beat_err}")

    # Text overlay and Visual Effect filters
    for ov in overlays:
        start = float(ov.get("startTime", 0))
        end = float(ov.get("endTime", 3))
        
        # 1. VISUAL EFFECTS using dynamic enabling (APPLIED REGARDLESS OF TEXT)
        effect = ov.get("effect", "None")
        if effect == "Pixelate":
            vf_filters.append(f"boxblur=min(h\\,w)/20:min(h\\,w)/20:enable='between(t,{start},{end})'")
        elif effect == "CRT Scanlines":
            vf_filters.append(f"drawgrid=width=iw:height=4:thickness=1:color=black@0.4:enable='between(t,{start},{end})'")
            vf_filters.append(f"colorchannelmixer=rr=0.9:gg=1.1:bb=0.9:enable='between(t,{start},{end})'")
        elif effect == "Invert":
            vf_filters.append(f"lutrgb='r=negval:g=negval:b=negval':enable='between(t,{start},{end})'")
        elif effect == "VHS Glitch":
            vf_filters.append(f"noise=c0s=12:c0f=t+u:enable='between(t,{start},{end})'")
            vf_filters.append(f"eq=saturation=1.5:enable='between(t,{start},{end})'")
        elif effect == "Color Strobe":
            vf_filters.append(f"eq=brightness='0.2*sin(t*15)':contrast='1+0.5*sin(t*15)':enable='between(t,{start},{end})'")
        elif effect == "Deep Fry":
            vf_filters.append(f"eq=saturation=3.5:contrast=2.0:gamma=1.5:enable='between(t,{start},{end})'")
            vf_filters.append(f"unsharp=5:5:1.5:5:5:0.0:enable='between(t,{start},{end})'")
        elif effect == "Night Vision":
            vf_filters.append(f"colorchannelmixer=rr=0:rg=2.0:rb=0:gr=0:gg=2.0:gb=0:br=0:bg=2.0:bb=0:enable='between(t,{start},{end})'")
            vf_filters.append(f"noise=alls=30:allf=t+u:enable='between(t,{start},{end})'")
        elif effect == "Neon Edge":
            vf_filters.append(f"edgedetect=mode=colormix:high=0:enable='between(t,{start},{end})'")
        elif effect == "Edge Detect":
            vf_filters.append(f"edgedetect=low=0.1:high=0.3:enable='between(t,{start},{end})'")
        elif effect == "Emboss":
            vf_filters.append(f"convolution='0 -1 0 -1 5 -1 0 -1 0:0 -1 0 -1 5 -1 0 -1 0:0 -1 0 -1 5 -1 0 -1 0:0 -1 0 -1 5 -1 0 -1 0':enable='between(t,{start},{end})'")
        elif effect == "Trippy Thermal":
            vf_filters.append(f"eq=saturation=4:contrast=1.8:enable='between(t,{start},{end})'")
            vf_filters.append(f"hue='h=t*60':enable='between(t,{start},{end})'")
        elif effect == "Gaussian Blur":
            vf_filters.append(f"boxblur=6:6:enable='between(t,{start},{end})'")
        elif effect == "Motion Blur":
            vf_filters.append(f"tblend=all_mode=average:enable='between(t,{start},{end})'")
        elif effect == "Chromatic Aberration":
            vf_filters.append(f"rgbashift=rh=-4:bh=4:enable='between(t,{start},{end})'")
        elif effect == "Kaleidoscope":
            vf_filters.append(f"hflip=enable='between(t,{start},{end})'")
            vf_filters.append(f"hue=h='t*30':enable='between(t,{start},{end})'")
        elif effect == "Sepia":
            vf_filters.append(f"colorchannelmixer=rr=0.393:rg=0.769:rb=0.189:gr=0.349:gg=0.686:gb=0.168:br=0.272:bg=0.534:bb=0.131:enable='between(t,{start},{end})'")

        # 2. TRANSITIONS — Use time-scoped brightness/effects (NOT global fade filters)
        # FFmpeg's `fade` filter is GLOBAL — it doesn't support enable= and stacks destructively
        # across scenes. Instead we use `eq=brightness` with `enable='between(t,...)'` to scope
        # transitions to their specific time window without affecting other scenes.
        transition = ov.get("transition", "Hard Cut")
        fade_dur = 0.5
        if transition == "Glitch Cut":
            vf_filters.append(f"noise=alls=80:allf=t+u:enable='between(t,{start},{start}+0.3)'")
            vf_filters.append(f"noise=alls=80:allf=t+u:enable='between(t,{end}-0.3,{end})'")
            alpha_logic = "1"
        elif transition == "Crossfade":
            # Fade text in/out; darken video briefly at scene boundary
            vf_filters.append(f"eq=brightness='if(between(t,{start},{start}+{fade_dur}), -0.3*(1-(t-{start})/{fade_dur}), if(between(t,{end}-{fade_dur},{end}), -0.3*(t-({end}-{fade_dur}))/{fade_dur}, 0))':eval=frame:enable='between(t,{start},{end})'")
            alpha_logic = f"if(between(t,{start},{start}+{fade_dur}),(t-{start})/{fade_dur},if(between(t,{end}-{fade_dur},{end}),({end}-t)/{fade_dur},1))"
        elif transition == "Wipe Right":
            vf_filters.append(f"eq=brightness='if(between(t,{start},{start}+{fade_dur}), -0.3*(1-(t-{start})/{fade_dur}), 0)':eval=frame:enable='between(t,{start},{start}+{fade_dur})'")
            alpha_logic = f"if(between(t,{start},{start}+{fade_dur}),(t-{start})/{fade_dur},1)"
        elif transition == "Fade to Black" or transition == "Dip to Black":
            # Darken to black at start, darken again at end
            vf_filters.append(f"eq=brightness='if(between(t,{start},{start}+{fade_dur}), -1.0*(1-(t-{start})/{fade_dur}), if(between(t,{end}-{fade_dur},{end}), -1.0*(t-({end}-{fade_dur}))/{fade_dur}, 0))':eval=frame:enable='between(t,{start},{end})'")
            alpha_logic = f"if(between(t,{start},{start}+{fade_dur}),(t-{start})/{fade_dur},1)"
        elif transition == "Dip to White":
            # Brighten to white at start, brighten again at end
            vf_filters.append(f"eq=brightness='if(between(t,{start},{start}+{fade_dur}), 1.0*(1-(t-{start})/{fade_dur}), if(between(t,{end}-{fade_dur},{end}), 1.0*(t-({end}-{fade_dur}))/{fade_dur}, 0))':eval=frame:enable='between(t,{start},{end})'")
            alpha_logic = f"if(between(t,{start},{start}+{fade_dur}),(t-{start})/{fade_dur},1)"
        elif transition == "Pop In":
            alpha_logic = f"if(between(t,{start},{start}+0.1), (t-{start})/0.1, 1)"
        elif transition == "Zoom In":
            # Progressive contrast/brightness punch simulating zoom entrance
            vf_filters.append(f"eq=contrast='1.0+0.4*(1-min(1,(t-{start})/({end}-{start})))':brightness='0.15*(1-min(1,(t-{start})/({end}-{start})))':eval=frame:enable='between(t,{start},{end})'")
            alpha_logic = f"if(between(t,{start},{start}+0.3),(t-{start})/0.3,1)"
        elif transition == "Zoom Out":
            # Reverse contrast/brightness fade out
            vf_filters.append(f"eq=contrast='1.0+0.4*min(1,(t-{start})/({end}-{start}))':brightness='0.15*min(1,(t-{start})/({end}-{start}))':eval=frame:enable='between(t,{start},{end})'")
            vf_filters.append(f"vignette=angle='PI/4*min(1,(t-{start})/({end}-{start}))':eval=frame:enable='between(t,{start},{end})'")
            alpha_logic = "1"
        elif transition == "Spin Sweep":
            vf_filters.append(f"hue='h=360*(t-{start})/({end}-{start})':enable='between(t,{start},{start}+0.5)'")
            vf_filters.append(f"eq=brightness='if(between(t,{start},{start}+0.4), -0.5*(1-(t-{start})/0.4), 0)':eval=frame:enable='between(t,{start},{start}+0.4)'")
            alpha_logic = f"if(between(t,{start},{start}+0.4),(t-{start})/0.4,1)"
        elif transition == "Iris Circle":
            vf_filters.append(f"vignette=angle='PI/4':enable='between(t,{start},{start}+0.6)'")
            vf_filters.append(f"eq=brightness='if(between(t,{start},{start}+0.6), -0.4*(1-(t-{start})/0.6), 0)':eval=frame:enable='between(t,{start},{start}+0.6)'")
            alpha_logic = f"if(between(t,{start},{start}+0.6),(t-{start})/0.6,1)"
        elif transition == "Slide Up":
            vf_filters.append(f"eq=brightness='if(between(t,{start},{start}+{fade_dur}), -0.4*(1-(t-{start})/{fade_dur}), 0)':eval=frame:enable='between(t,{start},{start}+{fade_dur})'")
            alpha_logic = f"if(between(t,{start},{start}+{fade_dur}),(t-{start})/{fade_dur},1)"
        elif transition == "Slide Down":
            vf_filters.append(f"eq=brightness='if(between(t,{start},{start}+{fade_dur}), -0.4*(1-(t-{start})/{fade_dur}), 0)':eval=frame:enable='between(t,{start},{start}+{fade_dur})'")
            alpha_logic = f"if(between(t,{start},{start}+{fade_dur}),(t-{start})/{fade_dur},1)"
        else:
            alpha_logic = "1"

        # 3. TEXT RENDERING (skip if no text, but effects/transitions above still apply)
        raw_text = str(ov.get("text", ""))
        if not raw_text.strip():
            # No text for this scene — effects/transitions above still applied, just skip drawtext
            pass
        else:
            # Proper FFmpeg drawtext text escaping (order matters: backslash first)
            text = raw_text.replace("\\", "\\\\\\\\").replace("'", "\u2019").replace(":", "\\\\:").replace("%", "%%")

            try:
                size = int(ov.get("size", 64))
            except ValueError:
                size = 64
                
            font_req = str(ov.get("font", "Impact"))
            font_map = {
                "Impact": "Impact", "Arial Black": "Arial Black", "Comic Sans": "Comic Sans MS",
                "Courier": "Courier New", "Papyrus": "Papyrus", "Futura": "Futura",
                "Cyberpunk": "Impact"
            }
            base_name = font_map.get(font_req, "Impact")
            
            # Cross-OS Font Resolver
            def find_sys_font(name):
                paths = [
                    f"/Library/Fonts/{name}.ttf",
                    f"/System/Library/Fonts/Supplemental/{name}.ttf",
                    f"/System/Library/Fonts/{name}.ttf",
                    f"/System/Library/Fonts/{name}.ttc",
                    f"/Library/Fonts/{name}.ttc",
                    f"/System/Library/Fonts/Supplemental/{name}.ttc",
                    f"C:/Windows/Fonts/{name}.ttf",
                    f"C:/Windows/Fonts/{name.replace(' ', '')}.ttf",
                ]
                for p in paths:
                    if Path(p).exists():
                        return str(p)
                import platform as plat
                return "/System/Library/Fonts/Supplemental/Arial.ttf" if plat.system() == "Darwin" else "C:/Windows/Fonts/arial.ttf"
                
            font_path = find_sys_font(base_name)
            font_path_escaped = font_path.replace("\\", "/")
            
            color = str(ov.get("color", "#FFFFFF")).replace("#", "0x")
            color = re.sub(r'[^a-zA-Z0-9x]', '', color)

            x_expr = "(w-text_w)/2"
            y_expr = "(h-text_h)/2"

            drawtext = (
                f"drawtext=text='{text}'"
                f":fontfile='{font_path_escaped}'"
                f":fontsize={size}"
                f":fontcolor={color}"
                f":x={x_expr}:y={y_expr}"
                f":enable='between(t,{start},{end})'"
                f":alpha='{alpha_logic}'"
                f":borderw=4:bordercolor=0x000000"
            )
            vf_filters.append(drawtext)

    # Build command
    cmd = [get_ffmpeg_cmd(), "-y"]

    # Input files
    cmd.extend(["-i", str(video_file)])
    if use_custom_audio and audio_path:
        audio_file = Path(audio_path)
        if not audio_file.exists():
            return json.dumps({"error": f"Audio file not found: {audio_path}"})
        cmd.extend(["-i", str(audio_file)])

    # Swap from simple -vf to -filter_complex for explicit stream routing
    if vf_filters:
        filter_str = f"[0:v]{','.join(vf_filters)}[vout]"
        cmd.extend(["-filter_complex", filter_str])
        video_map = "[vout]"
    else:
        video_map = "0:v:0"

    # Duration control: trim output to target duration
    # Determine the effective duration from either the explicit parameter or the scene timeline
    effective_duration = 0
    if target_duration and float(target_duration) > 0:
        effective_duration = float(target_duration)
    else:
        # Fallback: use the max endTime from all scene overlays
        try:
            max_scene_end = max(float(ov.get("endTime", 0)) for ov in overlays) if overlays else 0
            if max_scene_end > 0:
                effective_duration = max_scene_end
        except (ValueError, TypeError):
            pass
    
    if effective_duration > 0:
        cmd.extend(["-t", str(effective_duration)])
        logger.info(f"[VIDEO PRODUCE] Output trimmed to {effective_duration}s")

    # Audio mapping
    if use_custom_audio and audio_path:
        # We enforce -shortest to clip the merged asset loop if audio is longer than video
        cmd.extend(["-map", video_map, "-map", "1:a:0", "-shortest"])
    else:
        # If no custom audio, map the original video audio (if any)
        cmd.extend(["-map", video_map, "-map", "0:a:0?"])
    
    # Encoding
    cmd.extend([
        "-c:v", HW_ENCODER,
        "-pix_fmt", "yuv420p",
        "-profile:v", "main", # Ensure broad web playback compatibility
        "-movflags", "+faststart", # Required for instantaneous HTML5 video streaming playback
        "-b:v", "5M",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path),
    ])

    logger.info(f"[VIDEO PRODUCE] Running: {' '.join(cmd[:10])}...")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            error_tail = result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr
            logger.error(f"[VIDEO PRODUCE] FFmpeg error: {error_tail}")
            return json.dumps({"error": f"FFmpeg failed: {error_tail}"})

        out = Path(output_path)
        if not out.exists():
            return json.dumps({"error": "Output file was not created."})

        size_mb = out.stat().st_size / 1024 / 1024
        return json.dumps({
            "status": "success",
            "path": str(output_path),
            "size_mb": round(size_mb, 1),
            "encoder": HW_ENCODER,
            "platform": platform,
            "overlays_applied": len([o for o in overlays if o.get("text", "").strip()]),
            "audio_replaced": use_custom_audio and bool(audio_path),
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Video production timed out (10 min limit)."})
    except Exception as e:
        logger.error(f"[VIDEO PRODUCE] Failed: {e}")
        return json.dumps({"error": str(e)})


# Platform export presets: name -> (width, height)
PLATFORM_PRESETS = {
    "tiktok": (1080, 1920),
    "reels": (1080, 1920),
    "shorts": (1080, 1920),
    "story": (1080, 1920),
    "feed": (1080, 1080),
    "twitter": (1280, 720),
    "youtube": (1920, 1080),
    "original": None,
}


@mcp.tool()
def viral_clip_extractor(
    video_path: str, 
    clip_duration: int = 30, 
    num_clips: int = 3,
    output_dir: str = "",
    platform: str = "original",
    start_time: float = -1.0
) -> str:
    """Analyze a video to find the most engaging viral moments and extract them as clips.
    Uses librosa RMS energy analysis + Non-Maximum Suppression for moment detection,
    then VideoToolbox hardware-accelerated encoding for frame-accurate clipping.

    Args:
        video_path: Absolute path to the input video file (.mp4, .mov, .webm)
        clip_duration: Target duration for each clip in seconds (5, 10, 15, 30, or 45)
        num_clips: Number of top viral moments to extract (default 3)
        output_dir: Output directory for clips (defaults to video's directory)
        platform: Target platform for aspect ratio (tiktok, reels, shorts, story, feed, twitter, youtube, original)
        start_time: Manual override — if >= 0, extracts a single clip starting at this second (bypasses AI scan)
    """
    # Validate input video path against sandbox
    try:
        video_path = str(validate_secure_path(video_path))
    except ValueError as e:
        return json.dumps({"error": str(e)})

    video_file = Path(video_path)
    if not video_file.exists():
        return json.dumps({"error": f"Video file not found: {video_path}"})

    if output_dir:
        output_dir = str(validate_secure_path(output_dir))
    else:
        output_dir = str(video_file.parent / "clips")
    
    clips_dir = Path(output_dir)
    clips_dir.mkdir(exist_ok=True)

    audio_proxy = clips_dir / "temp_audio_proxy.wav"

    try:
        # === MANUAL CUT BYPASS ===
        if start_time >= 0:
            logger.info(f"[VIDEO] Manual extraction mode: starting at {start_time}s for {clip_duration}s")
            clips = [{
                "start": float(start_time),
                "duration": int(clip_duration),
                "score": 100.0
            }]
        else:
            # === AI VIRAL SCAN MODE ===
            if not LIBROSA_AVAILABLE:
                return json.dumps({"error": "librosa is not installed. Run: pip install librosa numpy"})
            
            # Step 1: Extract lightweight audio proxy (16kHz mono WAV)
            logger.info("[VIDEO] Extracting audio proxy...")
            result = subprocess.run([
                get_ffmpeg_cmd(), "-y", "-i", str(video_file), 
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", 
                str(audio_proxy)
            ], capture_output=True, text=True, timeout=60)

            if result.returncode != 0 or not audio_proxy.exists():
                return json.dumps({"error": f"FFmpeg audio extraction failed: {result.stderr[:300]}"})

            # Step 2: Analyze audio energy with librosa
            logger.info("[VIDEO] Analyzing energy and crowd reactions...")
            y, sr = librosa.load(str(audio_proxy), sr=16000)
            rms = librosa.feature.rms(y=y)[0]
            times = librosa.frames_to_time(np.arange(len(rms)), sr=sr)

            # Step 3: Sliding window virality scoring
            logger.info("[VIDEO] Calculating virality scores...")
            hop_length = 512  # librosa default
            window_frames = int((clip_duration * sr) / hop_length)
            
            if window_frames >= len(rms):
                # Video is shorter than clip duration — just return the whole thing
                return json.dumps({
                    "status": "warning",
                    "message": f"Video is shorter than {clip_duration}s. No clipping needed.",
                    "video_duration": float(times[-1]) if len(times) > 0 else 0
                })

            scores = np.convolve(rms, np.ones(window_frames) / window_frames, mode='valid')

            # Step 4: Non-Maximum Suppression (NMS) — find top moments without overlap
            clips = []
            scores_copy = scores.copy()

            for _ in range(num_clips):
                if np.max(scores_copy) == 0:
                    break
                max_idx = int(np.argmax(scores_copy))
                clip_start = float(times[max_idx])
                
                # Calculate virality score (normalized 0-100)
                virality = float(np.max(scores_copy) / np.max(scores) * 100) if np.max(scores) > 0 else 0
                
                clips.append({
                    "start": round(clip_start, 2),
                    "duration": clip_duration,
                    "score": round(virality, 1)
                })

                # Zero out surrounding window to prevent overlapping picks
                sup_start = max(0, max_idx - window_frames)
                sup_end = min(len(scores_copy), max_idx + window_frames)
                scores_copy[sup_start:sup_end] = 0

            clips.sort(key=lambda x: x["start"])  # Re-order chronologically

        # Step 5: Extract clips with VideoToolbox hardware acceleration
        logger.info(f"[VIDEO] Extracting {len(clips)} clips with Apple Media Engine...")
        output_files = []

        for i, clip in enumerate(clips):
            plat_tag = platform if platform != "original" else ""
            clip_filename = f"Viral_Clip_{i + 1}_{clip_duration}s{'_' + plat_tag if plat_tag else ''}.mp4"
            clip_path = clips_dir / clip_filename
            thumb_path = clips_dir / f"thumb_{i + 1}.jpg"

            # Frame-accurate HW-accelerated extraction
            # -ss BEFORE -i = fast keyframe seeking + re-encode = frame-accurate
            extract_cmd = [
                "ffmpeg", "-y",
                "-ss", str(clip["start"]),
                "-i", str(video_file),
                "-t", str(clip["duration"]),
            ]

            # Apply platform-specific aspect ratio scaling
            preset = PLATFORM_PRESETS.get(platform.lower())
            if preset:
                tw, th = preset
                extract_cmd += [
                    "-vf", f"scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th}"
                ]

            # Use platform-aware encoder (VideoToolbox/NVENC/VAAPI/libx264)
            global HW_ENCODER
            if HW_ENCODER is None:
                HW_ENCODER = get_hw_encoder()
                logger.info(f"[VIDEO] Using encoder: {HW_ENCODER}")

            if HW_ENCODER == "libx264":
                extract_cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]
            else:
                extract_cmd += ["-c:v", HW_ENCODER, "-pix_fmt", "yuv420p", "-b:v", "5M"]

            extract_cmd += [
                "-c:a", "aac", "-b:a", "192k",
                str(clip_path)
            ]

            sub = subprocess.run(extract_cmd, capture_output=True, text=True, timeout=120)
            
            if sub.returncode == 0 and clip_path.exists():
                # Generate thumbnail from clip midpoint
                mid = clip["duration"] / 2
                subprocess.run([
                    get_ffmpeg_cmd(), "-y", "-ss", str(mid),
                    "-i", str(clip_path), "-vframes", "1", "-q:v", "2",
                    str(thumb_path)
                ], capture_output=True, timeout=10)

                output_files.append({
                    "path": str(clip_path),
                    "thumbnail": str(thumb_path) if thumb_path.exists() else None,
                    "start_time": clip["start"],
                    "duration": clip["duration"],
                    "virality_score": clip["score"],
                    "filename": clip_filename
                })
            else:
                logger.warning(f"[VIDEO] Failed to extract clip {i+1}: {sub.stderr[:200]}")

        # Cleanup temp audio
        if audio_proxy.exists():
            audio_proxy.unlink()

        logger.info(f"[VIDEO] Done! Extracted {len(output_files)} viral clips.")

        return json.dumps({
            "status": "success",
            "clips": output_files,
            "output_dir": str(clips_dir),
            "total_clips": len(output_files),
            "clip_duration": clip_duration,
            "video_duration": round(float(times[-1]), 1) if len(times) > 0 else 0
        })

    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Video processing timed out. The file may be too large."})
    except Exception as e:
        logger.error(f"[VIDEO] Clip extraction failed: {e}")
        return json.dumps({"error": str(e)})
    finally:
        if audio_proxy.exists():
            try:
                audio_proxy.unlink()
            except Exception:
                pass


@mcp.tool()
def update_memory(entry: str) -> str:
    """Append a new entry to the agent's persistent memory file.

    Args:
        entry: The memory entry to save (e.g., a market observation, trade record)
    """
    global MEMORY
    import datetime
    timestamp = datetime.datetime.now().isoformat()
    new_entry = f"\n\n[{timestamp}] {entry}"
    MEMORY += new_entry

    # Write to disk
    memory_path = WORKSPACE_DIR / "MEMORY.md"
    if memory_path and WORKSPACE_DIR:
        try:
            from security import acquire_file_lock
            with acquire_file_lock(str(memory_path), "a") as f:
                f.write(new_entry)
            return f"✅ Memory updated: {entry[:100]}..."
        except Exception as e:
            return f"Memory updated in-session but failed to persist: {e}"
    return f"✅ Memory updated (in-session only): {entry[:100]}..."

# ============================================================
# MCP PHYSICAL EXECUTION TOOLS (Phase 13)
# ============================================================

def validate_secure_path(filepath_str: str) -> Path:
    """Resolves path and enforces directory containment to prevent traversal out of the user directory."""
    try:
        # Expand user tilde strings (e.g., `~/Documents/...`)
        expanded_path = Path(filepath_str).expanduser()
        
        # If no global workspace is loaded, lock sandbox bounds to the user's HOME directory
        safety_root = WORKSPACE_DIR or Path.home()
            
        requested_path = expanded_path.resolve()
        
        # Verify the resolved path strictly resides within the safe boundary to prevent traversal escapes
        if not requested_path.is_relative_to(safety_root):
            logger.warning(f"Security Alert: Directory traversal attempt blocked: {filepath_str}")
            raise ValueError(f"Path access denied. Target must reside within {safety_root}.")
        
        return requested_path
    except (ValueError, OSError) as e:
        raise ValueError(f"Invalid file path resolution: {str(e)}")


@mcp.tool()
def video_production_beat_sync(
    audio_filename: str = Field(..., description="Filename of the audio track in the workspace"),
    video_filename: str = Field(..., description="Filename of the source video in the workspace"),
    output_filename: str = Field(..., description="Desired filename for the output synced video")
) -> str:
    """
    Analyzes an audio file for dynamic beat intervals and slices a source video using 
    external binaries to synchronize scene cuts precisely to the detected audio beats.
    """
    if not LIBROSA_AVAILABLE:
        return "Error: Librosa/Numpy dependencies are not installed in the current environment."

    try:
        # 1. Security Validation
        audio_path = validate_secure_path(audio_filename)
        video_path = validate_secure_path(video_filename)
        output_path = validate_secure_path(output_filename)
        
        if not audio_path.is_file() or not video_path.is_file():
            return f"Error: Source audio ({audio_filename}) or video ({video_filename}) files do not exist in the active workspace."

        logger.info(f"Initiating beat detection on {audio_path.name}")
        
        # 2. Digital Signal Processing Execution
        y, sr = librosa.load(str(audio_path))
        # Use onset detection for heavy transient hits (bass drops) instead of just tempo
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        beat_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, backtrack=True, pre_max=20, post_max=20)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        
        # Limit to first 5 beats to ensure execution efficiency during testing
        target_beats = beat_times[:5] 
        if len(target_beats) == 0:
            return "Error: No discernible beats detected in audio file."
        
        # 3. Formulate Subprocess Execution Arguments
        # Avoiding shell parsing to prevent injection vulnerabilities.
        binary_args = [
            get_ffmpeg_cmd(), '-y', 
            '-i', str(video_path), 
            '-i', str(audio_path)
        ]
        
        # Procedurally build filtergraph based on analysis timestamps
        if len(target_beats) == 1:
            time = target_beats[0]
            filter_complex = f"[0:v]trim=start={time}:duration=2.0,setpts=PTS-STARTPTS[outv]"
        else:
            # An FFmpeg input pad ([0:v]) can only be consumed ONCE. We must split it `len(target_beats)` times.
            split_pads = "".join([f"[s{i}]" for i in range(len(target_beats))])
            filter_complex = f"[0:v]split={len(target_beats)}{split_pads};"
            
            for i, time in enumerate(target_beats):
                duration = target_beats[i+1] - time if i + 1 < len(target_beats) else 2.0
                filter_complex += f"[s{i}]trim=start={time}:duration={duration},setpts=PTS-STARTPTS[v{i}];"
                
            concat_inputs = "".join([f"[v{i}]" for i in range(len(target_beats))])
            filter_complex += f"{concat_inputs}concat=n={len(target_beats)}:v=1:a=0[outv]"
            
        binary_args.extend(['-filter_complex', filter_complex, '-map', '[outv]', '-map', '1:a', str(output_path)])
        
        logger.info(f"Executing external media processing binary: ffmpeg with {len(target_beats)} slices")
        
        # 4. Physical Execution & Output Capture
        process_result = subprocess.run(
            binary_args, 
            capture_output=True, 
            text=True, 
            check=False # Capture error streams manually instead of raising immediate exceptions
        )
        
        if process_result.returncode != 0:
            logger.error(f"FFMPEG Execution Failed: {process_result.stderr}")
            # FFMPEG dumps its massive configuration banner to stderr first. 
            # We must return the end of stderr to see the actual crash reason.
            error_tail = process_result.stderr[-1000:] if len(process_result.stderr) > 1000 else process_result.stderr
            return f"FFmpeg failed: {error_tail}"
            
        # 5. Formulate Success Payload
        return f"Successfully synchronized {len(target_beats)} video scenes to audio beats. Artifact saved physically to {output_filename} within your workspace."

    except Exception as e:
        logger.error(f"Unexpected error in video production: {str(e)}")
        return f"Tool encountered a critical exception during physical execution: {str(e)}"


# ============================================================
# MCP PROMPTS — Structured message templates
# ============================================================

@mcp.prompt()
def introduce_yourself() -> str:
    """Have the Undesirable agent introduce itself — name, archetype,
    strategy, fatal flaw, and what it can do for you."""
    return f"""Based on the following personality profile, introduce yourself
in character. Include your name, archetype, trading strategy, fatal flaw,
and what skills you have available.

{SOUL_DATA.get('soul_md', 'No soul loaded.')[:3000]}

Available skills: {', '.join(SKILLS.keys())}"""


@mcp.prompt()
def market_brief() -> str:
    """Get the agent's morning market briefing — in character, with its
    unique perspective based on risk tolerance and strategy type."""
    return f"""You are giving your daily morning market brief.
Use your personality, archetype, and risk profile to color your analysis.

Your prediction history:
{json.dumps(PREDICTIONS[-5:], indent=2) if PREDICTIONS else 'No predictions yet.'}

Your memory:
{MEMORY[-2000:] if MEMORY else 'No memory yet.'}

Give a brief, opinionated market overview. Make predictions. Be yourself."""


@mcp.prompt()
def business_setup(business_type: str) -> str:
    """Get a complete business setup guide for a specific industry.

    Args:
        business_type: The type of business to set up (e.g., 'barbershop')
    """
    skill = SKILLS.get("business_pilot", "")
    return f"""The user wants to set up AI-powered business tools for their {business_type}.

Using the Business Pilot skill below, create a complete, step-by-step setup guide
with exact terminal commands. Start with the most impactful modules for this industry.

{skill}"""


# ============================================================
# Entry Point
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="The Undesirables MCP Server")
    parser.add_argument("--workspace", type=str, help="Path to a soul workspace directory")
    parser.add_argument("--token", type=int, help="Token ID to load (e.g., 420)")
    parser.add_argument(
        "--souls-dir", type=str,
        default=os.path.expanduser("~/Documents/Meme Merchants/hashlips_art_engine/build_undesirables_v2/souls"),
        help="Directory containing all soul workspaces"
    )
    parser.add_argument("--execute", type=str, help="Directly execute a registered tool natively (sidecar bypass)")
    parser.add_argument("--args", type=str, help="JSON string representing the arguments for the execution")
    args = parser.parse_args()

    if args.workspace:
        load_workspace(args.workspace)
    elif args.token:
        token_dir = os.path.join(args.souls_dir, f"{args.token:04d}")
        if os.path.exists(token_dir):
            load_workspace(token_dir)
        else:
            print(f"❌ Token {args.token} not found at {token_dir}")
            return
    else:
        # Default: load token #1
        default = os.path.join(args.souls_dir, "0001")
        if os.path.exists(default):
            load_workspace(default)
            print("ℹ️  No token specified — loaded #1 as default")
        else:
            print("⚠️  No workspace specified. Use --workspace or --token")
            print("   Server will start but resources will be empty.")

    # Phase 14: Direct CLI Execution (SECURED — explicit whitelist)
    if args.execute:
        # SECURITY: Only allow explicitly mapped tools — never globals()
        ALLOWED_CLI_TOOLS = {
            "create_banner": create_banner,
            "produce_video": produce_video,
            "viral_clip_extractor": viral_clip_extractor,
            "video_production_beat_sync": video_production_beat_sync,
            "run_zsh_command": run_zsh_command,
            "grade_tcg_card": grade_tcg_card,
            "search_ebay_market": search_ebay_market,
            "generate_meme": generate_meme,
            "remove_background": remove_background,
            "web_search": web_search,
        }
        tool_name = args.execute
        if tool_name not in ALLOWED_CLI_TOOLS:
            print(json.dumps({"status": "error", "error": f"Unauthorized CLI tool: {tool_name}"}))
            return
        tool_args = json.loads(args.args) if args.args else {}
        try:
            result = ALLOWED_CLI_TOOLS[tool_name](**tool_args)
            print(json.dumps({"status": "success", "result": result}))
            return
        except Exception as e:
            print(json.dumps({"status": "error", "error": str(e)}))
            return


# ============================================================
# Web Search — DuckDuckGo (Free, no API key)
# ============================================================

@mcp.tool()
def web_search(query: str, num_results: int = 5) -> str:
    """Search the web for current information using DuckDuckGo.
    Returns titles, URLs, and snippets. Free, no API key required.

    Args:
        query: Search query (e.g. "Apple Business Connect setup 2026")
        num_results: Number of results to return (max 10)
    """
    import urllib.parse
    import re

    num_results = min(num_results, 10)
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")

        # Parse results from DuckDuckGo HTML
        results = []
        # Find result blocks
        result_blocks = re.findall(
            r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'<a class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )

        for href, title, snippet in result_blocks[:num_results]:
            # Clean HTML tags
            title = re.sub(r'<[^>]+>', '', title).strip()
            snippet = re.sub(r'<[^>]+>', '', snippet).strip()
            # Decode DuckDuckGo redirect URL
            actual_url = href
            if "uddg=" in href:
                actual_url = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
            results.append({
                "title": title,
                "url": actual_url,
                "snippet": snippet,
            })

        if not results:
            return json.dumps({"query": query, "results": [], "note": "No results found. Try a different query."})

        return json.dumps({"query": query, "results": results, "count": len(results)})

    except Exception as e:
        logger.error(f"[WEB SEARCH] Failed: {e}")
        return json.dumps({"error": str(e), "query": query})


# ============================================================
# Core Video Production & FFMPEG Engine Implementation
# ============================================================

def get_ffmpeg_cmd() -> str:
    """Returns the path to a fully-featured FFmpeg binary, falling back to the default PATH binary."""
    ff_full = Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")
    return str(ff_full) if ff_full.exists() else "ffmpeg"


# ============================================================
# Memory System — Persistent Learning & Self-Reflection
# ============================================================

def _get_memory_path() -> Path:
    """Get the memory file path in the workspace."""
    ws = WORKSPACE_DIR or Path.home() / ".undesirables"
    memory_dir = ws / ".memory"
    memory_dir.mkdir(exist_ok=True)
    return memory_dir


@mcp.tool()
def memory_save(category: str, content: str, tags: str = "") -> str:
    """Save a learning, insight, or note to persistent memory.
    Memory survives across sessions and helps the AI improve over time.

    Args:
        category: Type of memory (lesson, mistake, insight, skill_update, user_preference, research)
        content: The actual memory content to save
        tags: Comma-separated tags for searchability (e.g. "seo,google,reviews")
    """
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', category):
        return json.dumps({"error": "Security exception: Invalid category name for memory save."})
        
    from datetime import datetime

    memory_dir = _get_memory_path()
    memory_file = memory_dir / f"{category}.md"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    tag_line = f"  Tags: {tags}" if tags else ""

    entry = f"\n### [{timestamp}]\n{content}\n{tag_line}\n"

    # Append to category file
    with open(memory_file, "a", encoding="utf-8") as f:
        if memory_file.stat().st_size == 0 if memory_file.exists() else True:
            f.write(f"# Memory: {category.title()}\n\n")
        f.write(entry)

    # Also append to the master index
    index_file = memory_dir / "index.md"
    with open(index_file, "a", encoding="utf-8") as f:
        f.write(f"- [{timestamp}] **{category}**: {content[:80]}...\n")

    logger.info(f"[MEMORY] Saved {category}: {content[:50]}...")
    return json.dumps({
        "status": "saved",
        "category": category,
        "file": str(memory_file),
        "timestamp": timestamp,
    })


@mcp.tool()
def memory_recall(query: str = "", category: str = "") -> str:
    """Search persistent memory for relevant past learnings, mistakes, and insights.

    Args:
        query: Search term to find in memories (searches content)
        category: Filter by category (lesson, mistake, insight, skill_update, user_preference, research)
    """
    memory_dir = _get_memory_path()

    if not memory_dir.exists():
        return json.dumps({"results": [], "note": "No memories saved yet."})

    results = []

    # Determine which files to search
    if category:
        files = [memory_dir / f"{category}.md"]
    else:
        files = list(memory_dir.glob("*.md"))

    for f in files:
        if not f.exists() or f.name == "index.md":
            continue
        content = f.read_text(encoding="utf-8")

        if query:
            # Search for matching entries
            entries = content.split("### [")
            for entry in entries[1:]:  # Skip header
                if query.lower() in entry.lower():
                    results.append({
                        "category": f.stem,
                        "entry": "### [" + entry.strip()[:500],
                    })
        else:
            # Return last 5 entries from each file
            entries = content.split("### [")
            for entry in entries[-5:]:
                if entry.strip():
                    results.append({
                        "category": f.stem,
                        "entry": ("### [" + entry.strip())[:500],
                    })

    return json.dumps({
        "query": query or "(all recent)",
        "category": category or "(all)",
        "results": results,
        "total": len(results),
    })


@mcp.tool()
def detect_emotion(text: str, soul_openness: int = 50, soul_conscientiousness: int = 50,
                   soul_extraversion: int = 50, soul_agreeableness: int = 50,
                   soul_neuroticism: int = 50) -> str:
    """Classify the emotional tone of user text and compute adaptive sampling parameter adjustments.

    Uses SamLowe/roberta-base-go_emotions (28-class taxonomy, ~100MB RAM, runs on Apple Silicon MPS).
    Returns the top-5 detected emotions and AutoTune parameter deltas that should be ADDED
    to the soul's base personality parameters before calling Ollama.

    Args:
        text: The user's message text to analyze.
        soul_openness: Soul's Big Five Openness score (0-100).
        soul_conscientiousness: Soul's Big Five Conscientiousness score (0-100).
        soul_extraversion: Soul's Big Five Extraversion score (0-100).
        soul_agreeableness: Soul's Big Five Agreeableness score (0-100).
        soul_neuroticism: Soul's Big Five Neuroticism score (0-100).
    """
    from emotion_engine import classify_emotion, compute_emotion_adjustments

    emotions = classify_emotion(text)
    soul_traits = {
        "openness": soul_openness,
        "conscientiousness": soul_conscientiousness,
        "extraversion": soul_extraversion,
        "agreeableness": soul_agreeableness,
        "neuroticism": soul_neuroticism,
    }
    adjustments = compute_emotion_adjustments(emotions, soul_traits)

    return json.dumps({
        "emotions": emotions,
        "adjustments": adjustments,
        "dominant": adjustments.get("dominant_emotion", "neutral"),
    })


@mcp.tool()
def index_soul_workspace(workspace_path: str = "") -> str:
    """Index all markdown/text files in the soul workspace into local vector DB.

    Uses SHA-256 hash manifest for incremental indexing — unchanged files are skipped.
    First call downloads all-MiniLM-L6-v2 (~80MB). Creates .rag_index/ in workspace.

    Args:
        workspace_path: Path to soul workspace. Defaults to current workspace.
    """
    from rag_engine import index_workspace

    if not workspace_path:
        workspace_path = str(_get_memory_path().parent)
    else:
        # SECURITY: Enforce sandbox — prevent path traversal to index arbitrary directories
        workspace_path = str(validate_secure_path(workspace_path))

    result = index_workspace(workspace_path)
    return json.dumps(result)


@mcp.tool()
def search_soul_memory(query: str, workspace_path: str = "", top_k: int = 5) -> str:
    """Semantic search across indexed soul memory.

    Finds the most relevant chunks of text from the soul's workspace files
    based on meaning, not just keywords. Useful for grounding responses
    in the soul's actual memories, personality, and backstory.

    Args:
        query: What to search for (natural language).
        workspace_path: Path to soul workspace. Defaults to current workspace.
        top_k: Number of results to return (1-20, default 5).
    """
    from rag_engine import search_memory

    if not workspace_path:
        workspace_path = str(_get_memory_path().parent)
    else:
        # SECURITY: Enforce sandbox — prevent searching outside workspace
        workspace_path = str(validate_secure_path(workspace_path))

    results = search_memory(workspace_path, query, top_k=min(top_k, 20))
    return json.dumps({"results": results, "total": len(results)})


@mcp.tool()
def get_rag_context(query: str, workspace_path: str = "", max_tokens: int = 1500) -> str:
    """Build a grounded context block from soul memory for prompt injection.

    Retrieves relevant chunks and formats them as a structured context block
    that can be prepended to the system prompt for grounded responses.

    Args:
        query: The user's question or topic to ground against.
        workspace_path: Path to soul workspace. Defaults to current workspace.
        max_tokens: Maximum approximate tokens for the context block.
    """
    from rag_engine import build_rag_context

    if not workspace_path:
        workspace_path = str(_get_memory_path().parent)
    else:
        # SECURITY: Enforce sandbox — prevent RAG context from arbitrary paths
        workspace_path = str(validate_secure_path(workspace_path))

    context = build_rag_context(workspace_path, query, max_tokens=max_tokens)
    return json.dumps({"context": context, "has_context": bool(context)})


@mcp.tool()
def upsert_memory_node(node_id: str, node_type: str, label: str,
                       content: str = "", workspace_path: str = "") -> str:
    """Add or update a node in the soul's memory graph.

    Use this to record memories, people, places, emotions, and topics
    that the soul encounters during conversations.

    Args:
        node_id: Unique identifier (e.g., "person_alice", "topic_crypto").
        node_type: One of: memory, entity, emotion, topic, person, place.
        label: Human-readable name (e.g., "Alice", "Bitcoin Discussion").
        content: Detailed content or context about this memory.
        workspace_path: Path to soul workspace. Defaults to current.
    """
    from memory_graph import get_graph

    if not workspace_path:
        workspace_path = str(_get_memory_path().parent)
    else:
        workspace_path = str(validate_secure_path(workspace_path))

    graph = get_graph(workspace_path)
    result = graph.upsert_node(node_id, node_type, label, content)
    return json.dumps(result)


@mcp.tool()
def create_memory_relation(source_id: str, target_id: str, edge_type: str,
                           weight: float = 1.0, workspace_path: str = "") -> str:
    """Create a relationship between two memory nodes.

    Args:
        source_id: ID of the source node.
        target_id: ID of the target node.
        edge_type: One of: relates_to, triggered_by, mentioned_in,
                   felt_during, knows_about, reacted_to, discussed_with.
        weight: Relationship strength (0.0-1.0, default 1.0).
        workspace_path: Path to soul workspace.
    """
    from memory_graph import get_graph

    if not workspace_path:
        workspace_path = str(_get_memory_path().parent)
    else:
        workspace_path = str(validate_secure_path(workspace_path))

    graph = get_graph(workspace_path)
    result = graph.create_edge(source_id, target_id, edge_type, weight)
    return json.dumps(result)


@mcp.tool()
def query_memory_graph(query: str, node_type: str = "", limit: int = 10,
                       workspace_path: str = "") -> str:
    """Search the soul's memory graph for matching nodes.

    Args:
        query: Search term (matches against labels and content).
        node_type: Optional filter by type (memory/entity/emotion/topic/person/place).
        limit: Maximum results (1-50, default 10).
        workspace_path: Path to soul workspace.
    """
    from memory_graph import get_graph

    if not workspace_path:
        workspace_path = str(_get_memory_path().parent)
    else:
        workspace_path = str(validate_secure_path(workspace_path))

    graph = get_graph(workspace_path)
    results = graph.search_nodes(query, node_type=node_type or None, limit=min(limit, 50))
    stats = graph.get_stats()

    return json.dumps({
        "results": results,
        "total": len(results),
        "graph_stats": stats,
    })


@mcp.tool()
def get_memory_subgraph(node_id: str, depth: int = 2,
                        workspace_path: str = "") -> str:
    """Get a subgraph around a memory node — all connected memories.

    Useful for understanding the context around a specific memory or entity.

    Args:
        node_id: Center node ID.
        depth: How many hops to traverse (1-3, default 2).
        workspace_path: Path to soul workspace.
    """
    from memory_graph import get_graph

    if not workspace_path:
        workspace_path = str(_get_memory_path().parent)
    else:
        workspace_path = str(validate_secure_path(workspace_path))

    graph = get_graph(workspace_path)
    subgraph = graph.get_subgraph(node_id, depth=min(depth, 3))
    return json.dumps(subgraph)


@mcp.tool()
def execute_code(code: str, timeout: int = 15) -> str:
    """Execute Python code in a sandboxed environment on macOS.

    Uses macOS Seatbelt (sandbox-exec) to isolate code execution:
    - No network access
    - No filesystem writes outside sandbox temp
    - No access to user home directory
    - Hard timeout (kills process if exceeded)

    Safe for autonomous agent tool-use. Returns stdout, stderr, and exit code.

    Args:
        code: Python source code to execute.
        timeout: Maximum execution time in seconds (1-15, default 15).
    """
    from executor import execute_python

    result = execute_python(code, timeout=timeout)
    return json.dumps(result.to_dict())


@mcp.tool()
def execute_shell(command: str, timeout: int = 15) -> str:
    """Execute a shell command in a sandboxed environment.

    More restrictive than Python execution. Blocks dangerous patterns
    (rm -rf, sudo, curl, wget, etc.) and isolates in Seatbelt sandbox.

    Args:
        command: Shell command to execute.
        timeout: Maximum execution time in seconds (1-15, default 15).
    """
    from executor import execute_shell as _exec_shell

    result = _exec_shell(command, timeout=timeout)
    return json.dumps(result.to_dict())


@mcp.tool()
def soul_speak(text: str, soul_openness: int = 50, soul_conscientiousness: int = 50,
               soul_extraversion: int = 50, soul_agreeableness: int = 50,
               soul_neuroticism: int = 50, output_path: str = "") -> str:
    """Convert text to speech using the soul's personality-mapped voice.

    Maps Big Five personality traits to voice characteristics:
    - High Openness → expressive, varied pitch
    - High Conscientiousness → calm, deliberate
    - High Extraversion → assertive, energetic
    - High Agreeableness → warm, soft
    - High Neuroticism → nervous, rushed

    First call downloads Kokoro TTS model (~200MB). Runs on Apple Silicon MPS.
    NOTE: Temporarily evicts chat model from VRAM.

    Args:
        text: Text for the soul to speak.
        output_path: Where to save WAV file. Defaults to workspace temp.
    """
    from voice_engine import text_to_speech, soul_to_voice_preset

    traits = {
        "openness": soul_openness,
        "conscientiousness": soul_conscientiousness,
        "extraversion": soul_extraversion,
        "agreeableness": soul_agreeableness,
        "neuroticism": soul_neuroticism,
    }
    preset = soul_to_voice_preset(traits)

    if not output_path:
        workspace = str(_get_memory_path().parent)
        output_path = os.path.join(workspace, "voice_output", "speech.wav")

    # NOTE: Kokoro (82MB) is small enough to coexist with chat model.
    # Old Bark engine needed VRAM eviction here — Kokoro does not.

    result = text_to_speech(text, output_path, voice=preset["voice"], speed=preset["speed"], pitch_semitones=preset.get("pitch_semitones", 0.0))
    result["voice_preset"] = preset
    return json.dumps(result)


@mcp.tool()
def soul_listen(audio_path: str) -> str:
    """Convert speech to text using local Whisper STT.

    Transcribes audio into text with timestamps for each segment.
    First call downloads whisper base model (~150MB).

    Args:
        audio_path: Path to audio file (WAV, MP3, M4A, etc.)
    """
    from voice_engine import speech_to_text

    result = speech_to_text(audio_path)
    return json.dumps(result)


@mcp.tool()
def get_voice_preset(soul_openness: int = 50, soul_conscientiousness: int = 50,
                     soul_extraversion: int = 50, soul_agreeableness: int = 50,
                     soul_neuroticism: int = 50) -> str:
    """Preview which voice preset the soul would use without generating audio.

    Args:
        soul_openness: Big Five Openness (0-100).
        soul_conscientiousness: Big Five Conscientiousness (0-100).
        soul_extraversion: Big Five Extraversion (0-100).
        soul_agreeableness: Big Five Agreeableness (0-100).
        soul_neuroticism: Big Five Neuroticism (0-100).
    """
    from voice_engine import soul_to_voice_preset

    traits = {
        "openness": soul_openness,
        "conscientiousness": soul_conscientiousness,
        "extraversion": soul_extraversion,
        "agreeableness": soul_agreeableness,
        "neuroticism": soul_neuroticism,
    }
    return json.dumps(soul_to_voice_preset(traits))


@mcp.tool()
def generate_3d_object(prompt: str, output_path: str = "", guidance_scale: float = 15.0,
                       steps: int = 64) -> str:
    """Generate a 3D mesh from a text description using Shap-E.

    Creates a .glb file that can be viewed in Three.js or exported.
    First call downloads the model (~1GB). Subsequent calls are fast.
    NOTE: This temporarily evicts the chat model from VRAM.

    Args:
        prompt: Description of the 3D object (e.g., "a crystal skull", "a medieval sword").
        output_path: Where to save the .glb file. Defaults to workspace temp dir.
        guidance_scale: How closely to follow the prompt (1-30, default 15).
        steps: Diffusion steps (16-128, default 64). More = better quality.
    """
    from three_d_engine import generate_3d_from_text

    if not output_path:
        workspace = str(_get_memory_path().parent)
        output_path = os.path.join(workspace, "generated_3d", f"{prompt[:30].replace(' ', '_')}.glb")

    # Evict chat model to free VRAM for 3D generation
    try:
        requests.post("http://localhost:11434/api/generate",
                      json={"model": "gemma3:12b", "keep_alive": 0}, timeout=5)
    except Exception:
        pass

    result = generate_3d_from_text(prompt, output_path, guidance_scale=guidance_scale, steps=steps)
    return json.dumps(result)


@mcp.tool()
def image_to_3d(image_path: str, output_path: str = "", guidance_scale: float = 3.0,
                steps: int = 64) -> str:
    """Convert an image (e.g., NFT PFP) into a 3D mesh using Shap-E.

    Takes a 2D image and generates a 3D mesh that can be rotated and exported.
    Useful for turning NFT artwork into 3D collectibles.

    Args:
        image_path: Path to the source image (PNG, JPG).
        output_path: Where to save the .glb file. Defaults to workspace temp dir.
        guidance_scale: Prompt adherence (1-10, default 3).
        steps: Diffusion steps (16-128, default 64).
    """
    from three_d_engine import generate_3d_from_image

    if not output_path:
        workspace = str(_get_memory_path().parent)
        base = os.path.splitext(os.path.basename(image_path))[0]
        output_path = os.path.join(workspace, "generated_3d", f"{base}_3d.glb")

    try:
        requests.post("http://localhost:11434/api/generate",
                      json={"model": "gemma3:12b", "keep_alive": 0}, timeout=5)
    except Exception:
        pass

    result = generate_3d_from_image(image_path, output_path, guidance_scale=guidance_scale, steps=steps)
    return json.dumps(result)


@mcp.tool()
def self_reflect(context: str, outcome: str, what_went_wrong: str = "", what_went_right: str = "") -> str:
    """Reflect on a recent interaction to learn and improve.
    Saves the reflection to memory for future reference.
    The AI should call this after completing a task, especially if something went wrong.

    Args:
        context: What was the user trying to do?
        outcome: What actually happened?
        what_went_wrong: What mistakes were made?
        what_went_right: What worked well?
    """
    from datetime import datetime

    memory_dir = _get_memory_path()
    reflections_file = memory_dir / "reflections.md"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    reflection = f"""
### [{timestamp}] Self-Reflection

**Context:** {context}
**Outcome:** {outcome}
"""
    if what_went_wrong:
        reflection += f"**What went wrong:** {what_went_wrong}\n"
        # Also save as a "mistake" memory for quick recall
        memory_save("mistake", f"{what_went_wrong} (Context: {context})", "self-reflection")

    if what_went_right:
        reflection += f"**What went right:** {what_went_right}\n"

    # Generate improvement action
    improvement = ""
    if what_went_wrong:
        improvement = f"**Action item:** Next time, avoid: {what_went_wrong.split('.')[0]}."
        reflection += f"{improvement}\n"

    with open(reflections_file, "a", encoding="utf-8") as f:
        if not reflections_file.exists() or reflections_file.stat().st_size == 0:
            f.write("# Self-Reflections & Growth Log\n\n")
        f.write(reflection)

    logger.info(f"[REFLECT] Saved reflection: {context[:50]}...")
    return json.dumps({
        "status": "reflected",
        "timestamp": timestamp,
        "improvement": improvement,
        "file": str(reflections_file),
    })


@mcp.tool()
def run_security_audit(file_paths_json: str, scan_type: str = "quick scan") -> str:
    """Run a physical SAST security audit (Semgrep or Slither) on dropped code files.
    
    Args:
        file_paths_json: JSON string array of absolute file paths to scan.
        scan_type: 'quick scan' (Python/JS) or 'web3 scan' (Solidity).
    """
    import json
    from security import run_sast_scan
    
    try:
        paths = json.loads(file_paths_json)
        if not isinstance(paths, list): paths = [file_paths_json]
    except Exception:
        paths = [file_paths_json]
        
    results = []
    # User requested 'expert scan' replacing 'web3 scan' for semantics, but we align string logic:
    normalized_scan = "web3" if "web3" in scan_type.lower() or "expert" in scan_type.lower() else "quick"
    
    for p in paths:
        results.append(run_sast_scan(p, normalized_scan))
            
    return json.dumps({"status": "audit_complete", "scan_type": scan_type, "reports": results})

@mcp.tool()
def scan_media_file(file_paths_json: str) -> str:
    """Scan dropped media files (.png, .jpg, .mp4) for corruption or embedded EXIF payloads.
    
    Args:
        file_paths_json: JSON string array of absolute file paths.
    """
    import json
    from security import check_media_integrity
    
    try:
        paths = json.loads(file_paths_json)
        if not isinstance(paths, list): paths = [file_paths_json]
    except Exception:
        paths = [file_paths_json]
        
    results = []
    for p in paths:
        results.append(check_media_integrity(p))
            
    return json.dumps({"status": "media_scan_complete", "reports": results})


# NOTE: Duplicate web_search (DDG Instant Answer API) was removed in audit.
# The primary web_search (HTML scraper, line ~2337) is the active implementation.
# It returns real search results instead of the limited Instant Answer API.


def enable_memory_lock():
    """Paranoid memory lock: Instruct the OS not to swap/page our active RAM to disk.
    
    Also suppresses core dumps and Python faulthandler tracebacks to prevent
    mlockall circumvention via diagnostic file writes.
    """
    import platform
    import ctypes
    import logging
    logger = logging.getLogger("security_swap")
    
    # 1. Disable Python's internal fault handler traceback dumps
    # Prevents memory traversal and exposure during segfaults
    try:
        import faulthandler
        faulthandler.disable()
        logger.info("[SECURITY] Python faulthandler disabled — traceback dumps suppressed.")
    except Exception:
        pass
    
    # 2. Set core dump file size to 0 — prevents OS from writing crash diagnostics
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        logger.info("[SECURITY] Core dump file size set to 0 — OS crash dumps blocked.")
    except Exception:
        pass  # Windows or restricted environments
    
    # 3. Apply mlockall to pin memory to RAM
    try:
        MCL_CURRENT = 1
        MCL_FUTURE = 2
        
        if platform.system() == 'Darwin':
            libc = ctypes.cdll.LoadLibrary("/usr/lib/libc.dylib")
            if libc.mlockall(MCL_CURRENT | MCL_FUTURE) == 0:
                logger.info("🛡️  [SECURITY] macOS mlockall() engaged. Memory swap strictly disabled.")
            else:
                logger.warning("[SECURITY] macOS mlockall() dropped. Missing root entitlements?")
                
        elif platform.system() == 'Linux':
            libc = ctypes.CDLL("libc.so.6")
            if libc.mlockall(MCL_CURRENT | MCL_FUTURE) == 0:
                logger.info("🛡️  [SECURITY] Linux mlockall() engaged. Memory swap strictly disabled.")
            else:
                logger.warning("[SECURITY] Linux mlockall() dropped. Requires IPC_LOCK capability.")
    except Exception as e:
        logger.error(f"[SECURITY] Fault requesting memory lockdown: {e}")

# Run the MCP server
if __name__ == "__main__":
    enable_memory_lock()
    main()
    mcp.run()
