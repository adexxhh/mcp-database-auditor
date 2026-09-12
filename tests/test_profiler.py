import json
import pytest
from core.profiler import (
    AuditProfiler,
    AuditReport,
    ColumnProfile,
    OutlierDetail,
    PerformanceMetrics,
)


@pytest.fixture
def profiler():
    return AuditProfiler()


@pytest.fixture
def sample_rows():
    return [
        {"id": 1, "tenant_id": 101, "amount": 100.0, "status": "PAID"},
        {"id": 2, "tenant_id": 101, "amount": 105.0, "status": "PAID"},
        {"id": 3, "tenant_id": 102, "amount": 95.0, "status": "PENDING"},
        {"id": 4, "tenant_id": 102, "amount": 110.0, "status": "PAID"},
        {"id": 5, "tenant_id": 103, "amount": 999999.0, "status": "FLAGGED"},  # Outlier
        {"id": 6, "tenant_id": None, "amount": 98.0, "status": "PAID"},       # Key null violation
    ]


def test_histogram_bar_generation(profiler):
    """Test zero-dependency ASCII and Unicode distribution bar generation."""
    bar_unicode = profiler.generate_histogram_bar(0.60, width=10, use_unicode=True)
    assert bar_unicode == "[██████░░░░] 60%"

    bar_ascii = profiler.generate_histogram_bar(0.40, width=10, use_unicode=False)
    assert bar_ascii == "[####------] 40%"

    bar_zero = profiler.generate_histogram_bar(0.0)
    assert "0%" in bar_zero

    bar_full = profiler.generate_histogram_bar(1.0)
    assert "100%" in bar_full


def test_profiling_statistical_checks(profiler, sample_rows):
    """Test statistical calculations: null rates, cardinality ratios, min/max/mean/std_dev."""
    query = "SELECT id, tenant_id, amount, status FROM invoices"
    report = profiler.profile(sample_rows, query=query, execution_time_ms=12.45, key_columns=["id", "tenant_id"])

    assert report.query == query
    assert report.performance.row_count == 6
    assert report.performance.execution_time_ms == 12.45
    assert report.performance.bytes_transferred > 0
    assert report.performance.estimated_memory_bytes > 0

    profiles = {p.name: p for p in report.column_profiles}

    # Test amount column statistics
    amt_prof = profiles["amount"]
    assert amt_prof.null_count == 0
    assert amt_prof.null_rate == 0.0
    assert amt_prof.min_val == 95.0
    assert amt_prof.max_val == 999999.0
    assert amt_prof.mean_val is not None
    assert len(amt_prof.outliers) > 0

    # Test outlier details
    outlier = amt_prof.outliers[0]
    assert outlier.column == "amount"
    assert outlier.value == 999999.0
    assert outlier.row_index == 4


def test_key_null_warning_detection(profiler, sample_rows):
    """Test detection of null primary/foreign key columns."""
    query = "SELECT id, tenant_id FROM invoices"
    report = profiler.profile(sample_rows, query=query, execution_time_ms=5.0, key_columns=["tenant_id"])

    profiles = {p.name: p for p in report.column_profiles}
    tenant_id_prof = profiles["tenant_id"]

    assert tenant_id_prof.key_null_warning is True
    assert tenant_id_prof.null_count == 1
    assert any("NULL_KEY_DETECTED" in a for a in report.anomalies_detected)


def test_markdown_report_generation(profiler, sample_rows):
    """Test Markdown report formatting, tables, warnings, and distribution bars."""
    report = profiler.profile(sample_rows, query="SELECT * FROM invoices", execution_time_ms=8.3)
    md_output = profiler.to_markdown(report)

    assert "# Database Audit & Data Profiling Report" in md_output
    assert "SELECT * FROM invoices" in md_output
    assert "Performance Metrics" in md_output
    assert "Column Profiles & Statistical Summary" in md_output
    assert "[██████" in md_output or "[░" in md_output
    assert "NULL_KEY_DETECTED" in md_output or "OUTLIERS_DETECTED" in md_output


def test_json_report_export(profiler, sample_rows):
    """Test Pydantic JSON serialization and deserialization back to AuditReport."""
    report = profiler.profile(sample_rows, query="SELECT * FROM invoices", execution_time_ms=15.1)
    json_output = profiler.to_json(report)

    parsed = json.loads(json_output)
    assert parsed["query"] == "SELECT * FROM invoices"
    assert parsed["performance"]["row_count"] == 6

    deserialized = AuditReport.model_validate_json(json_output)
    assert deserialized.performance.row_count == 6
    assert len(deserialized.column_profiles) == 4


def test_empty_rows_profiling(profiler):
    """Test profiling with empty query result set."""
    report = profiler.profile([], query="SELECT * FROM empty_table", execution_time_ms=1.2)
    assert report.performance.row_count == 0
    assert len(report.column_profiles) == 0
    assert any("EMPTY_RESULT_SET" in a for a in report.anomalies_detected)
