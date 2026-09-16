"""Automated CI test gate for Agent Evaluation Benchmark Suite."""
from pathlib import Path
import pytest

from evals.harness import (
    evaluate_intent_routing,
    evaluate_injection_defense,
    evaluate_parameter_normalization,
    evaluate_token_savings,
    run_full_evaluation,
)


def test_intent_routing_benchmark() -> None:
    results = evaluate_intent_routing()
    assert results["total"] >= 50
    assert results["accuracy_pct"] >= 90.0, f"Routing accuracy fell below 90%: {results['accuracy_pct']}%"
    assert len(results["failures"]) == 0, f"Routing failures: {results['failures']}"


def test_injection_defense_benchmark(tmp_path: Path) -> None:
    results = evaluate_injection_defense(workspace_root=tmp_path)
    assert results["total"] >= 25
    assert results["defense_rate_pct"] == 100.0, f"Injection defense rate must be 100%: {results['defense_rate_pct']}%"
    assert len(results["failures"]) == 0, f"Injection leaks: {results['failures']}"


def test_parameter_normalization_benchmark() -> None:
    results = evaluate_parameter_normalization()
    assert results["total"] >= 30
    assert results["pass_rate_pct"] >= 95.0, f"Normalization pass rate fell below 95%: {results['pass_rate_pct']}%"
    assert len(results["failures"]) == 0, f"Normalization failures: {results['failures']}"


def test_token_savings_benchmark() -> None:
    savings = evaluate_token_savings()
    assert savings["average_reduction_pct"] >= 75.0, f"Expected >= 75% savings, got {savings['average_reduction_pct']}%"
    assert savings["average_saved_tokens"] > 1000


def test_full_evaluation_suite() -> None:
    report = run_full_evaluation()
    assert report["all_passed"] is True
    assert report["duration_ms"] < 5000  # Must run in < 5 seconds for fast CI
