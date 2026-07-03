from pathlib import Path

from tron_tracer.report.csv_export import write_consumption_ledger_csv
from tron_tracer.report.graphml_export import write_graphml
from tron_tracer.report.html_report import render_html_report
from tron_tracer.trace.engine import InMemoryProvider, run_forward_trace
from tron_tracer.trace.policies import TracePolicy

A = "TAddrA1111111111111111111111111111111"
X = "TAddrX1111111111111111111111111111111"
EXCHANGE = "TExchange1111111111111111111111111111"


def _sample_doc(xfer):
    transfers = [
        xfer("tx1", 100, 0, A, X, 1_000_000),
        xfer("tx2", 101, 0, X, EXCHANGE, 900_000),
    ]
    provider = InMemoryProvider(transfers, labeled={EXCHANGE})
    return run_forward_trace(X, "TRX", provider, TracePolicy(method="fifo"), seed_tx_hashes=["tx1"])


def test_csv_export(tmp_path, xfer):
    doc = _sample_doc(xfer)
    path = write_consumption_ledger_csv(doc, tmp_path / "ledger.csv")
    content = path.read_text()
    assert "tx2" in content
    assert "amount_consumed" in content.splitlines()[0]


def test_graphml_export(tmp_path, xfer):
    doc = _sample_doc(xfer)
    path = write_graphml(doc, tmp_path / "graph.graphml")
    content = path.read_text()
    assert "<graphml" in content
    assert X in content or A in content


def test_html_report_renders(tmp_path, xfer):
    doc = _sample_doc(xfer)
    path = render_html_report(doc, tmp_path / "report.html")
    content = path.read_text()
    assert "Tron Fund Trace Report" in content
    assert "<svg" in content
    assert doc["document_sha256"] in content
    assert "Limitations" in content
