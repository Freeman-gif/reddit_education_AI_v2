"""Stage 4: Run emotion analysis + stance detection on all unprocessed comments.
Uses system Python (not venv) for ROCm GPU acceleration on Radeon 8060S iGPU.
Run with: python3 scripts/run_stage4.py (NOT .venv/bin/python3)
"""

import os
import sys
sys.path.insert(0, "/home/freeman/reddit_scrap")
os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "11.0.0")

from analysis.emotions import run_emotions, run_stance

print("=== Stage 4: Emotion Analysis ===")
run_emotions(callback=print)

print("\n=== Stage 4: Stance Detection ===")
run_stance(callback=print)

print("\n=== Stage 4 Complete ===")
