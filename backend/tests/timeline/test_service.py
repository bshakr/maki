from datetime import UTC, datetime
from unittest.mock import MagicMock

from maki.schemas import DeployedService, ServicesResponse
from maki.timeline.service import TimelineService

TD_REV7 = "arn:aws:ecs:eu-west-1:1:task-definition/wfm-service:7"

CREATED = datetime(2026, 5, 29, 4, 0, 0, tzinfo=UTC)
STARTED = datetime(2026, 5, 29, 4, 0, 12, tzinfo=UTC)
FINISHED = datetime(2026, 5, 29, 4, 3, 16, tzinfo=UTC)
MERGED = datetime(2026, 5, 29, 3, 50, 0, tzinfo=UTC)


def _inventory(svc):
    inv = MagicMock()
    inv.get_inventory.return_value = ServicesResponse(
        services=[svc] if svc else [], generated_at=datetime.now(UTC)
    )
    return inv


def _ecs_client(task_def_arn=TD_REV7, has_service=True):
    client = MagicMock()
    services = [{"taskDefinition": task_def_arn}] if has_service else []
    client.describe_services.return_value = {"services": services}
    return client


def _svc():
    return DeployedService(
        name="wfm-service",
        platform="ecs",
        git_sha="cf930b6",
        committed_at=MERGED,
        deployed_at=FINISHED,
    )


def _make(
    inventory,
    ecs,
    deployment,
    jobs,
    repo="acme/platform",
    rollout_suffixes=None,
    rollout_prefixes=None,
    group_matrix_jobs=None,
    enabled=None,
    actions=None,
):
    sd = MagicMock()
    sd.deployment_for_revision.return_value = deployment
    if actions is None:
        actions = MagicMock()
        actions.jobs_for_sha.return_value = jobs
    kwargs = {}
    if rollout_suffixes is not None:
        kwargs["rollout_suffixes"] = rollout_suffixes
    if rollout_prefixes is not None:
        kwargs["rollout_prefixes"] = rollout_prefixes
    if group_matrix_jobs is not None:
        kwargs["group_matrix_jobs"] = group_matrix_jobs
    if enabled is not None:
        kwargs["enabled"] = enabled
    return TimelineService(
        inventory=inventory,
        ecs_client=ecs,
        cluster="production",
        service_deployments=sd,
        actions=actions,
        repo_for=lambda _n: repo,
        fresh_seconds=0.0,
        stale_seconds=0.0,
        **kwargs,
    )


def _ecs_deploy():
    return {
        "created_at": CREATED,
        "started_at": STARTED,
        "finished_at": FINISHED,
        "status": "SUCCESSFUL",
    }


def _jobs():
    return [
        {
            "name": "Build",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:55:38Z",
            "conclusion": "success",
        },
        {
            "name": "Test",
            "started_at": "2026-05-29T03:56:00Z",
            "completed_at": "2026-05-29T03:57:12Z",
            "conclusion": "failure",
        },
    ]


def test_actions_jobs_map_to_ci_segments():
    out = _make(_inventory(_svc()), _ecs_client(), None, _jobs()).get_timeline("wfm-service")
    ci = [s for s in out.segments if s.source == "github_actions"]
    assert [s.key for s in ci] == ["ci:build", "ci:test"]
    assert ci[0].label == "Build"
    assert ci[0].seconds == 38
    assert ci[0].count == 1
    assert ci[0].status == "success"
    assert ci[1].status == "failed"


def test_parallel_matrix_jobs_collapse_to_one_phase_with_wall_clock_span():
    # `test (0)` + `test (1)` run in PARALLEL: one Test phase, span = wall-clock
    # max(end) - min(start), NOT the sum of the two job durations.
    jobs = [
        {
            "name": "test (0)",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:56:00Z",  # 60s
            "conclusion": "success",
        },
        {
            "name": "test (1)",
            "started_at": "2026-05-29T03:55:10Z",
            "completed_at": "2026-05-29T03:57:00Z",  # overlaps the first
            "conclusion": "success",
        },
    ]
    out = _make(_inventory(_svc()), _ecs_client(), None, jobs).get_timeline("wfm-service")
    ci = [s for s in out.segments if s.source == "github_actions"]
    assert [s.key for s in ci] == ["ci:test"]
    phase = ci[0]
    assert phase.label == "test"
    assert phase.count == 2
    # wall-clock span 03:55:00 -> 03:57:00 = 120s (NOT 60 + 110 = 170)
    assert phase.seconds == 120
    assert phase.status == "success"


def test_image_tags_fanout_collapses_with_count():
    jobs = [
        {
            "name": "image-tags / image-tags",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:55:09Z",
            "conclusion": "success",
        }
        for _ in range(10)
    ]
    out = _make(_inventory(_svc()), _ecs_client(), None, jobs).get_timeline("wfm-service")
    ci = [s for s in out.segments if s.source == "github_actions"]
    assert [s.key for s in ci] == ["ci:image-tags"]
    assert ci[0].label == "image-tags"
    assert ci[0].count == 10


def test_rollout_jobs_excluded_from_ci_segments():
    # `* / schedule` and `deploy / deploy` and `deploy-*` are per-service ECS
    # rollouts, not shared CI; only the build/image-tags jobs remain.
    jobs = [
        {
            "name": "image-tags / image-tags",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:55:09Z",
            "conclusion": "success",
        },
        {
            "name": "deploy / deploy",
            "started_at": "2026-05-29T03:56:00Z",
            "completed_at": "2026-05-29T04:01:00Z",
            "conclusion": "success",
        },
        {
            "name": "schedule-holiday-reset / schedule",
            "started_at": "2026-05-29T03:56:00Z",
            "completed_at": "2026-05-29T04:02:00Z",
            "conclusion": "success",
        },
        {
            "name": "deploy-inventory-service / deploy",
            "started_at": "2026-05-29T03:56:00Z",
            "completed_at": "2026-05-29T04:02:00Z",
            "conclusion": "success",
        },
    ]
    out = _make(_inventory(_svc()), _ecs_client(), None, jobs).get_timeline("wfm-service")
    ci = [s for s in out.segments if s.source == "github_actions"]
    assert [s.key for s in ci] == ["ci:image-tags"]


def test_unrelated_workflow_run_on_same_sha_is_dropped():
    # jobs_for_sha returns jobs across EVERY run for the sha. The deploy run (101)
    # ran at merge; a later dependency-upgrade run (202) touched the same sha with an
    # 11-minute `update-dep` job hours later. The detached run must be dropped so it
    # doesn't stretch the axis.
    jobs = [
        {
            "name": "image-tags / image-tags",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:55:09Z",
            "conclusion": "success",
            "run_id": 101,
        },
        {
            "name": "update-dep",
            "started_at": "2026-05-29T08:00:00Z",
            "completed_at": "2026-05-29T08:11:00Z",
            "conclusion": "success",
            "run_id": 202,
        },
    ]
    out = _make(_inventory(_svc()), _ecs_client(), None, jobs).get_timeline("wfm-service")
    ci = [s for s in out.segments if s.source == "github_actions"]
    # Only the merge-time run's CI phase survives; update-dep is detached -> dropped.
    assert [s.key for s in ci] == ["ci:image-tags"]


def test_run_urls_present_in_run_order_for_kept_runs():
    # Two runs survive the merge-time cluster (101 then 102); a later, detached
    # run (303) is dropped. Only the kept runs' URLs appear, earliest run first.
    jobs = [
        {
            "name": "test (0)",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:58:00Z",
            "conclusion": "success",
            "run_id": 101,
            "html_url": "https://github.com/acme/platform/actions/runs/101",
        },
        {
            "name": "image-tags / image-tags",
            "started_at": "2026-05-29T03:58:30Z",
            "completed_at": "2026-05-29T03:59:00Z",
            "conclusion": "success",
            "run_id": 102,
            "html_url": "https://github.com/acme/platform/actions/runs/102",
        },
        {
            "name": "update-dep",
            "started_at": "2026-05-29T09:00:00Z",
            "completed_at": "2026-05-29T09:11:00Z",
            "conclusion": "success",
            "run_id": 303,
            "html_url": "https://github.com/acme/platform/actions/runs/303",
        },
    ]
    out = _make(_inventory(_svc()), _ecs_client(), None, jobs).get_timeline("wfm-service")
    assert out.run_urls == [
        "https://github.com/acme/platform/actions/runs/101",
        "https://github.com/acme/platform/actions/runs/102",
    ]


def test_run_urls_empty_when_no_actions_jobs():
    out = _make(_inventory(_svc()), _ecs_client(), _ecs_deploy(), []).get_timeline("wfm-service")
    assert out.run_urls == []


def test_contiguous_runs_at_merge_are_all_kept():
    # A real deploy spans several runs firing at merge: a CI/test run (101) and a
    # separate build+deploy run (102) that starts moments later. Both belong to this
    # deploy's activity cluster and must be kept — even though the genuine CI run has
    # no rollout job. A later dependency-upgrade run (303) is dropped.
    jobs = [
        {
            "name": "test (0)",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:58:00Z",
            "conclusion": "success",
            "run_id": 101,
        },
        {
            "name": "checks",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:56:00Z",
            "conclusion": "success",
            "run_id": 101,
        },
        {
            "name": "image-tags / image-tags",
            "started_at": "2026-05-29T03:58:30Z",
            "completed_at": "2026-05-29T03:59:00Z",
            "conclusion": "success",
            "run_id": 102,
        },
        {
            "name": "deploy-wfm-service / deploy",
            "started_at": "2026-05-29T03:59:00Z",
            "completed_at": "2026-05-29T04:03:00Z",
            "conclusion": "success",
            "run_id": 102,
        },
        {
            "name": "update-dep",
            "started_at": "2026-05-29T09:00:00Z",
            "completed_at": "2026-05-29T09:11:00Z",
            "conclusion": "success",
            "run_id": 303,
        },
    ]
    out = _make(_inventory(_svc()), _ecs_client(), None, jobs).get_timeline("wfm-service")
    ci = [s for s in out.segments if s.source == "github_actions"]
    # Both merge-time runs kept (rollout job stripped), update-dep dropped.
    assert [s.key for s in ci] == ["ci:checks", "ci:test", "ci:image-tags"]


def test_trigger_deploy_is_not_a_rollout():
    # 'trigger-deploy' has no ' / deploy' suffix and doesn't start 'deploy-'.
    jobs = [
        {
            "name": "trigger-deploy",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:55:05Z",
            "conclusion": "success",
        }
    ]
    out = _make(_inventory(_svc()), _ecs_client(), None, jobs).get_timeline("wfm-service")
    ci = [s for s in out.segments if s.source == "github_actions"]
    assert [s.key for s in ci] == ["ci:trigger-deploy"]


def test_worst_status_wins_within_a_collapsed_phase():
    jobs = [
        {
            "name": "test (0)",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:56:00Z",
            "conclusion": "success",
        },
        {
            "name": "test (1)",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:56:30Z",
            "conclusion": "failure",
        },
    ]
    out = _make(_inventory(_svc()), _ecs_client(), None, jobs).get_timeline("wfm-service")
    ci = [s for s in out.segments if s.source == "github_actions"]
    assert [s.key for s in ci] == ["ci:test"]
    assert ci[0].status == "failed"


def test_in_progress_ci_status_when_no_conclusion():
    jobs = [{"name": "build", "started_at": "2026-05-29T04:00:00Z", "conclusion": None}]
    out = _make(_inventory(_svc()), _ecs_client(), None, jobs).get_timeline("wfm-service")
    seg = next(s for s in out.segments if s.key == "ci:build")
    assert seg.status == "in_progress"
    assert seg.seconds is None  # no completed_at


def test_ecs_deployment_maps_to_queued_and_rollout():
    out = _make(_inventory(_svc()), _ecs_client(), _ecs_deploy(), []).get_timeline("wfm-service")
    keys = [s.key for s in out.segments]
    assert keys == ["ecs:queued", "ecs:rollout"]
    queued = out.segments[0]
    rollout = out.segments[1]
    assert queued.start == CREATED and queued.end == STARTED and queued.seconds == 12
    assert rollout.start == STARTED and rollout.end == FINISHED and rollout.seconds == 184
    assert queued.status == "success" and rollout.status == "success"
    assert out.live_at == FINISHED
    assert out.total_seconds == int((FINISHED - MERGED).total_seconds())


def test_segments_ordered_by_start_across_sources():
    out = _make(_inventory(_svc()), _ecs_client(), _ecs_deploy(), _jobs()).get_timeline(
        "wfm-service"
    )
    starts = [s.start for s in out.segments]
    assert starts == sorted(starts)
    # CI (03:55) precedes ECS (04:00)
    assert out.segments[0].source == "github_actions"
    assert out.segments[-1].key == "ecs:rollout"


def test_equal_start_phases_order_stably_by_end_then_key():
    # Three CI phases share the SAME start. Tiebreak must be deterministic:
    # by end (earlier first), then by key. 'alpha' and 'beta' share an end too,
    # so the final tiebreak falls to the key ('ci:alpha' < 'ci:beta').
    same_start = "2026-05-29T03:55:00Z"
    jobs = [
        {
            "name": "beta",
            "started_at": same_start,
            "completed_at": "2026-05-29T03:56:00Z",
            "conclusion": "success",
        },
        {
            "name": "alpha",
            "started_at": same_start,
            "completed_at": "2026-05-29T03:56:00Z",  # same end as beta
            "conclusion": "success",
        },
        {
            "name": "gamma",
            "started_at": same_start,
            "completed_at": "2026-05-29T03:55:30Z",  # ends EARLIER -> sorts first
            "conclusion": "success",
        },
    ]
    out = _make(_inventory(_svc()), _ecs_client(), None, jobs).get_timeline("wfm-service")
    ci = [s for s in out.segments if s.source == "github_actions"]
    # gamma ends first; alpha before beta because they tie on start+end -> key.
    assert [s.key for s in ci] == ["ci:gamma", "ci:alpha", "ci:beta"]


def test_rollout_suffix_is_configurable():
    # A job whose reusable suffix is 'release' is a rollout ONLY when 'release'
    # is in the configured suffix set; with the defaults it stays in the CI timeline.
    jobs = [
        {
            "name": "release-web / release",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:56:00Z",
            "conclusion": "success",
        }
    ]
    # Default suffixes ({deploy, schedule}): 'release' is NOT excluded.
    out_default = _make(_inventory(_svc()), _ecs_client(), None, jobs).get_timeline("wfm-service")
    ci_default = [s for s in out_default.segments if s.source == "github_actions"]
    assert [s.key for s in ci_default] == ["ci:release-web"]

    # Configured suffixes ('release',): the job IS excluded as a rollout.
    out_cfg = _make(
        _inventory(_svc()), _ecs_client(), None, jobs, rollout_suffixes=("release",)
    ).get_timeline("wfm-service")
    ci_cfg = [s for s in out_cfg.segments if s.source == "github_actions"]
    assert ci_cfg == []


def test_no_token_or_empty_actions_yields_only_ecs_segments():
    out = _make(_inventory(_svc()), _ecs_client(), _ecs_deploy(), []).get_timeline("wfm-service")
    assert {s.source for s in out.segments} == {"ecs"}
    assert out.merged_at == MERGED
    assert out.live_at == FINISHED


def test_unmapped_service_yields_no_ci_segments():
    out = _make(
        _inventory(_svc()), _ecs_client(), None, _jobs(), repo=None
    ).get_timeline("wfm-service")
    assert [s for s in out.segments if s.source == "github_actions"] == []


def test_no_ecs_deployment_yields_only_ci_segments():
    out = _make(_inventory(_svc()), _ecs_client(), None, _jobs()).get_timeline("wfm-service")
    assert {s.source for s in out.segments} == {"github_actions"}
    # live_at falls back to deployed_at; total still computable
    assert out.live_at == FINISHED
    assert out.total_seconds == int((FINISHED - MERGED).total_seconds())


def test_neither_source_yields_empty_segments_with_fallback_totals():
    out = _make(_inventory(_svc()), _ecs_client(), None, []).get_timeline("wfm-service")
    assert out.segments == []
    # totals from committed -> deployed fallback
    assert out.merged_at == MERGED
    assert out.live_at == FINISHED
    assert out.total_seconds == int((FINISHED - MERGED).total_seconds())


def test_total_seconds_none_when_merged_unknown():
    svc = _svc()
    svc.committed_at = None
    svc.deployed_at = None
    out = _make(_inventory(svc), _ecs_client(), None, []).get_timeline("wfm-service")
    assert out.total_seconds is None
    assert out.merged_at is None
    assert out.live_at is None


def test_describe_services_failure_drops_ecs_but_keeps_ci():
    ecs = MagicMock()
    ecs.describe_services.side_effect = RuntimeError("AccessDenied")
    out = _make(_inventory(_svc()), ecs, _ecs_deploy(), _jobs()).get_timeline("wfm-service")
    # ECS segments dropped because family/revision couldn't resolve; CI still present
    assert {s.source for s in out.segments} == {"github_actions"}


def test_service_missing_from_inventory_yields_empty():
    out = _make(_inventory(None), _ecs_client(has_service=False), None, []).get_timeline("gone")
    assert out.service == "gone"
    assert out.sha is None
    assert out.segments == []
    assert out.total_seconds is None


def test_empty_rollout_prefixes_and_suffixes_keep_deploy_jobs():
    # With hideJobsStartingWith=[] and hideJobsEndingWith=[], a 'deploy / deploy'
    # job and a 'deploy-foo' job are NO LONGER rollouts — they appear as CI phases.
    jobs = [
        {
            "name": "deploy / deploy",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:56:00Z",
            "conclusion": "success",
        },
        {
            "name": "deploy-foo",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:56:00Z",
            "conclusion": "success",
        },
    ]
    out = _make(
        _inventory(_svc()),
        _ecs_client(),
        None,
        jobs,
        rollout_suffixes=(),
        rollout_prefixes=(),
    ).get_timeline("wfm-service")
    ci = [s for s in out.segments if s.source == "github_actions"]
    assert {s.key for s in ci} == {"ci:deploy", "ci:deploy-foo"}


def test_rollout_prefix_is_configurable():
    # 'ship-' as the configured prefix excludes 'ship-web'; the default 'deploy-'
    # prefix no longer applies, so 'deploy-foo' stays as a CI phase.
    jobs = [
        {
            "name": "ship-web",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:56:00Z",
            "conclusion": "success",
        },
        {
            "name": "deploy-foo",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:56:00Z",
            "conclusion": "success",
        },
    ]
    out = _make(
        _inventory(_svc()),
        _ecs_client(),
        None,
        jobs,
        rollout_prefixes=("ship-",),
    ).get_timeline("wfm-service")
    ci = [s for s in out.segments if s.source == "github_actions"]
    assert [s.key for s in ci] == ["ci:deploy-foo"]


def test_matrix_jobs_kept_separate_when_grouping_disabled():
    # groupMatrixJobs=False: 'test (0)' and 'test (1)' are DISTINCT job names, so
    # each is its own segment — parens are NOT stripped and nothing collapses.
    jobs = [
        {
            "name": "test (0)",
            "started_at": "2026-05-29T03:55:00Z",
            "completed_at": "2026-05-29T03:56:00Z",
            "conclusion": "success",
        },
        {
            "name": "test (1)",
            "started_at": "2026-05-29T03:55:10Z",
            "completed_at": "2026-05-29T03:57:00Z",
            "conclusion": "success",
        },
    ]
    out = _make(
        _inventory(_svc()),
        _ecs_client(),
        None,
        jobs,
        group_matrix_jobs=False,
    ).get_timeline("wfm-service")
    ci = [s for s in out.segments if s.source == "github_actions"]
    assert [s.key for s in ci] == ["ci:test-0", "ci:test-1"]
    assert [s.label for s in ci] == ["test (0)", "test (1)"]
    assert all(s.count == 1 for s in ci)


def test_disabled_timeline_yields_empty_segments_and_skips_github():
    actions = MagicMock()
    actions.jobs_for_sha.return_value = _jobs()
    out = _make(
        _inventory(_svc()),
        _ecs_client(),
        _ecs_deploy(),
        _jobs(),
        enabled=False,
        actions=actions,
    ).get_timeline("wfm-service")
    assert out.segments == []
    assert out.total_seconds is None
    assert out.merged_at is None
    assert out.live_at is None
    # Valid response shell still returned.
    assert out.service == "wfm-service"
    assert out.sha is None
    assert out.generated_at is not None
    # GitHub Actions is never queried when the feature is off.
    actions.jobs_for_sha.assert_not_called()
