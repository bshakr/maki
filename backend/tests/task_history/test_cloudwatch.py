from datetime import UTC, datetime
from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from maki.aws.cloudwatch import CloudWatchTaskMetrics

T0 = datetime(2026, 5, 30, 10, 0, tzinfo=UTC)
T1 = datetime(2026, 5, 30, 11, 0, tzinfo=UTC)
T2 = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
START = datetime(2026, 5, 29, tzinfo=UTC)
END = datetime(2026, 5, 30, 13, 0, tzinfo=UTC)


def _client(results):
    client = MagicMock()
    client.get_metric_data.return_value = {"MetricDataResults": results}
    return client


def test_merges_series_by_timestamp_ascending():
    client = _client(
        [
            {"Id": "running", "Timestamps": [T0, T1, T2], "Values": [2.0, 3.0, 3.0]},
            {"Id": "desired", "Timestamps": [T0, T1, T2], "Values": [3.0, 3.0, 3.0]},
        ]
    )
    points = CloudWatchTaskMetrics(client, "production").task_history("inventory", START, END, 300)

    assert [p["timestamp"] for p in points] == [T0, T1, T2]
    assert [p["running"] for p in points] == [2.0, 3.0, 3.0]
    assert [p["desired"] for p in points] == [3.0, 3.0, 3.0]


def test_missing_values_become_none():
    # running has a point at T1 that desired lacks, and vice-versa at T2.
    client = _client(
        [
            {"Id": "running", "Timestamps": [T0, T1], "Values": [2.0, 4.0]},
            {"Id": "desired", "Timestamps": [T0, T2], "Values": [3.0, 5.0]},
        ]
    )
    points = CloudWatchTaskMetrics(client, "production").task_history("inventory", START, END, 300)

    by_ts = {p["timestamp"]: p for p in points}
    assert by_ts[T0] == {"timestamp": T0, "running": 2.0, "desired": 3.0}
    assert by_ts[T1] == {"timestamp": T1, "running": 4.0, "desired": None}
    assert by_ts[T2] == {"timestamp": T2, "running": None, "desired": 5.0}
    assert [p["timestamp"] for p in points] == [T0, T1, T2]  # ascending


def test_builds_two_queries_with_dimensions():
    client = _client([])
    CloudWatchTaskMetrics(client, "production").task_history("inventory", START, END, 3600)

    kwargs = client.get_metric_data.call_args.kwargs
    assert kwargs["ScanBy"] == "TimestampAscending"
    assert kwargs["StartTime"] == START
    assert kwargs["EndTime"] == END
    queries = kwargs["MetricDataQueries"]
    assert {q["Id"] for q in queries} == {"running", "desired"}
    running = next(q for q in queries if q["Id"] == "running")
    stat = running["MetricStat"]
    assert stat["Metric"]["Namespace"] == "ECS/ContainerInsights"
    assert stat["Metric"]["MetricName"] == "RunningTaskCount"
    assert stat["Period"] == 3600
    assert stat["Stat"] == "Maximum"
    assert stat["Metric"]["Dimensions"] == [
        {"Name": "ServiceName", "Value": "inventory"},
        {"Name": "ClusterName", "Value": "production"},
    ]


def test_fail_soft_returns_empty_on_client_error():
    client = MagicMock()
    client.get_metric_data.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "no"}}, "GetMetricData"
    )
    points = CloudWatchTaskMetrics(client, "production").task_history("inventory", START, END, 300)
    assert points == []
