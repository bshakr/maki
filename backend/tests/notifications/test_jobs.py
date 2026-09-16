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
