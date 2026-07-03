from tron_tracer.attribution.orchestrate import run_attribution
from tron_tracer.db.models import Account, Label, Transfer
from tron_tracer.db.session import session_scope

A = "TAddrA1111111111111111111111111111111"
B = "TAddrB1111111111111111111111111111111"
EXCHANGE = "TExchange111111111111111111111111111"
KEY = "TSharedKey11111111111111111111111111"


def test_run_attribution_shared_key_and_activation(tmp_path):
    db_url = f"sqlite:///{tmp_path}/case.db"
    with session_scope(db_url) as session:
        session.add_all([
            Account(address=A, owner_permission={"keys": [{"address": KEY}]}, active_permissions=[],
                    activated_by=EXCHANGE, activation_tx="tx_activate"),
            Account(address=B, owner_permission={"keys": [{"address": KEY}]}, active_permissions=[]),
            Label(address=EXCHANGE, label="Big Exchange", category="exchange", source="tronscan"),
        ])
        session.add_all([
            Transfer(tx_hash="tx_activate", block_number=1, tx_index=0, log_index=0, block_timestamp=0,
                     from_address=EXCHANGE, to_address=A, asset_type="TRX", asset_id="TRX", amount=1,
                     contract_type="AccountCreateContract"),
            Transfer(tx_hash="tx1", block_number=2, tx_index=0, log_index=0, block_timestamp=0,
                     from_address=A, to_address=B, asset_type="TRX", asset_id="TRX", amount=1000),
        ])
        session.flush()

        result = run_attribution(session, threshold=0.75)

    assert len(result["clusters"]) == 1
    cluster = result["clusters"][0]
    assert set(cluster["members"]) == {A, B}
    assert cluster["min_confidence_edge"]["confidence"] >= 0.98  # shared key dominates


def test_activation_link_capped_when_activator_is_exchange(tmp_path):
    db_url = f"sqlite:///{tmp_path}/case2.db"
    with session_scope(db_url) as session:
        session.add_all([
            Account(address=A, activated_by=EXCHANGE, activation_tx="tx_activate"),
            Label(address=EXCHANGE, label="Big Exchange", category="exchange", source="tronscan"),
        ])
        session.add(Transfer(
            tx_hash="tx_activate", block_number=1, tx_index=0, log_index=0, block_timestamp=0,
            from_address=EXCHANGE, to_address=A, asset_type="TRX", asset_id="TRX", amount=1,
            contract_type="AccountCreateContract",
        ))
        session.flush()
        result = run_attribution(session, threshold=0.05)

    # capped activation confidence (<=0.05) should barely qualify or not at all
    for cluster in result["clusters"]:
        if EXCHANGE in cluster["members"] and A in cluster["members"]:
            assert cluster["min_confidence_edge"]["confidence"] <= 0.05
