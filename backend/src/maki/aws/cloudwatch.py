import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_NAMESPACE = "ECS/ContainerInsights"
_SERIES_IDS = frozenset({"running", "desired"})  # the two query Ids we merge by


class CloudWatchTaskMetrics:
    """Per-service running-vs-desired task counts from CloudWatch Container Insights.

    Reads ``RunningTaskCount`` and ``DesiredTaskCount`` for one ECS service in a single
    ``GetMetricData`` call (two queries, ascending by timestamp) and merges them into a sorted
    list of points. Read-only: only ``cloudwatch:GetMetricData`` is ever called.
    """

    def __init__(self, client, cluster: str):
        self._client = client
        self._cluster = cluster

    def task_history(
        self, service_name: str, start: datetime, end: datetime, period: int
    ) -> list[dict]:
        """Merged running/desired task-count points, ascending by timestamp.

        Returns ``[{"timestamp": datetime, "running": float | None, "desired": float | None}]``.
        Best-effort: ANY failure (botocore error, throttling, parse error) logs a warning and
        returns ``[]`` — the metrics tab must still render without this chart, so it never raises.
        """
        try:
            resp = self._client.get_metric_data(
                MetricDataQueries=[
                    self._query("running", "RunningTaskCount", service_name, period),
                    self._query("desired", "DesiredTaskCount", service_name, period),
                ],
                StartTime=start,
                EndTime=end,
                ScanBy="TimestampAscending",
            )
            return self._merge(resp.get("MetricDataResults", []))
        except Exception:  # noqa: BLE001 - intentional: the chart is optional, never break the tab
            logger.warning(
                "task_history failed for service %r over %s..%s; chart will render empty",
                service_name,
                start.isoformat(),
                end.isoformat(),
                exc_info=True,
            )
            return []

    def _query(self, query_id: str, metric_name: str, service_name: str, period: int) -> dict:
        return {
            "Id": query_id,
            "MetricStat": {
                "Metric": {
                    "Namespace": _NAMESPACE,
                    "MetricName": metric_name,
                    "Dimensions": [
                        {"Name": "ServiceName", "Value": service_name},
                        {"Name": "ClusterName", "Value": self._cluster},
                    ],
                },
                "Period": period,
                "Stat": "Maximum",
            },
            "ReturnData": True,
        }

    @staticmethod
    def _merge(results: list[dict]) -> list[dict]:
        """Merge the running/desired series (keyed by Id) into one timestamp-sorted point list."""
        points: dict[datetime, dict] = {}
        for result in results:
            field = result.get("Id")
            if field not in _SERIES_IDS:
                continue
            timestamps = result.get("Timestamps", [])
            values = result.get("Values", [])
            # Parallel arrays per the GetMetricData contract; strict=True turns any future
            # length mismatch into a raise the caller's fail-soft logs, not silent misalignment.
            for ts, value in zip(timestamps, values, strict=True):
                point = points.setdefault(ts, {"timestamp": ts, "running": None, "desired": None})
                point[field] = value
        return [points[ts] for ts in sorted(points)]
