import { describe, expect, it } from "vitest";

import {
  ago,
  compactImage,
  formatDuration,
  leadTimeSeconds,
  shortSha,
  statusBadgeVariant,
} from "@/lib/format";

describe("statusBadgeVariant", () => {
  it("maps COMPLETED / SUCCEED to success", () => {
    expect(statusBadgeVariant("COMPLETED")).toBe("success");
    expect(statusBadgeVariant("PROVISION_SUCCEEDED")).toBe("success");
  });

  it("maps IN_PROGRESS to default", () => {
    expect(statusBadgeVariant("IN_PROGRESS")).toBe("default");
  });

  it("maps failures and unavailability to destructive", () => {
    expect(statusBadgeVariant("FAILED")).toBe("destructive");
    expect(statusBadgeVariant("error")).toBe("destructive");
    expect(statusBadgeVariant("service unavailable")).toBe("destructive");
  });

  it("maps null and unknown statuses to outline", () => {
    expect(statusBadgeVariant(null)).toBe("outline");
    expect(statusBadgeVariant("SOMETHING_ELSE")).toBe("outline");
  });

  it("maps Amplify RUNNING to default", () => {
    expect(statusBadgeVariant("RUNNING")).toBe("default");
  });

  it("maps Amplify CANCELLED to destructive", () => {
    expect(statusBadgeVariant("CANCELLED")).toBe("destructive");
  });
});

describe("leadTimeSeconds", () => {
  it("returns the seconds between merged and live when both parse", () => {
    expect(
      leadTimeSeconds("2026-05-31T04:00:00Z", "2026-05-31T07:00:00Z"),
    ).toBe(3 * 3600);
  });

  it("returns null when either timestamp is missing", () => {
    expect(leadTimeSeconds(null, "2026-05-31T07:00:00Z")).toBeNull();
    expect(leadTimeSeconds("2026-05-31T04:00:00Z", null)).toBeNull();
    expect(leadTimeSeconds(null, null)).toBeNull();
  });

  it("returns null when live is before merged (negative)", () => {
    expect(
      leadTimeSeconds("2026-05-31T07:00:00Z", "2026-05-31T04:00:00Z"),
    ).toBeNull();
  });

  it("returns null when a timestamp is unparseable", () => {
    expect(leadTimeSeconds("not-a-date", "2026-05-31T07:00:00Z")).toBeNull();
  });
});

describe("ago", () => {
  it("clamps a future timestamp (clock skew) to 0s ago", () => {
    expect(ago(new Date(Date.now() + 5000).toISOString())).toBe("0s ago");
  });
});

describe("formatDuration", () => {
  it("clamps a negative duration to 0s", () => {
    expect(formatDuration(-30)).toBe("0s");
  });
});

describe("shortSha", () => {
  it("truncates to 7 chars, em-dash for null", () => {
    expect(shortSha("0123456789abcdef")).toBe("0123456");
    expect(shortSha(null)).toBe("—");
  });
});

describe("compactImage", () => {
  it("collapses an ECR URI to repo + short sha tag", () => {
    expect(
      compactImage(
        "123456789012.dkr.ecr.eu-west-1.amazonaws.com/nlabour:cf930b6819ffc",
      ),
    ).toBe("nlabour:cf930b6");
  });

  it("keeps short / non-sha tags intact", () => {
    expect(compactImage("x/wfm-service:latest")).toBe("wfm-service:latest");
    expect(compactImage("x/wfm-service:v1.2.3")).toBe("wfm-service:v1.2.3");
  });

  it("handles a path with no tag", () => {
    expect(compactImage("repo/path/name")).toBe("name");
  });

  it("returns em-dash for null", () => {
    expect(compactImage(null)).toBe("—");
  });
});
