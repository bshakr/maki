import { expect, test } from "vitest";

import { deriveServiceTab, serviceTabPath } from "@/lib/service-tabs";

test("bare service URL is the Deploys tab", () => {
  expect(deriveServiceTab("/services/wfm-service")).toBe("deploys");
});

test("the deploy-detail deep link still resolves to the Deploys tab", () => {
  expect(deriveServiceTab("/services/wfm-service/deploys/a1b2c3d")).toBe("deploys");
});

test("tasks/metrics/env segments select their tab", () => {
  expect(deriveServiceTab("/services/wfm-service/tasks")).toBe("tasks");
  expect(deriveServiceTab("/services/wfm-service/metrics")).toBe("metrics");
  expect(deriveServiceTab("/services/wfm-service/env")).toBe("env");
});

test("an unknown trailing segment falls back to Deploys", () => {
  expect(deriveServiceTab("/services/wfm-service/bogus")).toBe("deploys");
});

test("serviceTabPath: Deploys is the bare URL; others append the key (name encoded)", () => {
  expect(serviceTabPath("wfm-service", "deploys")).toBe("/services/wfm-service");
  expect(serviceTabPath("wfm-service", "tasks")).toBe("/services/wfm-service/tasks");
  expect(serviceTabPath("a/b", "env")).toBe("/services/a%2Fb/env");
});
