#!/usr/bin/env python3
"""Test async Langfuse flush to ensure it doesn't break the planner."""

import os
import sys
import time
import threading
from pathlib import Path

# Add the app to path
sys.path.insert(0, str(Path(__file__).parent / "images" / "slips_defender" / "defender"))

def test_sync_flush():
    """Test synchronous flush (current behavior)."""
    print("\n=== Testing SYNC flush ===")
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", "pk-lf-trident-defender"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", "sk-lf-trident-defender"),
            host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),
        )

        # Create a dummy trace
        trace = client.trace(name="test_sync", metadata={"test": "sync"})
        start = time.time()
        client.flush()
        elapsed = time.time() - start
        print(f"✓ SYNC flush completed in {elapsed:.2f}s")
        return elapsed
    except Exception as e:
        print(f"✗ SYNC flush failed: {e}")
        return None


def test_async_flush():
    """Test asynchronous flush (proposed behavior)."""
    print("\n=== Testing ASYNC flush ===")
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", "pk-lf-trident-defender"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", "sk-lf-trident-defender"),
            host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),
        )

        # Create a dummy trace
        trace = client.trace(name="test_async", metadata={"test": "async"})

        start = time.time()

        # Flush in background thread
        flush_thread = threading.Thread(target=client.flush, daemon=True)
        flush_thread.start()

        # Function returns immediately
        elapsed = time.time() - start
        print(f"✓ ASYNC flush returned in {elapsed:.4f}s (background thread running)")
        print(f"  - Thread is alive: {flush_thread.is_alive()}")

        # Wait a bit to see if it completes
        flush_thread.join(timeout=10)
        if flush_thread.is_alive():
            print(f"  ⚠ Thread still running after 10s (may timeout)")
        else:
            print(f"  ✓ Thread completed in background")

        return elapsed
    except Exception as e:
        print(f"✗ ASYNC flush failed: {e}")
        return None


def test_async_flush_with_timeout():
    """Test async flush with a timeout safeguard."""
    print("\n=== Testing ASYNC flush with timeout safeguard ===")
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", "pk-lf-trident-defender"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", "sk-lf-trident-defender"),
            host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),
        )

        # Create a dummy trace
        trace = client.trace(name="test_async_timeout", metadata={"test": "async_timeout"})

        start = time.time()

        # Flush with timeout in background
        def flush_with_timeout():
            try:
                client.flush()
            except Exception as e:
                print(f"  ⚠ Background flush error (non-critical): {e}")

        flush_thread = threading.Thread(target=flush_with_timeout, daemon=True)
        flush_thread.start()

        elapsed = time.time() - start
        print(f"✓ ASYNC flush with timeout returned in {elapsed:.4f}s")

        # Give it a moment to start
        time.sleep(0.1)

        if flush_thread.is_alive():
            print(f"  → Flush still running in background (expected)")

        # Check completion
        flush_thread.join(timeout=5)
        if flush_thread.is_alive():
            print(f"  ⚠ Flush incomplete after 5s (continuing anyway)")
        else:
            print(f"  ✓ Flush completed in {time.time() - start:.2f}s total")

        return elapsed
    except Exception as e:
        print(f"✗ ASYNC flush with timeout failed: {e}")
        return None


def test_batch_flush():
    """Test batching multiple traces before flushing."""
    print("\n=== Testing BATCH flush (5 traces) ===")
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", "pk-lf-trident-defender"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", "sk-lf-trident-defender"),
            host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),
        )

        # Create multiple traces without flushing
        for i in range(5):
            trace = client.trace(name=f"test_batch_{i}", metadata={"batch": True})

        start = time.time()
        client.flush()
        elapsed = time.time() - start
        print(f"✓ BATCH flush (5 traces) completed in {elapsed:.2f}s")
        print(f"  → Average per trace: {elapsed/5:.4f}s")
        return elapsed
    except Exception as e:
        print(f"✗ BATCH flush failed: {e}")
        return None


def test_planner_integration():
    """Test that the planner still works with async flush."""
    print("\n=== Testing planner integration ===")
    try:
        from app.planner import IncidentPlanner, PlannerConfig

        config = PlannerConfig(
            model=os.getenv("LLM_MODEL", "gemma4"),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "http://10.0.0.49:8080/p/diego/v1"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            langfuse_enabled=True,
            langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            langfuse_host=os.getenv("LANGFUSE_HOST"),
        )

        planner = IncidentPlanner(config)

        # Test alert
        test_alert = """
        2026-05-08T17:14:16+00:00 8.8.8.8 unknown (unknown) targeting unknown -
        Detected A DNS TXT answer with high entropy. query: test.com answer: "high_entropy_data"
        entropy: 5.58 Threat level: medium.
        """

        print("  → Sending test alert to planner...")
        start = time.time()

        result = planner.plan(test_alert.strip())

        elapsed = time.time() - start
        print(f"✓ Planner returned in {elapsed:.2f}s")
        print(f"  → Has executor_host_ip: {bool(result.get('executor_host_ip'))}")
        print(f"  → Has plan: {bool(result.get('plan'))}")
        print(f"  → Plan length: {len(result.get('plan', ''))} chars")

        return elapsed
    except Exception as e:
        print(f"✗ Planner integration failed: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    print("=" * 60)
    print("Langfuse Async Flush Test Suite")
    print("=" * 60)

    # Load env if needed
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        # Don't actually load here - let the modules read from os.environ
        print(f"\nLoading .env from: {env_path}")

    # Run tests
    results = {}

    results["sync"] = test_sync_flush()
    results["async"] = test_async_flush()
    results["async_timeout"] = test_async_flush_with_timeout()
    results["batch"] = test_batch_flush()
    results["planner"] = test_planner_integration()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for name, value in results.items():
        if value is not None:
            print(f"  {name:20s}: {value:.4f}s")
        else:
            print(f"  {name:20s}: FAILED")

    if results["sync"] and results["async"]:
        speedup = results["sync"] / results["async"]
        print(f"\n  → Async flush speedup: {speedup:.1f}x faster")

    print("\n" + "=" * 60)
