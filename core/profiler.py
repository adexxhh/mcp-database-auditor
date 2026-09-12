"""
Analytical Data Profiler and Markdown/JSON Report Generator.
"""

from datetime import datetime, timezone
import json
import math
import sys
from typing import Any, Dict, List, Optional, Sequence, Union
from pydantic import BaseModel, Field


class OutlierDetail(BaseModel):
    column: str
    row_index: int
    value: float
    score: float
    method: str


class ColumnProfile(BaseModel):
    name: str
    data_type: str
    total_count: int
    null_count: int
    null_rate: float
    unique_count: int
    cardinality_ratio: float
    is_key_column: bool = False
    key_null_warning: bool = False
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    mean_val: Optional[float] = None
    std_dev: Optional[float] = None
    outliers: List[OutlierDetail] = Field(default_factory=list)
    distribution_bar: Optional[str] = None


class PerformanceMetrics(BaseModel):
    execution_time_ms: float
    row_count: int
    bytes_transferred: int
    estimated_memory_bytes: int


class AuditReport(BaseModel):
    query: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    column_profiles: List[ColumnProfile] = Field(default_factory=list)
    performance: PerformanceMetrics
    anomalies_detected: List[str] = Field(default_factory=list)


class AuditProfiler:
    """
    Automated analytical profiler for query results providing statistical health checks,
    outlier identification, performance metrics, and Markdown/JSON report export.
    """

    @staticmethod
    def generate_histogram_bar(pct: float, width: int = 10, use_unicode: bool = True) -> str:
        """
        Generates a zero-dependency ASCII/Unicode distribution bar chart.
        Example: [██████░░░░] 60%
        """
        pct_clamped = max(0.0, min(1.0, float(pct)))
        filled = int(round(pct_clamped * width))
        empty = width - filled

        if use_unicode:
            fill_char, empty_char = "█", "░"
        else:
            fill_char, empty_char = "#", "-"

        bar = fill_char * filled + empty_char * empty
        return f"[{bar}] {int(pct_clamped * 100)}%"

    def profile(
        self,
        rows: List[Dict[str, Any]],
        query: str,
        execution_time_ms: float = 0.0,
        key_columns: Optional[Sequence[str]] = None,
    ) -> AuditReport:
        """
        Profiles query execution results and returns a structured AuditReport.

        Args:
            rows: List of row dictionaries returned by query execution.
            query: The executed SQL query string.
            execution_time_ms: Query execution duration in milliseconds.
            key_columns: Optional list of column names designated as primary/foreign keys.

        Returns:
            An AuditReport instance containing statistical metrics and anomalies.
        """
        key_cols_set = set(key_columns or [])
        total_rows = len(rows)

        # Performance Metrics
        json_bytes = len(json.dumps(rows, default=str).encode("utf-8")) if rows else 0
        memory_bytes = sum(sys.getsizeof(r) + sum(sys.getsizeof(k) + sys.getsizeof(v) for k, v in r.items()) for r in rows) if rows else 0

        perf_metrics = PerformanceMetrics(
            execution_time_ms=round(execution_time_ms, 3),
            row_count=total_rows,
            bytes_transferred=json_bytes,
            estimated_memory_bytes=memory_bytes,
        )

        if not rows:
            return AuditReport(
                query=query,
                column_profiles=[],
                performance=perf_metrics,
                anomalies_detected=["EMPTY_RESULT_SET: Query returned 0 rows."],
            )

        col_names = list(rows[0].keys())
        column_profiles: List[ColumnProfile] = []
        anomalies: List[str] = []

        for col in col_names:
            raw_vals = [r.get(col) for r in rows]
            non_null_vals = [v for v in raw_vals if v is not None]
            null_count = total_rows - len(non_null_vals)
            null_rate = round(null_count / total_rows, 4) if total_rows > 0 else 0.0

            unique_count = len(set(raw_vals))
            cardinality_ratio = round(unique_count / total_rows, 4) if total_rows > 0 else 0.0

            # Key column detection & null check warning
            is_key = col in key_cols_set or col.lower() == "id" or col.lower().endswith("_id")
            key_null_warning = is_key and null_count > 0

            if key_null_warning:
                anomalies.append(
                    f"NULL_KEY_DETECTED: Key column '{col}' has {null_count} null value(s) (null rate: {null_rate * 100:.1f}%)."
                )

            # Check if numeric for outlier and statistical analysis
            numeric_items: List[Tuple[int, float]] = []
            for idx, val in enumerate(raw_vals):
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    numeric_items.append((idx, float(val)))

            min_val, max_val, mean_val, std_dev = None, None, None, None
            outliers: List[OutlierDetail] = []

            if len(numeric_items) > 0:
                nums = [item[1] for item in numeric_items]
                min_val = round(min(nums), 4)
                max_val = round(max(nums), 4)
                mean_val = round(sum(nums) / len(nums), 4)

                variance = sum((x - mean_val) ** 2 for x in nums) / len(nums)
                std_dev = round(math.sqrt(variance), 4)

                # Outlier detection: IQR & Z-score
                sorted_nums = sorted(nums)
                n_nums = len(sorted_nums)
                q1 = sorted_nums[int(n_nums * 0.25)]
                q3 = sorted_nums[int(n_nums * 0.75)]
                iqr = q3 - q1

                iqr_lower = q1 - 1.5 * iqr
                iqr_upper = q3 + 1.5 * iqr

                for idx, val in numeric_items:
                    # IQR Outlier check
                    if val < iqr_lower or val > iqr_upper:
                        dist = round(abs(val - mean_val), 2)
                        outliers.append(
                            OutlierDetail(
                                column=col,
                                row_index=idx,
                                value=val,
                                score=dist,
                                method="IQR",
                            )
                        )
                    # Z-score Outlier check (if std_dev > 0)
                    elif std_dev and std_dev > 0:
                        z_score = abs(val - mean_val) / std_dev
                        if z_score > 3.0:
                            outliers.append(
                                OutlierDetail(
                                    column=col,
                                    row_index=idx,
                                    value=val,
                                    score=round(z_score, 2),
                                    method="Z-SCORE",
                                )
                            )

                if outliers:
                    anomalies.append(
                        f"OUTLIERS_DETECTED: Column '{col}' contains {len(outliers)} numerical outlier(s)."
                    )

            # Determine sample type string
            sample_val = non_null_vals[0] if non_null_vals else None
            dtype_str = type(sample_val).__name__ if sample_val is not None else "Unknown"

            # Distribution histogram bar based on non-null ratio
            non_null_ratio = (total_rows - null_count) / total_rows if total_rows > 0 else 0.0
            dist_bar = self.generate_histogram_bar(non_null_ratio)

            column_profiles.append(
                ColumnProfile(
                    name=col,
                    data_type=dtype_str,
                    total_count=total_rows,
                    null_count=null_count,
                    null_rate=null_rate,
                    unique_count=unique_count,
                    cardinality_ratio=cardinality_ratio,
                    is_key_column=is_key,
                    key_null_warning=key_null_warning,
                    min_val=min_val,
                    max_val=max_val,
                    mean_val=mean_val,
                    std_dev=std_dev,
                    outliers=outliers,
                    distribution_bar=dist_bar,
                )
            )

        return AuditReport(
            query=query,
            column_profiles=column_profiles,
            performance=perf_metrics,
            anomalies_detected=anomalies,
        )

    @staticmethod
    def to_markdown(report: AuditReport, max_preview_rows: int = 5) -> str:
        """
        Converts an AuditReport object into GitHub-Flavored Markdown report with tables,
        alerts, and visual distribution indicators.
        """
        md: List[str] = []
        md.append("# Database Audit & Data Profiling Report")
        md.append(f"**Query**: `{report.query}`")
        md.append(f"**Timestamp**: `{report.timestamp}`")
        md.append("")

        # 1. Anomalies & Health Warnings Section
        md.append("## Health Check Warnings & Anomalies")
        if report.anomalies_detected:
            for anomaly in report.anomalies_detected:
                md.append(f"> [!WARNING]")
                md.append(f"> {anomaly}")
                md.append("")
        else:
            md.append("> [!NOTE]")
            md.append("> No critical data anomalies or primary/foreign key null violations detected.")
            md.append("")

        # 2. Performance Metrics Section
        md.append("## Performance Metrics")
        md.append("| Metric | Value |")
        md.append("| :--- | :--- |")
        md.append(f"| **Execution Time** | `{report.performance.execution_time_ms:.2f} ms` |")
        md.append(f"| **Rows Returned** | `{report.performance.row_count}` |")
        md.append(f"| **Bytes Transferred** | `{report.performance.bytes_transferred} bytes` |")
        md.append(f"| **Est. Memory Footprint** | `{report.performance.estimated_memory_bytes} bytes` |")
        md.append("")

        # 3. Column Profiling Section
        md.append("## Column Profiles & Statistical Summary")
        md.append("| Column | Type | Null Rate | Cardinality | Min / Max | Mean (StdDev) | Data Present |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

        for cp in report.column_profiles:
            null_pct = f"{cp.null_rate * 100:.1f}%"
            card_pct = f"{cp.cardinality_ratio * 100:.1f}%"
            
            min_max_str = f"`{cp.min_val}` / `{cp.max_val}`" if cp.min_val is not None else "-"
            mean_std_str = f"`{cp.mean_val}` (`±{cp.std_dev}`)" if cp.mean_val is not None else "-"
            bar_str = f"`{cp.distribution_bar}`" if cp.distribution_bar else "-"

            col_name_fmt = f"**{cp.name}**" if cp.is_key_column else cp.name
            if cp.key_null_warning:
                col_name_fmt += " ⚠️"

            md.append(
                f"| {col_name_fmt} | `{cp.data_type}` | `{null_pct}` ({cp.null_count}) | `{card_pct}` ({cp.unique_count}) | {min_max_str} | {mean_std_str} | {bar_str} |"
            )

        md.append("")

        # 4. Outliers Detailed Section (if any)
        outlier_cols = [cp for cp in report.column_profiles if cp.outliers]
        if outlier_cols:
            md.append("## Outlier Details")
            md.append("| Column | Row Index | Outlier Value | Metric / Method |")
            md.append("| :--- | :--- | :--- | :--- |")
            for cp in outlier_cols:
                for out in cp.outliers:
                    md.append(f"| `{out.column}` | `{out.row_index}` | `{out.value}` | `{out.method}` (Score: {out.score}) |")
            md.append("")

        return "\n".join(md)

    @staticmethod
    def to_json(report: AuditReport) -> str:
        """Exports an AuditReport object into structured JSON format."""
        return report.model_dump_json(indent=2)
