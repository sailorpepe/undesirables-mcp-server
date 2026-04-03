"""Boot stub for 3D generation engine (TripoSR)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Direct import — run_3d.py is the readable entry point (not compiled)
import run_3d

if __name__ == "__main__":
    run_3d.main()
