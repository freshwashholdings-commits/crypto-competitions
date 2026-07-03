from tron_tracer.trace.engine import InMemoryProvider, run_backward_trace, run_forward_trace
from tron_tracer.trace.policies import TracePolicy

A = "TSenderA1111111111111111111111111111"
X = "TAddressX1111111111111111111111111111"
Y = "TAddressY1111111111111111111111111111"
EXCHANGE = "TExchangeService1111111111111111111"
CONTRACT = "TContractAddr11111111111111111111111"


def test_forward_trace_two_hops_with_service_terminal(xfer):
    transfers = [
        xfer("tx1", 100, 0, A, X, 1_000),       # deposit under investigation
        xfer("tx2", 101, 0, X, Y, 600),          # X peels 600 to Y
        xfer("tx3", 102, 0, Y, EXCHANGE, 600),   # Y sends it all to a labeled exchange
    ]
    provider = InMemoryProvider(transfers, labeled={EXCHANGE})
    doc = run_forward_trace(X, "TRX", provider, TracePolicy(method="fifo"), seed_tx_hashes=["tx1"])

    assert doc["parameters"]["direction"] == "forward"
    assert len(doc["hops"]) == 2  # hop 0 = X, hop 1 = Y
    assert doc["hops"][0]["address"] == X
    assert doc["hops"][1]["address"] == Y

    types = {t["terminal_type"]: t["amount"] for t in doc["terminals"]}
    assert types["service"] == 600
    assert types["holding"] == 400  # 1000 - 600 still sitting at X
    assert doc["total_traced"] == 1_000
    assert "document_sha256" in doc


def test_forward_trace_contract_and_dust_terminals(xfer):
    transfers = [
        xfer("tx1", 100, 0, A, X, 1_000),
        xfer("tx2", 101, 0, X, CONTRACT, 995),
        xfer("tx3", 102, 0, X, Y, 5),  # below dust threshold
    ]
    provider = InMemoryProvider(transfers, contracts={CONTRACT})
    doc = run_forward_trace(X, "TRX", provider, TracePolicy(method="fifo", dust_threshold=10), seed_tx_hashes=["tx1"])
    types = {t["terminal_type"]: t["amount"] for t in doc["terminals"]}
    assert types["contract_interaction"] == 995
    assert types["dust"] == 5


def test_forward_trace_determinism(xfer):
    transfers = [
        xfer("tx1", 100, 0, A, X, 1_000),
        xfer("tx2", 101, 0, X, Y, 600),
        xfer("tx3", 102, 0, Y, EXCHANGE, 600),
    ]
    provider = InMemoryProvider(transfers, labeled={EXCHANGE})
    doc1 = run_forward_trace(X, "TRX", provider, TracePolicy(method="fifo"), seed_tx_hashes=["tx1"])
    doc2 = run_forward_trace(X, "TRX", provider, TracePolicy(method="fifo"), seed_tx_hashes=["tx1"])
    assert doc1["document_sha256"] == doc2["document_sha256"]


def test_backward_trace_attributes_to_sender_with_proportional_scaling(xfer):
    # Y receives 1,000 from A (tx1), forwards only 700 of it to X (tx2).
    # Tracing X's holding backward must scale A's own 1,000-unit send down
    # to the 700 fraction actually attributable to X -- not credit X with
    # the full 1,000 A ever sent.
    transfers = [
        xfer("tx1", 100, 0, A, Y, 1_000),
        xfer("tx2", 101, 0, Y, X, 700),
    ]
    provider = InMemoryProvider(transfers, openings={(A, "TRX"): 1_000})
    doc = run_backward_trace(X, "TRX", provider, TracePolicy(method="fifo"))  # seed = current holding

    assert doc["parameters"]["direction"] == "backward"
    assert [h["address"] for h in doc["hops"]] == [X, Y, A]
    types = {t["terminal_type"]: t["amount"] for t in doc["terminals"]}
    assert types["pre_window_unknown"] == 700  # scaled down from A's full 1,000 send
    assert doc["total_traced"] == 700
