// Frontend builders for the ECS log-group convention + its CloudWatch console deep-link.
//
// The backend owns the authoritative values (the resolved log group + region come back on every
// logs payload — prefer those at call sites). These helpers cover the one place with no server
// value yet: the current-deploy console link, built before any logs response is fetched. The
// log-group template and the region fallback are deployment-specific and come from config
// (useConfig().log_group_template / .aws_region) — passed in, never hardcoded here.

// The ECS log group for a service: substitute `{service}` into the configured template
// (e.g. "/ecs/{service}-production"). The backend value (ServiceLogsResponse.log_group) is
// authoritative once a logs read returns.
export function logGroupForService(name: string, template: string): string {
  return template.split("{service}").join(name);
}

// Deep-link a service's log group to the CloudWatch console, using the configured template and a
// region fallback for when the server hasn't supplied a per-service region yet.
export function cloudWatchLogsUrl(
  name: string,
  region: string | null | undefined,
  template: string,
  fallbackRegion: string,
): string {
  return cloudWatchLogsUrlForGroup(
    logGroupForService(name, template),
    region,
    fallbackRegion,
  );
}

// Deep-link an explicit, already-resolved log group to the CloudWatch console. Prefer this over
// `cloudWatchLogsUrl` once the backend returns the authoritative `ServiceLogsResponse.log_group`.
// `$252F` are the console's double-encoded slashes in the log-group path segment.
export function cloudWatchLogsUrlForGroup(
  logGroup: string,
  region: string | null | undefined,
  fallbackRegion: string,
): string {
  const r = region || fallbackRegion;
  const group = logGroup.replace(/\//g, "$252F");
  return `https://${r}.console.aws.amazon.com/cloudwatch/home?region=${r}#logsV2:log-groups/log-group/${group}`;
}
