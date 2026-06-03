import sys
from pathlib import Path

# Makes backend/ importable as root when pytest runs from resume-optimizer/
sys.path.insert(0, str(Path(__file__).parent.parent))
