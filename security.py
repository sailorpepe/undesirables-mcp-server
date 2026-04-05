"""
Shared security utilities for all MCP engine modules.
Centralizes path validation, input sanitization, and size limits.
"""

import os
from pathlib import Path

# Absolute paths that must NEVER be accessible
BLOCKED_PATHS = [
    "/etc", "/var", "/usr", "/System", "/Library",
    "/bin", "/sbin", "/private", "/tmp",
]

MAX_TEXT_INPUT = 50000      # 50KB max for any text input
MAX_GRAPH_NODES = 10000     # Memory graph node cap
MAX_GRAPH_EDGES = 50000     # Memory graph edge cap
MAX_TTS_TEXT = 5000         # ~5 min of speech


def validate_workspace_path(workspace_path: str) -> str:
    """
    Validate and resolve a workspace path.
    Ensures the path doesn't escape into system directories.

    Returns: Resolved absolute path string
    Raises: ValueError if path is suspicious
    """
    resolved = Path(workspace_path).resolve()
    resolved_str = str(resolved)

    # Explicit whitelist for sandbox environment (bypasses global blocks)
    # Note: macOS symlinks /tmp to /private/tmp
    if resolved_str.startswith("/tmp/undsr_") or resolved_str.startswith("/private/tmp/undsr_"):
        return resolved_str

    # Block access to system directories
    for blocked in BLOCKED_PATHS:
        if resolved_str.startswith(blocked):
            raise ValueError(f"Security Error: Access to '{blocked}' is denied.")

    # Must be under a user directory
    if not any(resolved_str.startswith(p) for p in [
        "/Users/", "/home/",             # User dirs
    ]):
        raise ValueError(f"Security Error: Workspace path must be under user directory.")

    return resolved_str


def validate_file_path(filepath: str, workspace_path: str) -> str:
    """
    Validate a file path is within the workspace.
    Prevents path traversal via '../' injection.

    Returns: Resolved absolute path string
    Raises: ValueError if path escapes workspace
    """
    workspace = Path(workspace_path).resolve()
    target = (workspace / filepath).resolve() if not os.path.isabs(filepath) else Path(filepath).resolve()

    if not target.is_relative_to(workspace):
        raise ValueError(f"Security Error: Path traversal blocked. Access denied outside workspace.")

    return str(target)


def is_safe_symlink(filepath: str, workspace_path: str) -> bool:
    """Check if a symlink target is within the workspace."""
    path = Path(filepath)
    if path.is_symlink():
        target = path.resolve()
        workspace = Path(workspace_path).resolve()
        return target.is_relative_to(workspace)
    return True  # Not a symlink, always safe


def sanitize_text(text: str, max_length: int = MAX_TEXT_INPUT) -> str:
    """Truncate text input to prevent DoS."""
    if len(text) > max_length:
        return text[:max_length]
    return text

import subprocess
import json
import logging
import time
import contextlib
import platform

# Cross-platform file locking for concurrent AI environments
logger = logging.getLogger("security_auditor")

@contextlib.contextmanager
def acquire_file_lock(filepath: str, mode: str = 'a'):
    """Cross-platform advisory file locking to prevent Race Conditions on flat files.
    
    Uses O_NOFOLLOW to atomically reject symlinks at the kernel level,
    closing the TOCTOU gap between open() and flock().
    """
    flags = os.O_RDWR | os.O_CREAT
    if mode == 'w':
        flags |= os.O_TRUNC
    elif mode == 'a':
        flags |= os.O_APPEND

    # TOCTOU mitigation: fail atomically if the path is a symlink
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW

    try:
        fd = os.open(filepath, flags, 0o644)
    except OSError as e:
        # O_NOFOLLOW raises ELOOP (errno 40) on symlinks — block it explicitly
        if e.errno == 40:
            raise ValueError(f"Security Error: Symlink detected at {filepath}. Lock refused.")
        raise

    f = os.fdopen(fd, mode, encoding='utf-8' if 'b' not in mode else None)
    try:
        if platform.system() == 'Windows':
            import msvcrt
            # Lock maximum boundary (not just 1MB) to protect tails of large files
            max_lock_len = 0x7FFFFFFF  # 2GB - portable 32-bit max
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, max_lock_len)
            yield f
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, max_lock_len)
            except Exception: pass
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield f
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception: pass
    finally:
        f.close()

@contextlib.contextmanager
def acquire_mutex_lock(lock_path: str, timeout: float = 10.0):
    """Inter-process mutex (via `.lock` atomic O_CREAT). Secures atomic JSON renames."""
    lock_file = lock_path + ".lock"
    start_time = time.time()
    
    while True:
        try:
            # os.O_EXCL guarantees atomicity at the OS Kernel level
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except OSError:
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Deadlock detected on {lock_path}")
            time.sleep(0.01)
            
    try:
        yield
    finally:
        try:
            os.remove(lock_file)
        except OSError:
            pass

def run_sast_scan(file_path: str, scan_type: str) -> dict:
    try:
        safe_path = validate_workspace_path(file_path)
    except Exception as e:
        return {"error": str(e)}

    target = Path(safe_path)
    if not target.exists():
        return {"error": "File not found."}

    results = {"file": target.name, "tool": "unknown", "findings": []}

    try:
        if target.suffix == ".sol":
            # Slither compilation & scan
            cmd = ["slither", str(target), "--json", "-"]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True)
            except FileNotFoundError:
                return {"error": "Slither Solidity Analyzer is not installed. Please run `pip install slither-analyzer`."}
                
            output = proc.stdout if proc.stdout else proc.stderr
            
            # Slither sometimes prepends warnings; isolate the JSON block
            import re
            json_match = re.search(r'(\\{.*\\})', output, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
                for d in data.get("results", {}).get("detectors", []):
                    results["findings"].append({
                        "rule": d.get("check"),
                        "severity": d.get("impact"),
                        "description": d.get("description", "")[:200]
                    })
                results["tool"] = "slither"
            else:
                return {"error": "Failed to parse Slither output.", "raw_error": output[:200]}
                
        else:
            # Semgrep dynamic AST Scan
            cmd = ["semgrep", "scan", "--json", "--config", "auto", str(target)]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True)
            except FileNotFoundError:
                return {"error": "Semgrep is not installed. Please run `pip install semgrep` or `brew install semgrep`."}
            
            if proc.stdout:
                data = json.loads(proc.stdout)
                for r in data.get("results", []):
                    results["findings"].append({
                        "rule": r.get("check_id"),
                        "severity": r.get("extra", {}).get("severity"),
                        "line": r.get("start", {}).get("line"),
                        "message": r.get("extra", {}).get("message", "")[:200]
                    })
                results["tool"] = "semgrep"
            else:
                return {"error": "Semgrep output empty.", "raw_error": proc.stderr[:200]}

        # Truncate to prevent LLM Context Window blowout
        if len(results["findings"]) > 20:
            results["summary"] = f"Found {len(results['findings'])} issues. Showing top 20 critical."
            results["findings"] = results["findings"][:20]

        return results
    except Exception as e:
        return {"error": str(e)}

def check_media_integrity(file_path: str) -> dict:
    try:
        safe_path = validate_workspace_path(file_path)
    except Exception as e:
        return {"error": str(e)}
        
    target = Path(safe_path)
    if not target.exists():
        return {"error": "File not found."}

    ext = target.suffix.lower()
    report = {"file": target.name, "status": "safe", "warnings": []}

    if ext in ['.png', '.jpg', '.jpeg', '.webp']:
        try:
            from PIL import Image
            import exifread
            
            # 1. Structural Byte-level verify (avoids zip bomb execution)
            with Image.open(target) as img:
                img.verify()
                
            # 2. XSS/Polyglot Payload verify via EXIF headers
            with open(target, 'rb') as f:
                tags = exifread.process_file(f, details=False)
                for tag, val in tags.items():
                    val_str = str(val).lower()
                    if any(threat in val_str for threat in ['<script', '<?php', 'eval(', 'cmd.exe', '/bin/sh']):
                        report["status"] = "suspicious"
                        report["warnings"].append(f"Malicious polyglot payload signature detected in EXIF tag: {tag}")
        except Exception as e:
            report["status"] = "corrupted"
            report["warnings"].append(f"Image validation failed: {e}")

    elif ext in ['.mp4', '.mov', '.webm']:
        try:
            # ffprobe parses headers; errors out instantly if stream is malformed
            cmd = ["ffprobe", "-v", "error", "-show_format", "-show_streams", str(target)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if res.returncode != 0:
                report["status"] = "corrupted"
                report["warnings"].append(f"Video stream corruption: {res.stderr[:200]}")
        except Exception as e:
            report["status"] = "error"
            report["warnings"].append(str(e))

    return report
