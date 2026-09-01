from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docs" / "architecture" / "milestone-8a-spec.json"
TODO_PATH = ROOT / "TODO.md"
STABLE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"milestone-8a-spec: ERROR: {message}")


def unique_ids(items: list[dict[str, Any]], label: str) -> set[str]:
    ids = [str(item["id"]) for item in items]
    require(len(ids) == len(set(ids)), f"duplicate {label} id")
    require(all(STABLE_ID.fullmatch(item_id) for item_id in ids), f"invalid {label} id")
    return set(ids)


def require_acyclic(
    items: list[dict[str, Any]], id_key: str, prerequisite_key: str, label: str
) -> None:
    graph = {
        str(item[id_key]): [str(value) for value in item[prerequisite_key]]
        for item in items
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        require(node not in visiting, f"cycle in {label} graph at {node}")
        if node in visited:
            return
        visiting.add(node)
        for prerequisite in graph[node]:
            require(
                prerequisite in graph, f"unknown {label} prerequisite {prerequisite}"
            )
            visit(prerequisite)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def main() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    require(spec["schema_version"] == "8a-spec-1.0.0", "unexpected schema version")
    require(spec["skill_id"] == "algorithm", "unexpected skill id")
    require(spec["candidate_skill_version"] == "0.3.0", "unexpected candidate version")
    require(spec["status"] == "design_only", "8A must remain design-only")

    decisions = spec["decisions"]
    require(
        set(decisions) == {f"M8-D{i:02d}" for i in range(1, 16)}, "decision set drift"
    )
    require(
        all(
            value == "confirmed" for key, value in decisions.items() if key != "M8-D12"
        ),
        "unconfirmed decision",
    )
    require(decisions["M8-D12"] == "confirmed_8a_only", "authorization must stop at 8A")

    domains = spec["domains"]
    capabilities = spec["capabilities"]
    units = spec["units"]
    sources = spec["sources"]
    budgets = spec["content_budget"]
    domain_ids = unique_ids(domains, "domain")
    capability_ids = unique_ids(capabilities, "capability")
    unit_ids = unique_ids(units, "unit")
    source_ids = unique_ids(sources, "source")

    require(len(domain_ids) == budgets["exact_domains"] == 12, "domain count drift")
    require(
        len(capability_ids) <= budgets["max_capabilities"], "capability budget exceeded"
    )
    require(len(unit_ids) <= budgets["max_units"], "unit budget exceeded")
    require_acyclic(capabilities, "id", "prerequisites", "capability")
    require_acyclic(units, "id", "prerequisite_unit_ids", "unit")

    covered_capabilities: set[str] = set()
    for capability in capabilities:
        require(capability["domain_id"] in domain_ids, "capability has unknown domain")
        require(
            str(capability["diagnostic_signal"]).strip() != "",
            "missing diagnostic signal",
        )
        require(
            capability["remediation_unit_id"] in unit_ids, "unknown remediation unit"
        )
    total_minutes = 0
    for unit in units:
        require(unit["domain_id"] in domain_ids, "unit has unknown domain")
        minutes = int(unit["estimated_minutes"])
        require(15 <= minutes <= 240, "unit time outside reviewable range")
        total_minutes += minutes
        for capability_id in unit["capability_ids"]:
            require(capability_id in capability_ids, "unit has unknown capability")
            covered_capabilities.add(capability_id)
    require(
        covered_capabilities == capability_ids,
        "not every capability is covered by a unit",
    )
    require(
        total_minutes <= budgets["max_total_unit_minutes"],
        "total unit time budget exceeded",
    )

    matrix_domains: set[str] = set()
    tier_by_source = {source["id"]: int(source["authority_tier"]) for source in sources}
    for row in spec["source_matrix"]:
        domain_id = row["domain_id"]
        require(domain_id in domain_ids, "source matrix has unknown domain")
        require(domain_id not in matrix_domains, "duplicate source matrix domain")
        matrix_domains.add(domain_id)
        row_sources = row["source_ids"]
        require(
            len(set(row_sources)) >= budgets["minimum_sources_per_domain"],
            "source coverage too small",
        )
        require(
            all(source_id in source_ids for source_id in row_sources),
            "unknown source reference",
        )
        require(
            sum(tier_by_source[source_id] <= 2 for source_id in row_sources)
            >= budgets["minimum_authority_tier_1_or_2_sources_per_domain"],
            "domain lacks tier 1 or 2 source",
        )
    require(matrix_domains == domain_ids, "source matrix domain coverage drift")

    required_activities = {
        "study",
        "active_recall",
        "structured_check",
        "correction",
        "transfer",
        "review",
    }
    coverage_domains: set[str] = set()
    all_dimensions: set[str] = set()
    for row in spec["coverage"]:
        domain_id = row["domain_id"]
        require(domain_id in domain_ids, "coverage has unknown domain")
        require(domain_id not in coverage_domains, "duplicate coverage domain")
        coverage_domains.add(domain_id)
        require(
            required_activities <= set(row["activity_types"]), "activity coverage gap"
        )
        all_dimensions.update(row["evidence_dimensions"])
    require(coverage_domains == domain_ids, "coverage matrix domain drift")
    require(
        all_dimensions
        == {
            "understanding",
            "operation",
            "transfer",
            "artifact",
            "retention",
            "correction",
        },
        "six-dimension evidence coverage drift",
    )

    diagnostic = spec["diagnostic_policy"]
    require(
        diagnostic["item_bank_max"] <= budgets["max_diagnostic_items"],
        "diagnostic budget exceeded",
    )
    require(
        diagnostic["session_question_max"] < len(capability_ids),
        "diagnostic must permit inconclusive scopes",
    )
    require(
        diagnostic["fallback"] == "managed_fixed_sequence", "unsafe diagnostic fallback"
    )
    require(
        diagnostic["evidence_ceiling"] == "diagnostic_signal_only",
        "diagnostic evidence ceiling drift",
    )

    daily = spec["daily_policy"]
    require(daily["target_minutes"] == 120, "daily target drift")
    require(daily["default_hard_cap_minutes"] == 120, "daily default cap drift")
    review = spec["review_policy"]
    require(
        review["interval_days"] == [1, 2, 4, 7, 15],
        "authoritative review intervals drift",
    )
    require(
        "cannot_change_tasks_evidence" in review["shadow_model"],
        "shadow model boundary missing",
    )

    gate_ids = unique_ids(spec["branch_gates"], "branch gate")
    require(
        gate_ids == {"engineering", "interview", "competition", "theory"},
        "branch gate drift",
    )
    for gate in spec["branch_gates"]:
        require(
            all(item in capability_ids for item in gate["required_capability_ids"]),
            "unknown gate capability",
        )
        require("不表示" in gate["required"], "branch limitation missing")

    todo_text = TODO_PATH.read_text(encoding="utf-8")
    for todo_id in spec["deferred_todo_ids"]:
        require(todo_id in todo_text, f"deferred task {todo_id} missing from TODO.md")

    candidate_path = ROOT / "skill-packs" / "algorithm" / "versions" / "0.3.0"
    if candidate_path.exists():
        require(
            "| M8B-001 | 已完成（当前授权范围） |" in todo_text,
            "algorithm@0.3.0 requires a recorded 8B completion state",
        )
    print(
        "milestone-8a-spec: OK "
        f"({len(domain_ids)} domains, {len(capability_ids)} capabilities, "
        f"{len(unit_ids)} units, {total_minutes} planned minutes)"
    )


if __name__ == "__main__":
    main()
