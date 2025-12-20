#!/usr/bin/env python3
"""Stress test for freetser client connections.

Run separately from regular tests:
    uv run python tests/stress_test.py

Requires the test server to be running:
    uv run python tests/main.py
"""

import argparse
import concurrent.futures
import statistics
import time

from freetser import client


def run_sequential_test(conn: client.Connection, num_requests: int) -> dict:
    """Run sequential requests on a single connection."""
    start = time.perf_counter()

    for i in range(num_requests):
        response = conn.get(f"/test/{i}")
        assert response.status_code == 200

    elapsed = time.perf_counter() - start
    rps = num_requests / elapsed

    return {
        "type": "sequential",
        "requests": num_requests,
        "elapsed": elapsed,
        "rps": rps,
    }


def run_parallel_test(
    address: client.Address,
    num_requests: int,
    num_connections: int,
) -> dict:
    """Run parallel requests using multiple connections."""
    connections = [client.Connection(address) for _ in range(num_connections)]
    completed = 0
    errors = 0

    def make_request(i: int) -> bool:
        conn = connections[i % num_connections]
        try:
            response = conn.get(f"/test/{i}")
            return response.status_code == 200
        except Exception:
            return False

    start = time.perf_counter()

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_connections) as executor:
        futures = [executor.submit(make_request, i) for i in range(num_requests)]
        for f in concurrent.futures.as_completed(futures):
            if f.result():
                completed += 1
            else:
                errors += 1

    elapsed = time.perf_counter() - start
    rps = completed / elapsed if elapsed > 0 else 0

    for conn in connections:
        conn.close()

    return {
        "type": "parallel",
        "requests": num_requests,
        "completed": completed,
        "errors": errors,
        "connections": num_connections,
        "elapsed": elapsed,
        "rps": rps,
    }


def run_latency_test(conn: client.Connection, num_requests: int) -> dict:
    """Measure individual request latencies."""
    latencies = []

    for i in range(num_requests):
        start = time.perf_counter()
        response = conn.get(f"/test/{i}")
        elapsed = time.perf_counter() - start

        if response.status_code == 200:
            latencies.append(elapsed * 1000)  # Convert to ms

    return {
        "type": "latency",
        "requests": num_requests,
        "min_ms": min(latencies),
        "max_ms": max(latencies),
        "avg_ms": statistics.mean(latencies),
        "median_ms": statistics.median(latencies),
        "p95_ms": sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
        "p99_ms": sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Stress test freetser client")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument("--requests", type=int, default=1000, help="Number of requests")
    parser.add_argument("--connections", type=int, default=4, help="Number of parallel connections")
    args = parser.parse_args()

    address = client.TcpAddress(args.host, args.port)

    print(f"Stress testing {args.host}:{args.port}")
    print(f"Requests: {args.requests}, Connections: {args.connections}")
    print("-" * 60)

    # Warm up
    print("Warming up...")
    with client.Connection(address) as conn:
        for _ in range(10):
            conn.get("/test")

    # Sequential test (single connection)
    print("\nSequential test (1 connection)...")
    with client.Connection(address) as conn:
        result = run_sequential_test(conn, args.requests)
        print(f"  Requests: {result['requests']}")
        print(f"  Time: {result['elapsed']:.2f}s")
        print(f"  Throughput: {result['rps']:.1f} req/s")

    # Parallel test
    print(f"\nParallel test ({args.connections} connections)...")
    result = run_parallel_test(address, args.requests, args.connections)
    print(f"  Requests: {result['requests']}")
    print(f"  Completed: {result['completed']}")
    print(f"  Errors: {result['errors']}")
    print(f"  Time: {result['elapsed']:.2f}s")
    print(f"  Throughput: {result['rps']:.1f} req/s")

    # Latency test
    print("\nLatency test (single connection)...")
    with client.Connection(address) as conn:
        result = run_latency_test(conn, min(args.requests, 100))
        print(f"  Min: {result['min_ms']:.2f}ms")
        print(f"  Max: {result['max_ms']:.2f}ms")
        print(f"  Avg: {result['avg_ms']:.2f}ms")
        print(f"  Median: {result['median_ms']:.2f}ms")
        print(f"  P95: {result['p95_ms']:.2f}ms")
        print(f"  P99: {result['p99_ms']:.2f}ms")

    # Connection count comparison
    print("\nConnection count comparison:")
    for num_conn in [1, 2, 4, 8]:
        result = run_parallel_test(address, args.requests, num_conn)
        print(f"  {num_conn} connections: {result['rps']:.1f} req/s")

    print("\nDone!")


if __name__ == "__main__":
    main()
