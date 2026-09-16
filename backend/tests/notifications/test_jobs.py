from maki.notifications.jobs import is_deploy_job_for

PREFIXES = ["deploy-"]
SUFFIXES = ["deploy"]


def test_matches_prefixed_deploy_job():
    assert is_deploy_job_for("deploy-insights", "insights", PREFIXES, SUFFIXES) is True


def test_matches_suffixed_deploy_job_after_separator():
    assert is_deploy_job_for("build / insights deploy", "insights", PREFIXES, SUFFIXES) is True


def test_rejects_sibling_service_in_same_repo():
    assert is_deploy_job_for("deploy-worker", "insights", PREFIXES, SUFFIXES) is False


def test_rejects_non_deploy_job_naming_the_service():
    assert is_deploy_job_for("test-insights", "insights", PREFIXES, SUFFIXES) is False


def test_is_case_insensitive():
    assert is_deploy_job_for("Deploy-Insights", "insights", PREFIXES, SUFFIXES) is True


def test_matches_service_named_in_the_reusable_workflow_caller():
    # The common shape: a per-service caller job calls a shared reusable deploy workflow, and
    # GitHub renders it "deploy-insights / deploy" — the service is in the caller, not the callee.
    assert is_deploy_job_for("deploy-insights / deploy", "insights", PREFIXES, SUFFIXES) is True


def test_rejects_sibling_service_whose_name_extends_this_one():
    assert is_deploy_job_for("deploy-insights-worker", "insights", PREFIXES, SUFFIXES) is False


def test_matches_the_longer_sibling_on_its_own_job():
    assert (
        is_deploy_job_for("deploy-insights-worker", "insights-worker", PREFIXES, SUFFIXES) is True
    )


def test_rejects_shared_deploy_job_that_names_no_service():
    assert is_deploy_job_for("deploy / deploy", "insights", PREFIXES, SUFFIXES) is False


def test_matches_suffix_attached_by_separator():
    assert is_deploy_job_for("insights-deploy", "insights", PREFIXES, SUFFIXES) is True


# The cases below use real Noryai/nory job names and real ECS service names — see
# ci-job-name-evidence.md. CI job tokens drop the env/domain prefix the ECS names carry, so the
# job token is a separator-bounded suffix of the service rather than the whole of it.


def test_matches_real_job_whose_token_is_a_suffix_of_the_service():
    assert (
        is_deploy_job_for(
            "deploy-reconciliation-shift-sweep / deploy",
            "prod-workforce-payroll-reconciliation-shift-sweep",
            PREFIXES,
            SUFFIXES,
        )
        is True
    )


def test_matches_real_job_whose_token_overlaps_the_service_prefix():
    assert (
        is_deploy_job_for(
            "deploy-payroll-common / deploy",
            "prod-workforce-payroll-common",
            PREFIXES,
            SUFFIXES,
        )
        is True
    )


def test_suffix_match_requires_a_separator_boundary():
    # 'common' must not match a service merely ending in those letters.
    assert (
        is_deploy_job_for(
            "deploy-common / deploy", "prod-workforce-payroll-uncommon", PREFIXES, SUFFIXES
        )
        is False
    )


def test_rejects_real_sibling_whose_token_extends_the_service():
    assert (
        is_deploy_job_for(
            "deploy-inventory-report-preload / deploy", "inventory", PREFIXES, SUFFIXES
        )
        is False
    )


def test_rejects_real_sibling_whose_service_extends_the_token():
    assert (
        is_deploy_job_for(
            "deploy-inventory / deploy", "inventory-report-preload", PREFIXES, SUFFIXES
        )
        is False
    )


def test_known_unmatched_when_ci_and_ecs_names_diverge():
    # 'entity-sync-batch' vs 'employee-sync-batch' is a genuine naming divergence no derivation
    # rule can bridge; pinned so the gap is documented rather than surprising.
    assert (
        is_deploy_job_for(
            "deploy-entity-sync-batch / deploy",
            "prod-workforce-payroll-employee-sync-batch",
            PREFIXES,
            SUFFIXES,
        )
        is False
    )


def test_matching_does_not_depend_on_prefix_list_order():
    # Every configured prefix is tried, so a longer prefix is not masked by a shorter one.
    for prefixes in (["deploy-", "deploy-prod-"], ["deploy-prod-", "deploy-"]):
        assert is_deploy_job_for("deploy-prod-inventory", "inventory", prefixes, SUFFIXES) is True
