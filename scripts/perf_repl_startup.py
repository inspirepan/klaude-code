"""
Performance test for REPL startup time.

Measures the time from script start to REPL ready for user input.
Run with: uv run scripts/perf_repl_startup.py
"""

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@dataclass
class TimingResult:
    """Single timing measurement."""

    label: str
    elapsed_ms: float  # Cumulative time from start
    delta_ms: float  # Time since last measurement


class StartupTimer:
    """Timer for measuring REPL startup phases."""

    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.last_time = self.t0
        self.results: list[TimingResult] = []

    def mark(self, label: str) -> float:
        """Record a timing point. Returns elapsed ms from start."""
        now = time.perf_counter()
        elapsed_ms = (now - self.t0) * 1000
        delta_ms = (now - self.last_time) * 1000
        self.last_time = now
        self.results.append(TimingResult(label, elapsed_ms, delta_ms))
        return elapsed_ms

    def print_summary(self) -> None:
        """Print timing summary."""
        print("\n" + "=" * 60)
        print("REPL Startup Timing Summary")
        print("=" * 60)
        print(f"{'Phase':<45} {'Cumulative':>10} {'Delta':>10}")
        print("-" * 65)
        for r in self.results:
            print(f"{r.label:<45} {r.elapsed_ms:>9.1f}ms {r.delta_ms:>9.1f}ms")
        print("-" * 65)
        if self.results:
            total = self.results[-1].elapsed_ms
            print(f"{'TOTAL':<45} {total:>9.1f}ms")
        print("=" * 60)

    def print_phase_breakdown(self) -> None:
        """Print phase breakdown with percentages."""
        if not self.results:
            return

        total = self.results[-1].elapsed_ms
        print("\nPhase Breakdown:")
        print("-" * 50)

        # Group phases
        phases = {
            "Module imports": 0.0,
            "Config & theme": 0.0,
            "Skill discovery": 0.0,
            "LLM clients": 0.0,
            "Async init": 0.0,
        }

        for r in self.results:
            if "Import" in r.label:
                phases["Module imports"] += r.delta_ms
            elif "config" in r.label.lower() or "theme" in r.label.lower():
                phases["Config & theme"] += r.delta_ms
            elif "Skill" in r.label:
                phases["Skill discovery"] += r.delta_ms
            elif "LLM" in r.label or "llm" in r.label:
                phases["LLM clients"] += r.delta_ms
            else:
                phases["Async init"] += r.delta_ms

        for phase, ms in phases.items():
            pct = (ms / total) * 100 if total > 0 else 0
            bar = "#" * int(pct / 2)
            print(f"{phase:<20} {ms:>8.1f}ms ({pct:>5.1f}%) {bar}")


async def run_startup_test() -> StartupTimer:
    """Run the full startup sequence with timing."""
    timer = StartupTimer()
    timer.mark("Script start")

    # Phase 1: Imports
    from klaude_code.cli.main import app  # type: ignore

    timer.mark("Import cli.main")

    from klaude_code.config import load_config
    from klaude_code.core.agent import DefaultModelProfileProvider
    from klaude_code.core.executor import Executor
    from klaude_code.core.manager import build_llm_clients
    from klaude_code.protocol import events, op
    from klaude_code.protocol.sub_agent import iter_sub_agent_profiles
    from klaude_code.ui.terminal.color import is_light_terminal_background

    timer.mark("Import runtime modules")

    from klaude_code import ui

    timer.mark("Import ui")

    # Phase 2: Configuration
    config = load_config()
    if config is None:
        raise RuntimeError("Failed to load config")
    timer.mark("load_config()")

    detected = is_light_terminal_background()
    theme = "light" if detected is True else "dark" if detected is False else None
    timer.mark("is_light_terminal_background()")

    # Phase 4: LLM clients
    enabled_sub_agents = [p.name for p in iter_sub_agent_profiles()]
    timer.mark("iter_sub_agent_profiles()")

    llm_clients = build_llm_clients(config, model_override=None, enabled_sub_agents=enabled_sub_agents)
    timer.mark("build_llm_clients()")

    # Phase 5: Create components
    event_queue: asyncio.Queue[events.Event] = asyncio.Queue()
    model_profile_provider = DefaultModelProfileProvider()
    executor = Executor(event_queue, llm_clients, model_profile_provider=model_profile_provider)
    timer.mark("Create Executor")

    display = ui.create_default_display(debug=False, theme=theme)
    timer.mark("create_default_display()")

    # Phase 6: Async initialization
    executor_task = asyncio.create_task(executor.start())
    timer.mark("executor.start() task")

    display_task = asyncio.create_task(display.consume_event_loop(event_queue))
    timer.mark("display.consume_event_loop() task")

    await executor.submit_and_wait(op.InitAgentOperation())
    timer.mark("InitAgentOperation completed")

    await event_queue.join()
    timer.mark("event_queue.join()")

    # Phase 7: Input provider
    from klaude_code.ui.modes.repl import build_repl_status_snapshot
    from klaude_code.ui.modes.repl.input_prompt_toolkit import REPLStatusSnapshot

    def _status_provider() -> REPLStatusSnapshot:
        return build_repl_status_snapshot(agent=None, update_message=None)

    input_provider = ui.PromptToolkitInput(status_provider=_status_provider)
    timer.mark("Create PromptToolkitInput")

    await input_provider.start()
    timer.mark("input_provider.start() - READY")

    # Cleanup
    await executor.stop()
    executor_task.cancel()
    await event_queue.put(events.EndEvent())
    try:
        await display_task
    except asyncio.CancelledError:
        pass

    return timer


def main() -> None:
    """Run the performance test."""
    print("REPL Startup Performance Test")
    print("-" * 40)

    timer = asyncio.run(run_startup_test())
    timer.print_summary()
    timer.print_phase_breakdown()


if __name__ == "__main__":
    main()
