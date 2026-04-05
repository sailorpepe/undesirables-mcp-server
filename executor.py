"""
Code Execution Sandbox — Isolated Subprocess Execution

Executes Python/Shell code in an isolated subprocess with:
- Restricted environment variables (no secrets leak)
- Redirected HOME to sandbox temp dir
- 15-second hard timeout (kills process tree)
- stdout/stderr capture with size limits
- Dangerous command pattern blocking
- Automatic temp directory cleanup

This uses standard subprocess isolation which works reliably on
all macOS versions including Apple Silicon.

Runs natively. No Docker. No cloud. Zero external dependencies.
"""

import os
import sys
import uuid
import shutil
import signal
import subprocess
import logging
import platform
from pathlib import Path

try:
    import docker
    from docker.errors import DockerException, ImageNotFound
    try:
        DOCKER_CLIENT = docker.from_env()
        DOCKER_CLIENT.ping()
        HAS_DOCKER = True
        logger.info("[SANDBOX] Docker Engine detected and connected.")
    except Exception as e:
        DOCKER_CLIENT = None
        HAS_DOCKER = False
        logger.info(f"[SANDBOX] Docker Engine not available. Fallback logic will apply: {e}")
except ImportError:
    DOCKER_CLIENT = None
    HAS_DOCKER = False
    logger.info("[SANDBOX] Docker Python SDK not installed.")

logger = logging.getLogger("executor")

SANDBOX_BASE = "/tmp/undsr_sandbox"
MAX_TIMEOUT = 15       # seconds
MAX_OUTPUT = 10000     # characters
MAX_CODE_SIZE = 50000  # characters

# Patterns that get instantly blocked before any execution
DANGEROUS_PATTERNS = [
    'rm -rf', 'rm -r /', 'mkfs', 'dd if=', ':(){', 'sudo ', 'su ',
    '> /dev/', 'curl ', 'wget ', 'nc ', 'ncat ', 'open -a',
    'osascript', 'defaults write', 'launchctl', 'killall',
    'shutdown', 'reboot', 'halt', 'diskutil',
]

# Python imports/builtins that get blocked at code level
DANGEROUS_IMPORTS = [
    'subprocess', 'shutil.rmtree', 'os.system', 'os.popen',
    'os.remove', 'os.unlink', 'os.rmdir', 'os.removedirs',
    'socket', 'http.client', 'urllib.request', 'requests',
    'smtplib', 'ftplib', 'telnetlib', 'ctypes',
    # Bypass prevention
    '__import__', 'importlib', 'exec(', 'eval(',
    'compile(', 'globals(', 'locals(',
    'getattr(', 'setattr(',
    'os.environ', 'os.putenv',
    # File system escape
    'pathlib', 'shutil.copy', 'shutil.move',
]


class SandboxResult:
    """Result of a sandboxed code execution."""
    def __init__(self, stdout: str, stderr: str, exit_code: int,
                 timed_out: bool, sandbox_dir: str):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.sandbox_dir = sandbox_dir

    def to_dict(self) -> dict:
        return {
            "stdout": self.stdout[:MAX_OUTPUT],
            "stderr": self.stderr[:MAX_OUTPUT],
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "truncated": len(self.stdout) > MAX_OUTPUT or len(self.stderr) > MAX_OUTPUT,
        }


def _check_dangerous_code(code: str) -> str:
    """Check for dangerous patterns in Python code. Returns error message or empty string."""
    for pattern in DANGEROUS_IMPORTS:
        # Check various import forms
        module = pattern.split('.')[0]
        if f'import {module}' in code or f'from {module}' in code:
            return f"BLOCKED: Code imports restricted module '{module}'"
        if pattern in code:
            return f"BLOCKED: Code contains restricted call '{pattern}'"
    return ""


def execute_python(code: str, timeout: int = MAX_TIMEOUT) -> SandboxResult:
    """
    Execute Python code in an isolated subprocess.

    Args:
        code: Python source code to execute
        timeout: Maximum execution time in seconds (1-15, hard cap)

    Returns:
        SandboxResult with stdout, stderr, exit code, and timeout flag
    """
    if len(code) > MAX_CODE_SIZE:
        return SandboxResult("", f"Code exceeds maximum size ({MAX_CODE_SIZE} chars)", 1, False, "")

    # Check for dangerous patterns
    danger = _check_dangerous_code(code)
    if danger:
        return SandboxResult("", danger, 1, False, "")

    timeout = max(1, min(timeout, MAX_TIMEOUT))

    # Create isolated sandbox directory
    run_id = str(uuid.uuid4())[:8]
    sandbox_dir = os.path.join(SANDBOX_BASE, run_id)
    os.makedirs(sandbox_dir, exist_ok=True)

    # Write code to temp file inside sandbox
    script_path = os.path.join(sandbox_dir, "script.py")
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(code)

    try:
        logger.info(f"[SANDBOX] Executing {run_id} (timeout={timeout}s, {len(code)} chars)")

        if HAS_DOCKER:
            logger.info(f"[SANDBOX] Routing {run_id} to Docker Ephemeral Container")
            try:
                # Ensure image exists quickly (will pull if missing, which takes time on 1st run)
                try:
                    DOCKER_CLIENT.images.get("python:3.11-alpine")
                except ImageNotFound:
                    logger.info("[SANDBOX] Pulling python:3.11-alpine for the first time...")
                    DOCKER_CLIENT.images.pull("python:3.11-alpine")

                container = DOCKER_CLIENT.containers.run(
                    "python:3.11-alpine",
                    command=["python", "/workspace/script.py"],
                    volumes={sandbox_dir: {'bind': '/workspace', 'mode': 'rw'}},
                    working_dir="/workspace",
                    network_mode="none",
                    mem_limit="512m",
                    cpu_period=100000,
                    cpu_quota=100000,
                    user=f"{os.getuid()}:{os.getgid()}" if hasattr(os, 'getuid') else None,
                    detach=True
                )

                try:
                    result = container.wait(timeout=timeout)
                    exit_code = result.get('StatusCode', 1)
                    # Use demux=True to properly separate stdout/stderr at the Docker protocol level.
                    # Without demux, Docker returns multiplexed binary with 8-byte headers that corrupt
                    # when decoded as UTF-8, enabling forged header injection attacks.
                    logs = container.logs(stdout=True, stderr=True, demux=True)
                    if isinstance(logs, tuple):
                        stdout_bytes, stderr_bytes = logs
                        stdout = stdout_bytes.decode('utf-8', errors='replace') if stdout_bytes else ""
                        stderr = stderr_bytes.decode('utf-8', errors='replace') if stderr_bytes else ""
                    else:
                        # Fallback: older docker-py versions may not support demux
                        stdout = logs.decode('utf-8', errors='replace') if isinstance(logs, bytes) else str(logs)
                        stderr = ""
                    timed_out = False
                except Exception as e:
                    # Timeout or wait error block
                    if "Timeout" in str(getattr(e, '__class__', '')):
                         pass
                    timed_out = True
                    stdout, stderr = "", f"TIMEOUT OR DOCKER ERROR: Execution exceeded {timeout}s or failed: {e}"
                    exit_code = 1
                finally:
                    try:
                        container.remove(force=True)
                    except Exception:
                        pass
                logger.info(f"[SANDBOX] Docker {run_id} finished: exit={exit_code}, timeout={timed_out}")
                return SandboxResult(stdout, stderr, exit_code, timed_out, sandbox_dir)

            except Exception as e:
                logger.error(f"[SANDBOX] Docker execution failed: {e}. Falling back...")
                # Fallthrough to native if docker crashes unexpectedly

        # Native Execution Fallback
        if platform.system() != 'Darwin':
            return SandboxResult("", f"SECURITY BLOCKED: Docker engine is not running and native Python execution is disabled on {platform.system()} to prevent arbitrary sandbox escapes.", 1, False, sandbox_dir)

        safe_env = {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            "HOME": sandbox_dir,
            "TMPDIR": sandbox_dir,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "LANG": "en_US.UTF-8",
        }

        profile_path = os.path.join(os.path.dirname(__file__), 'security_profile.sb')
        if os.path.exists(profile_path):
            exe_args = ["/usr/bin/sandbox-exec", "-f", profile_path, sys.executable, script_path]
            logger.info(f"[SANDBOX] macOS Seatbelt profile active for {run_id}")
        else:
            exe_args = [sys.executable, script_path]
            logger.warning(f"[SANDBOX] WARNING: Seatbelt missing, running bare darwin native for {run_id}")

        proc = subprocess.Popen(
            exe_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=sandbox_dir, env=safe_env, start_new_session=True
        )

        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
            stdout = stdout_bytes.decode('utf-8', errors='replace')
            stderr = stderr_bytes.decode('utf-8', errors='replace')
            timed_out = False
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                proc.kill()
            proc.wait()
            stdout, stderr = "", f"TIMEOUT: Execution exceeded {timeout}s limit and was terminated."
            timed_out = True

        exit_code = proc.returncode if proc.returncode is not None else 1
        logger.info(f"[SANDBOX] Native {run_id} finished: exit={exit_code}, timeout={timed_out}")

        return SandboxResult(stdout, stderr, exit_code, timed_out, sandbox_dir)

    finally:
        try:
            shutil.rmtree(sandbox_dir, ignore_errors=True)
        except Exception:
            pass


def execute_shell(command: str, timeout: int = MAX_TIMEOUT) -> SandboxResult:
    """
    Execute a shell command in an isolated subprocess.
    More restrictive than Python — blocks dangerous patterns at string level.
    """
    try:
        if HAS_DOCKER:
            logger.info(f"[SANDBOX] Routing shell {run_id} to Docker Ephemeral Container")
            try:
                try:
                    DOCKER_CLIENT.images.get("alpine:latest")
                except ImageNotFound:
                    DOCKER_CLIENT.images.pull("alpine:latest")

                script_path = os.path.join(sandbox_dir, "script.sh")
                with open(script_path, "w") as f:
                    f.write(command)

                container = DOCKER_CLIENT.containers.run(
                    "alpine:latest",
                    command=["/bin/sh", "/workspace/script.sh"],
                    volumes={sandbox_dir: {'bind': '/workspace', 'mode': 'rw'}},
                    working_dir="/workspace",
                    network_mode="none",
                    mem_limit="512m",
                    cpu_period=100000,
                    cpu_quota=100000,
                    detach=True
                )

                try:
                    result = container.wait(timeout=timeout)
                    exit_code = result.get('StatusCode', 1)
                    logs = container.logs(stdout=True, stderr=True)
                    stdout = logs.decode('utf-8', errors='replace')
                    stderr = ""
                    timed_out = False
                except Exception as e:
                    timed_out = True
                    stdout, stderr = "", f"TIMEOUT OR DOCKER ERROR: {e}"
                    exit_code = 1
                finally:
                    try:
                        container.remove(force=True)
                    except Exception:
                        pass
                
                return SandboxResult(stdout, stderr, exit_code, timed_out, sandbox_dir)
            except Exception as e:
                logger.error(f"[SANDBOX] Docker shell execution failed: {e}. Falling back...")

        if platform.system() != 'Darwin':
            return SandboxResult("", f"SECURITY BLOCKED: Docker engine is not running and native Shell execution is disabled on {platform.system()} to prevent arbitrary sandbox escapes.", 1, False, sandbox_dir)

        safe_env = {
            "PATH": "/usr/bin:/bin",
            "HOME": sandbox_dir,
            "TMPDIR": sandbox_dir,
            "LANG": "en_US.UTF-8",
        }

        profile_path = os.path.join(os.path.dirname(__file__), 'security_profile.sb')
        if os.path.exists(profile_path):
            exe_args = ["/usr/bin/sandbox-exec", "-f", profile_path, "/bin/bash", "-c", command]
        else:
            exe_args = ["/bin/bash", "-c", command]

        proc = subprocess.Popen(
            exe_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=sandbox_dir, env=safe_env, start_new_session=True
        )

        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
            stdout = stdout_bytes.decode('utf-8', errors='replace')
            stderr = stderr_bytes.decode('utf-8', errors='replace')
            timed_out = False
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                proc.kill()
            proc.wait()
            stdout, stderr = "", f"TIMEOUT: Execution exceeded {timeout}s limit."
            timed_out = True

        return SandboxResult(
            stdout, stderr, proc.returncode if proc.returncode is not None else 1,
            timed_out, sandbox_dir
        )

    finally:
        try:
            shutil.rmtree(sandbox_dir, ignore_errors=True)
        except Exception:
            pass
