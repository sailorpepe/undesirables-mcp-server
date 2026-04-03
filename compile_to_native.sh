#!/bin/bash

# Nuitka Compilation Pipeline for MCP Server Proprietary Logic
# This script compiles standard readable Python files into native C-compiled
# shared library binaries (.so files) using Nuitka for maximum protection.

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Run python3 -m venv .venv and install requirements."
    exit 1
fi

echo "Activating virtual environment..."
source .venv/bin/activate

echo "Checking Nuitka installation..."
pip show nuitka > /dev/null 2>&1 || pip install nuitka

PROPRIETARY_MODULES=(
    "server.py"
    "executor.py"
    "rag_engine.py"
    "memory_graph.py"
    "voice_engine.py"
    "three_d_engine.py"
    "emotion_engine.py"
    "tcg_oracle.py"
    "ebay_oracle.py"
    "run_3d.py"
    "run_bark.py"
    "security.py"
)

mkdir -p build_py_backup

for MODULE in "${PROPRIETARY_MODULES[@]}"; do
    if [ -f "$MODULE" ]; then
        echo "Compiling $MODULE to native C module..."
        python -m nuitka --module "$MODULE" --remove-output
        
        # Move the source file to backup so the app is forced to run the compiled binary
        echo "Moving $MODULE to build_py_backup/"
        mv "$MODULE" build_py_backup/
    else
        echo "Skipping $MODULE (already compiled/missing)"
    fi
done

echo "--------------------------------------------------------"
echo "✅ Compilation Complete."
echo "Your proprietary logic is now protected as native binaries."
echo "Only execute_tool.py (entry point) remains as readable source."
echo "--------------------------------------------------------"
