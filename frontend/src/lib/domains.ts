import type { GroupingRule } from "@/api";

// Groups the fleet into collapsible sections by service NAME. The RULES are deployment-specific
// and come from config (useConfig().grouping_rules); this module is just the generic matcher.
//
// Rules are evaluated TOP-TO-BOTTOM, most-specific first: the first match wins. `exact` requires
// the whole name to equal `match`; otherwise the name must start with `match`. Anything unmatched
// falls back to "Other".
export const OTHER_DOMAIN = "Other";

export function serviceDomain(name: string, rules: GroupingRule[]): string {
  for (const rule of rules) {
    if (rule.exact ? name === rule.match : name.startsWith(rule.match)) {
      return rule.label;
    }
  }
  return OTHER_DOMAIN;
}
