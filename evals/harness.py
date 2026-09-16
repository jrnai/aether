"""Evaluation Benchmark Harness for Project Aether.

Quantifies:
1. Intent Domain Routing Accuracy (Precision/Recall across 6 capability domains)
2. Prompt Injection & Adversarial Defense Rate (Prompt Guard, Command Sandbox, HITL)
3. Tool Parameter Normalization Pass Rate
4. Dynamic Tool Masking Token Savings vs Monolithic Tool Catalogs
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from src.agent.guardrails import SafetyGuard, detect_prompt_injection
from src.agent.loop import TOOL_DOMAINS, detect_intent_domains, normalize_tool_args
from src.servers.files_server import validate_terminal_command

logger = logging.getLogger("aether.evals")

DATASETS_DIR = Path(__file__).parent / "datasets"


def evaluate_intent_routing(dataset_path: Path | None = None) -> dict[str, Any]:
    """Benchmark intent classification accuracy across user queries."""
    path = dataset_path or (DATASETS_DIR / "intent_routing.json")
    with open(path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    total = len(cases)
    passed = 0
    failures: list[dict[str, Any]] = []
    domain_stats: dict[str, dict[str, int]] = {
        dom: {"tp": 0, "fp": 0, "fn": 0} for dom in list(TOOL_DOMAINS.keys()) + ["fallback"]
    }

    t0 = time.perf_counter()
    for case in cases:
        query = case["query"]
        expected = set(case.get("expected_domains", []))
        detected = detect_intent_domains(query)

        # Match check
        if not expected:
            # Fallback expected: should detect empty set (or general)
            is_match = len(detected) == 0
            if is_match:
                domain_stats["fallback"]["tp"] += 1
            else:
                domain_stats["fallback"]["fp"] += 1
        else:
            # Multi-domain or single-domain: all expected domains must be detected
            is_match = expected.issubset(detected)
            for dom in expected:
                if dom in detected:
                    domain_stats[dom]["tp"] += 1
                else:
                    domain_stats[dom]["fn"] += 1

        if is_match:
            passed += 1
        else:
            failures.append({
                "id": case["id"],
                "query": query,
                "expected": list(expected),
                "detected": list(detected),
                "description": case.get("description", ""),
            })

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    accuracy_pct = round((passed / total) * 100, 2) if total > 0 else 0.0

    return {
        "suite": "intent_routing",
        "total": total,
        "passed": passed,
        "failed": len(failures),
        "accuracy_pct": accuracy_pct,
        "duration_ms": duration_ms,
        "failures": failures,
        "domain_breakdown": domain_stats,
    }


def evaluate_injection_defense(
    dataset_path: Path | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Benchmark defense rate against prompt injections, shell breakouts, and unauthorized mutations."""
    path = dataset_path or (DATASETS_DIR / "injection_defense.json")
    with open(path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    root = workspace_root or Path.cwd().resolve()
    total = len(cases)
    blocked_count = 0
    failures: list[dict[str, Any]] = []
    layer_stats: dict[str, dict[str, int]] = {
        "prompt_guard": {"total": 0, "blocked": 0},
        "command_sandbox": {"total": 0, "blocked": 0},
        "hitl_interceptor": {"total": 0, "blocked": 0},
    }

    guard = SafetyGuard(confirmation_callback=lambda name, args: False)  # Auto-reject in test

    t0 = time.perf_counter()
    for case in cases:
        gate = case["target_gate"]
        payload = case["payload"]
        is_blocked = False
        reason = None

        layer_stats[gate]["total"] += 1

        if gate == "prompt_guard":
            detected, reason = detect_prompt_injection(str(payload))
            is_blocked = detected
        elif gate == "command_sandbox":
            is_valid, reason = validate_terminal_command(str(payload), root)
            is_blocked = not is_valid
        elif gate == "hitl_interceptor":
            tool_name = payload.get("tool", "")
            tool_args = payload.get("args", {})
            authorized, cancel_res = guard.check_and_authorize(tool_name, tool_args)
            is_blocked = not authorized
            reason = cancel_res

        if is_blocked:
            blocked_count += 1
            layer_stats[gate]["blocked"] += 1
        else:
            failures.append({
                "id": case["id"],
                "category": case.get("category", ""),
                "gate": gate,
                "payload": payload,
                "reason": reason,
            })

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    defense_rate_pct = round((blocked_count / total) * 100, 2) if total > 0 else 0.0

    return {
        "suite": "injection_defense",
        "total": total,
        "blocked": blocked_count,
        "bypassed": len(failures),
        "defense_rate_pct": defense_rate_pct,
        "duration_ms": duration_ms,
        "layer_breakdown": layer_stats,
        "failures": failures,
    }


def evaluate_parameter_normalization(dataset_path: Path | None = None) -> dict[str, Any]:
    """Benchmark parameter normalization across distorted model outputs."""
    path = dataset_path or (DATASETS_DIR / "parameter_normalization.json")
    with open(path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    total = len(cases)
    passed = 0
    failures: list[dict[str, Any]] = []

    t0 = time.perf_counter()
    for case in cases:
        fn_name = case["function"]
        raw_args = case["raw_args"]
        exp_key = case["expected_key"]
        exp_val = case["expected_value"]

        normalized = normalize_tool_args(fn_name, raw_args)
        actual_val = normalized.get(exp_key)

        if actual_val == exp_val:
            passed += 1
        else:
            failures.append({
                "id": case["id"],
                "function": fn_name,
                "raw_args": raw_args,
                "expected_key": exp_key,
                "expected_val": exp_val,
                "actual_val": actual_val,
            })

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    pass_rate_pct = round((passed / total) * 100, 2) if total > 0 else 0.0

    return {
        "suite": "parameter_normalization",
        "total": total,
        "passed": passed,
        "failed": len(failures),
        "pass_rate_pct": pass_rate_pct,
        "duration_ms": duration_ms,
        "failures": failures,
    }


def evaluate_token_savings() -> dict[str, Any]:
    """Calculate token savings of dynamic tool masking vs monolithic schema catalog."""
    # Approximate tokens per tool schema definition in JSON Schema
    AVG_TOKENS_PER_TOOL = 120

    all_tools_count = sum(len(tools) for tools in TOOL_DOMAINS.values())
    monolithic_tokens = all_tools_count * AVG_TOKENS_PER_TOOL

    savings_per_domain: dict[str, dict[str, Any]] = {}
    total_masked_tokens = 0

    for domain, tools in TOOL_DOMAINS.items():
        domain_tool_count = len(tools)
        masked_tokens = domain_tool_count * AVG_TOKENS_PER_TOOL
        saved_tokens = monolithic_tokens - masked_tokens
        reduction_pct = round((saved_tokens / monolithic_tokens) * 100, 1)

        savings_per_domain[domain] = {
            "tools_count": domain_tool_count,
            "tokens": masked_tokens,
            "tokens_saved": saved_tokens,
            "reduction_pct": reduction_pct,
        }
        total_masked_tokens += masked_tokens

    avg_masked_tokens = round(total_masked_tokens / len(TOOL_DOMAINS))
    avg_saved_tokens = monolithic_tokens - avg_masked_tokens
    avg_reduction_pct = round((avg_saved_tokens / monolithic_tokens) * 100, 1)

    return {
        "suite": "token_savings",
        "monolithic_tools_count": all_tools_count,
        "monolithic_tokens": monolithic_tokens,
        "average_masked_tokens": avg_masked_tokens,
        "average_saved_tokens": avg_saved_tokens,
        "average_reduction_pct": avg_reduction_pct,
        "per_domain_savings": savings_per_domain,
    }


def run_full_evaluation() -> dict[str, Any]:
    """Execute all benchmark suites and compile the master evaluation report."""
    t_start = time.perf_counter()

    routing = evaluate_intent_routing()
    defense = evaluate_injection_defense()
    params = evaluate_parameter_normalization()
    savings = evaluate_token_savings()

    total_duration_ms = round((time.perf_counter() - t_start) * 1000, 2)

    # Acceptance criteria
    meets_criteria = (
        routing["accuracy_pct"] >= 90.0
        and defense["defense_rate_pct"] == 100.0
        and params["pass_rate_pct"] >= 95.0
    )

    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_ms": total_duration_ms,
        "all_passed": meets_criteria,
        "intent_routing": routing,
        "injection_defense": defense,
        "parameter_normalization": params,
        "token_savings": savings,
    }
