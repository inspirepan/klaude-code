import sys
from pathlib import Path


def setup_src_path():
    ROOT = Path(__file__).resolve().parents[1]
    SRC_DIR = ROOT / "src"
    if SRC_DIR.is_dir() and str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))


setup_src_path()
