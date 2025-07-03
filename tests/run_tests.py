#!/usr/bin/env python
"""
Test runner script for klaude-code.

Usage:
    python run_tests.py              # Run all tests
    python run_tests.py tools        # Run only tools tests
    python run_tests.py -v           # Run with verbose output
    python run_tests.py --cov        # Run with coverage report
"""

import sys
import subprocess
from pathlib import Path

def main():
    # Default pytest arguments
    args = ["pytest"]
    
    # Add project root to Python path
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root / "src"))
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        if "--cov" in sys.argv:
            args.extend(["--cov=klaudecode", "--cov-report=html", "--cov-report=term"])
            sys.argv.remove("--cov")
        
        # Add remaining arguments
        args.extend(sys.argv[1:])
    
    # Run pytest
    result = subprocess.run(args, cwd=project_root)
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()