from fastapi import APIRouter

from maki.config import AppConfig
from maki.schemas import GroupingRuleView, ThemeView, UiConfigResponse
from maki.settings import settings

router = APIRouter(prefix="/api")


def ui_config_from(cfg: AppConfig) -> UiConfigResponse:
    """Project the ingested config down to the UI-relevant subset the SPA reads at boot.

    Deliberately excludes the repo map and any operational/secret-bearing fields — only what the
    frontend needs to brand itself, group services, build console links, and toggle features.
    """
    theme = ThemeView(light=cfg.theme.light, dark=cfg.theme.dark) if cfg.theme else None
    return UiConfigResponse(
        app_name=cfg.branding.appName,
        theme=theme,
        env_label=cfg.envLabel,
        aws_region=cfg.aws.region,
        log_group_template=cfg.aws.logGroupTemplate,
        amplify_enabled=cfg.amplify.enabled,
        grouping_rules=[
            GroupingRuleView(match=r.match, label=r.label, exact=r.exact)
            for r in cfg.grouping.rules
        ],
        deploy_timeline_enabled=cfg.deployTimeline.enabled,
        watches_enabled=settings.watch_enabled,
        auth_required=settings.auth_required,
    )


@router.get("/config", response_model=UiConfigResponse)
def get_ui_config() -> UiConfigResponse:
    return ui_config_from(settings.config)
