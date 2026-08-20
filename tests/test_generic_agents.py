from __future__ import annotations

import asyncio

from nightwatch.generic_agents import SPECIALISTS, author_parallel_curriculum
from nightwatch.operator_contracts import build_mission_contract, parse_uploaded_dataset
from test_operator_contracts import contract_request, jsonl_bytes


def test_curriculum_identity_is_bound_by_the_orchestrator(monkeypatch) -> None:
    dataset = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    contract = build_mission_contract(contract_request(dataset.dataset_id), dataset)

    async def structured_agent(**kwargs):
        specialist = kwargs["request"]["specialist"]
        labels = kwargs["request"]["labels"]
        examples = [
            {"text": f"{specialist} authored boundary example {index}", "label": labels[index % len(labels)]}
            for index in range(8)
        ]
        return {
            "specialist": "untrusted-model-claim",
            "rationale": "Author a balanced set covering every frozen classification label.",
            "examples": examples,
        }

    monkeypatch.setattr("nightwatch.generic_agents._structured_agent", structured_agent)
    result = asyncio.run(author_parallel_curriculum(
        {"headline": "Bounded diagnosis"},
        {"errors": [], "all_cases": []},
        contract,
    ))

    assert result["specialists"] == list(SPECIALISTS)
    assert [batch["specialist"] for batch in result["batches"]] == list(SPECIALISTS)
    assert {row["specialist"] for row in result["rows"]} == set(SPECIALISTS)
