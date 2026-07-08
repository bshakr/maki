import { describe, expect, it } from "vitest";

import type { GroupingRule } from "@/api";
import { OTHER_DOMAIN, serviceDomain } from "@/lib/domains";

// Sample rules exercising both prefix and exact matching, ordered most-specific first.
const RULES: GroupingRule[] = [
  { match: "prod-workforce-payroll-", label: "Payroll", exact: false },
  { match: "prod-scheduling-assistant-", label: "Scheduling Assistant", exact: false },
  { match: "pos-ingestion", label: "POS Ingestion", exact: false },
  { match: "im-ingestion-", label: "IM Ingestion", exact: false },
  { match: "webhooks-", label: "Webhooks", exact: false },
  { match: "inventory", label: "Inventory", exact: false },
  { match: "wfm-service", label: "Workforce", exact: true },
  { match: "prod-schedule-versioning", label: "Workforce", exact: true },
];

describe("serviceDomain", () => {
  it("maps a prefix rule to its label", () => {
    expect(serviceDomain("prod-workforce-payroll-common", RULES)).toBe("Payroll");
    expect(serviceDomain("prod-workforce-payroll-worker", RULES)).toBe("Payroll");
    expect(serviceDomain("prod-scheduling-assistant-api", RULES)).toBe(
      "Scheduling Assistant",
    );
    expect(serviceDomain("pos-ingestion", RULES)).toBe("POS Ingestion");
    expect(serviceDomain("pos-ingestion-worker", RULES)).toBe("POS Ingestion");
    expect(serviceDomain("im-ingestion-worker", RULES)).toBe("IM Ingestion");
    expect(serviceDomain("webhooks-api", RULES)).toBe("Webhooks");
    expect(serviceDomain("inventory", RULES)).toBe("Inventory");
    expect(serviceDomain("inventory-worker", RULES)).toBe("Inventory");
  });

  it("matches exact rules only on the whole name", () => {
    expect(serviceDomain("wfm-service", RULES)).toBe("Workforce");
    expect(serviceDomain("prod-schedule-versioning", RULES)).toBe("Workforce");
    // A suffixed name must NOT match an exact rule — it falls through.
    expect(serviceDomain("wfm-service-extra", RULES)).toBe(OTHER_DOMAIN);
    expect(serviceDomain("prod-schedule-versioning-2", RULES)).toBe(OTHER_DOMAIN);
  });

  it("returns the first matching rule (top-to-bottom)", () => {
    const rules: GroupingRule[] = [
      { match: "api", label: "First", exact: false },
      { match: "api", label: "Second", exact: false },
    ];
    expect(serviceDomain("api-gateway", rules)).toBe("First");
  });

  it("falls back to Other for unrecognised names or empty rules", () => {
    expect(serviceDomain("newsfeed", RULES)).toBe(OTHER_DOMAIN);
    expect(serviceDomain("", RULES)).toBe(OTHER_DOMAIN);
    expect(serviceDomain("inventory", [])).toBe(OTHER_DOMAIN);
  });
});
