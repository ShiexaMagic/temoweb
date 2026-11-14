"""Vercel entry point: serves the editor (/admin and /api/*) as a serverless function."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402,F401
