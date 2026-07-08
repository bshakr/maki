from maki.schemas import DeployedService


class AmplifyDeployRegistry:
    """Live, read-only view of the currently-deployed Amplify web app."""

    def __init__(self, client, app_id: str, branch: str, service_name: str = "web-app"):
        self._client = client
        self._app_id = app_id
        self._branch = branch
        self._service_name = service_name

    def get_deployed_web_app(self) -> DeployedService | None:
        branch = self._client.get_branch(appId=self._app_id, branchName=self._branch)["branch"]
        active_job_id = branch.get("activeJobId")
        if not active_job_id:
            return None
        summary = self._client.get_job(
            appId=self._app_id, branchName=self._branch, jobId=active_job_id
        )["job"]["summary"]
        return DeployedService(
            name=self._service_name,
            platform="amplify",
            git_sha=summary.get("commitId"),
            deployed_at=summary.get("endTime"),
            status=summary.get("status"),
        )
