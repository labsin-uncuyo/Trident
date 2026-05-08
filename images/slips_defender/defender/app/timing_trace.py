"""
Fine-grained timing trace utilities for performance analysis.

Outputs structured timing spans compatible with Chrome DevTools Trace format
and custom graphing tools.
"""

import json
import os
import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Span:
    """A single timing span (event)."""
    name: str
    category: str
    start_ms: float
    duration_ms: float
    args: Dict[str, Any] = field(default_factory=dict)
    thread_id: int = field(default_factory=lambda: threading.get_ident())
    process_id: int = field(default_factory=lambda: os.getpid())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "name": self.name,
            "cat": self.category,
            "ph": "X",  # Complete event
            "ts": self.start_ms * 1000,  # Microseconds for Chrome DevTools
            "dur": self.duration_ms * 1000,  # Microseconds for Chrome DevTools
            "pid": self.process_id,
            "tid": self.thread_id,
            "args": self.args,
        }

    def to_simple_dict(self) -> Dict[str, Any]:
        """Convert to simple JSON format for custom graphing."""
        return {
            "name": self.name,
            "category": self.category,
            "start_ms": self.start_ms,
            "duration_ms": self.duration_ms,
            "end_ms": self.start_ms + self.duration_ms,
            "timestamp": datetime.fromtimestamp(self.start_ms / 1000, tz=timezone.utc).isoformat(),
            "thread_id": self.thread_id,
            "args": self.args,
        }


class TimingTracer:
    """Collects and writes timing spans."""

    def __init__(self, output_path: Optional[Path] = None):
        self._spans: List[Span] = []
        self._start_time = time.time()
        self._lock = threading.Lock()
        self.output_path = output_path

    @classmethod
    def for_component(cls, component: str, run_id: Optional[str] = None) -> "TimingTracer":
        """Create a tracer with automatic output path."""
        run_id = run_id or os.getenv("RUN_ID", "run")
        output_dir = Path("/outputs") / run_id / "traces"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{component}_timing.json"
        return cls(output_path)

    @contextmanager
    def span(self, name: str, category: str = "general", **args):
        """Context manager for timing a block of code.

        Yields a MutableSpan placeholder that can be updated during the context.
        """
        start = time.time()
        start_ms = (start - self._start_time) * 1000
        thread_id = threading.get_ident()
        process_id = os.getpid()

        # Mutable placeholder for args that can be updated during the context
        @dataclass
        class MutableSpan:
            args: Dict[str, Any]

        mutable_span = MutableSpan(args=args)

        try:
            yield mutable_span
        finally:
            end = time.time()
            duration_ms = (end - start) * 1000

            span = Span(
                name=name,
                category=category,
                start_ms=start_ms,
                duration_ms=duration_ms,
                args=mutable_span.args,
                thread_id=thread_id,
                process_id=process_id,
            )

            with self._lock:
                self._spans.append(span)

    def add_span(self, name: str, start_ms: float, duration_ms: float,
                 category: str = "general", **args) -> None:
        """Manually add a span."""
        span = Span(
            name=name,
            category=category,
            start_ms=start_ms,
            duration_ms=duration_ms,
            args=args,
        )
        with self._lock:
            self._spans.append(span)

    def write(self, format: str = "simple") -> None:
        """Write traces to file."""
        if not self.output_path:
            return

        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if format == "chrome":
            # Chrome DevTools Trace format
            trace_data = {
                "traceEvents": [span.to_dict() for span in self._spans],
                "displayTimeUnit": "ms",
            }
        else:
            # Simple format for custom graphing
            trace_data = {
                "component": self.output_path.stem.replace("_timing", ""),
                "run_id": os.getenv("RUN_ID", "run"),
                "session_start": datetime.fromtimestamp(self._start_time, tz=timezone.utc).isoformat(),
                "spans": [span.to_simple_dict() for span in self._spans],
                "summary": self._compute_summary(),
            }

        with open(self.output_path, "w") as f:
            json.dump(trace_data, f, indent=2)

    def _compute_summary(self) -> Dict[str, Any]:
        """Compute summary statistics."""
        if not self._spans:
            return {}

        # Group by name
        by_name: Dict[str, List[Span]] = {}
        for span in self._spans:
            by_name.setdefault(span.name, []).append(span)

        summary = {}
        for name, spans in by_name.items():
            durations = [s.duration_ms for s in spans]
            summary[name] = {
                "count": len(spans),
                "total_ms": sum(durations),
                "avg_ms": sum(durations) / len(durations),
                "min_ms": min(durations),
                "max_ms": max(durations),
            }

        # Overall stats
        all_durations = [s.duration_ms for s in self._spans]
        summary["_overall"] = {
            "total_spans": len(self._spans),
            "total_duration_ms": sum(all_durations),
            "avg_duration_ms": sum(all_durations) / len(all_durations) if all_durations else 0,
        }

        return summary

    def get_spans(self) -> List[Span]:
        """Get all collected spans."""
        with self._lock:
            return list(self._spans)

    def clear(self) -> None:
        """Clear all spans."""
        with self._lock:
            self._spans.clear()


# Global tracer instances
_tracers: Dict[str, TimingTracer] = {}
_tracer_lock = threading.Lock()


def get_tracer(component: str) -> TimingTracer:
    """Get or create a tracer for a component."""
    with _tracer_lock:
        if component not in _tracers:
            _tracers[component] = TimingTracer.for_component(component)
        return _tracers[component]


def write_all_traces() -> None:
    """Write all traces to their respective files."""
    with _tracer_lock:
        for tracer in _tracers.values():
            tracer.write()


@contextmanager
def trace_span(name: str, component: str = "default", category: str = "general", **args):
    """Context manager for tracing with auto-component lookup."""
    tracer = get_tracer(component)
    with tracer.span(name, category, component=component, **args):
        yield


def log_timing(component: str, name: str, duration_ms: float,
               category: str = "general", **args) -> None:
    """Log a timing event manually."""
    tracer = get_tracer(component)
    elapsed = (time.time() - tracer._start_time) * 1000
    tracer.add_span(name, elapsed - duration_ms, duration_ms, category, component=component, **args)
