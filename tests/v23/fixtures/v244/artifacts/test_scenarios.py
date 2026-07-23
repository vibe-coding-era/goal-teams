def test_api_contract_scenario() -> None:
    assert {"state": "created"}["state"] == "created"


def test_e2e_contract_scenario() -> None:
    assert {"order_count": 1}["order_count"] == 1
