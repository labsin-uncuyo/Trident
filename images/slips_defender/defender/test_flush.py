#!/usr/bin/env python3
"""Test Langfuse flush performance - run inside defender container."""

import os
import sys
import time
import threading

print("=" * 60)
print("Langfuse Async Flush Test")
print("=" * 60)

# Use env vars or defaults
os.environ.setdefault('LANGFUSE_PUBLIC_KEY', 'pk-lf-trident-defender')
os.environ.setdefault('LANGFUSE_SECRET_KEY', 'sk-lf-trident-defender')
os.environ.setdefault('LANGFUSE_HOST', 'http://host.docker.internal:3000')

from langfuse import Langfuse

client = Langfuse(
    public_key=os.environ['LANGFUSE_PUBLIC_KEY'],
    secret_key=os.environ['LANGFUSE_SECRET_KEY'],
    host=os.environ['LANGFUSE_HOST'],
)

results = {}

# Test 1: Sync flush
print("\n[Test 1] SYNC flush (current behavior)")
print("-" * 40)
trace1 = client.trace(name='test_sync', metadata={'test': 'sync'})
start = time.time()
try:
    client.flush()
    elapsed = time.time() - start
    results['sync'] = elapsed
    print(f"✓ Completed in {elapsed:.4f}s")
except Exception as e:
    print(f"✗ Failed: {e}")
    results['sync'] = None

# Test 2: Async flush
print("\n[Test 2] ASYNC flush (proposed behavior)")
print("-" * 40)
trace2 = client.trace(name='test_async', metadata={'test': 'async'})
start = time.time()
flush_thread = threading.Thread(target=client.flush, daemon=True)
flush_thread.start()
elapsed = time.time() - start
results['async_return'] = elapsed
print(f"✓ Returned in {elapsed:.4f}s (background thread running)")
print(f"  → Thread is alive: {flush_thread.is_alive()}")

# Wait for thread with timeout
flush_thread.join(timeout=10)
if flush_thread.is_alive():
    print(f"  ⚠ Thread still running after 10s timeout")
    results['async_complete'] = None
else:
    total = time.time() - start
    results['async_complete'] = total
    print(f"  ✓ Thread completed in {total:.4f}s total")

# Test 3: Batch flush
print("\n[Test 3] BATCH flush (5 traces, 1 flush)")
print("-" * 40)
for i in range(5):
    client.trace(name=f'test_batch_{i}', metadata={'batch': True})

start = time.time()
try:
    client.flush()
    elapsed = time.time() - start
    results['batch'] = elapsed
    print(f"✓ Completed in {elapsed:.4f}s")
    print(f"  → Average per trace: {elapsed/5:.4f}s")
except Exception as e:
    print(f"✗ Failed: {e}")
    results['batch'] = None

# Summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

for name, value in results.items():
    if value is not None:
        print(f"  {name:20s}: {value:.4f}s")
    else:
        print(f"  {name:20s}: FAILED")

if results.get('sync') and results.get('async_return'):
    speedup = results['sync'] / results['async_return']
    print(f"\n  → Async flush is {speedup:.1f}x faster to return")

print("\n" + "=" * 60)
