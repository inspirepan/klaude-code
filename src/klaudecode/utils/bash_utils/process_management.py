import os
import signal
import subprocess
import time


class BashProcessManager:
    @classmethod
    def kill_process_tree(cls, pid: int):
        """Kill a process and all its children with improved reliability"""
        try:
            # Method 1: Use process group kill if available
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                time.sleep(0.1)
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                return  # If successful, we're done
            except (ProcessLookupError, OSError):
                pass  # Fall back to individual process killing

            # Method 2: Recursively kill children using pgrep
            children = []
            try:
                # Use pgrep to find all descendants, not just direct children
                output = subprocess.check_output(['pgrep', '-P', str(pid)], stderr=subprocess.DEVNULL, timeout=2)
                children = [int(child_pid) for child_pid in output.decode().strip().split('\n') if child_pid]
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                # No children found or pgrep failed
                pass

            # Kill children first (recursive)
            for child_pid in children:
                cls.kill_process_tree(child_pid)

            # Method 3: Kill the main process
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.1)
                # Check if process is still alive
                try:
                    os.kill(pid, 0)  # Check if process exists
                    os.kill(pid, signal.SIGKILL)  # Force kill if still alive
                except ProcessLookupError:
                    pass  # Process already dead
            except ProcessLookupError:
                # Process already dead
                pass

        except Exception:
            # Last resort: try to kill with SIGKILL directly
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass  # Process might already be dead
