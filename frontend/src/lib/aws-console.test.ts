import { expect, test } from "vitest";

import {
  cloudWatchLogsUrl,
  cloudWatchLogsUrlForGroup,
  logGroupForService,
} from "@/lib/aws-console";

const TEMPLATE = "/ecs/{service}-production";

test("logGroupForService substitutes {service} into the configured template", () => {
  expect(logGroupForService("wfm-service", TEMPLATE)).toBe(
    "/ecs/wfm-service-production",
  );
  expect(logGroupForService("api", "/logs/{service}")).toBe("/logs/api");
});

test("cloudWatchLogsUrl uses the server-provided region", () => {
  const url = cloudWatchLogsUrl("wfm-service", "us-east-1", TEMPLATE, "eu-west-1");
  expect(url).toContain("https://us-east-1.console.aws.amazon.com");
  expect(url).toContain("region=us-east-1");
  // The log-group path segment is double-slash-encoded for the console.
  expect(url).toContain("$252Fecs$252Fwfm-service-production");
});

test("cloudWatchLogsUrl falls back to the configured region when none is provided", () => {
  expect(cloudWatchLogsUrl("wfm-service", null, TEMPLATE, "ap-south-1")).toContain(
    "region=ap-south-1",
  );
  expect(
    cloudWatchLogsUrl("wfm-service", undefined, TEMPLATE, "ap-south-1"),
  ).toContain("https://ap-south-1.console.aws.amazon.com");
});

test("cloudWatchLogsUrlForGroup deep-links an explicit, non-convention group", () => {
  const url = cloudWatchLogsUrlForGroup("/ecs/inventory-real", "us-east-1", "eu-west-1");
  expect(url).toContain("https://us-east-1.console.aws.amazon.com");
  expect(url).toContain("region=us-east-1");
  expect(url).toContain("$252Fecs$252Finventory-real");
});

test("cloudWatchLogsUrlForGroup falls back to the configured region when absent", () => {
  expect(
    cloudWatchLogsUrlForGroup("/ecs/inventory-real", null, "ap-south-1"),
  ).toContain("region=ap-south-1");
});
