from nightwatch.fleet_probe import probe_contract


def test_fleet_probe_contract_pins_all_three_private_agents() -> None:
    contract = probe_contract()
    assert contract.delegation is not None
    assert contract.delegation.mandatory_specialists == ("regression_guard",)
    assert [agent.specialist for agent in contract.delegation.approved_agents] == [
        "target_repair", "safety_boundary", "regression_guard"
    ]
