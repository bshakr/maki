import type { DeployedService, DeployRecord } from "@/api";

// The live current-deploy comes from the inventory read (describe_services); the
// history list comes from a separate list_task_definitions read. The two have
// independent SWR caches and can briefly disagree on the newest deploy. We treat
// inventory as authoritative for "what's live" and fold it into the history dataset.

/** Shape the live inventory service as a DeployRecord (revision unknown; live ⇒ finished). */
export function currentDeployRecord(svc: DeployedService): DeployRecord {
  return {
    // No DB row: this is synthesized live from inventory, so it has no deploy_events id. The
    // history list keys such a row by sha (it always carries one).
    id: null,
    sha: svc.git_sha,
    image: svc.image,
    revision: null,
    registered_at: svc.deployed_at,
    committed_at: svc.committed_at,
    author: svc.author,
    author_avatar_url: svc.author_avatar_url,
    message: svc.message,
    commit_url: svc.commit_url,
    pr_url: svc.pr_url,
    finished_at: svc.deployed_at,
    // The live service is, by definition, a succeeded forward deploy.
    status: "success",
    is_rollback: false,
  };
}

/**
 * Merge the live current deploy into the history list, deduped by sha.
 *
 * If the history fetch already carries the current sha, leave the list untouched —
 * that record is richer (real revision, registeredAt, finishedAt). Only when the
 * history read lags behind inventory do we synthesize the current row from the live
 * source and prepend it, so the card, the history filter, and the deep-link sheet all
 * resolve the same deploy.
 */
export function withCurrentDeploy(
  deployments: DeployRecord[] | undefined,
  svc: DeployedService | undefined,
): DeployRecord[] | undefined {
  if (!svc?.git_sha) return deployments;
  const list = deployments ?? [];
  if (list.some((d) => d.sha === svc.git_sha)) return deployments;
  return [currentDeployRecord(svc), ...list];
}
