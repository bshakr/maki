import { render, screen } from "@testing-library/react";
import { Cloud, Code } from "lucide-react";
import { expect, test } from "vitest";

import { NavSecondary } from "./nav-secondary";
import { SidebarProvider } from "@/components/ui/sidebar";

test("renders secondary items as external links", () => {
  render(
    <SidebarProvider>
      <NavSecondary
        items={[
          { title: "GitHub", url: "https://github.com/acme/platform", icon: Code },
          { title: "AWS Console", url: "https://aws.example.com", icon: Cloud },
        ]}
      />
    </SidebarProvider>
  );

  const github = screen.getByRole("link", { name: /github/i });
  expect(github).toHaveAttribute("href", "https://github.com/acme/platform");
  expect(github).toHaveAttribute("target", "_blank");
  expect(github).toHaveAttribute("rel", "noreferrer");

  expect(
    screen.getByRole("link", { name: /aws console/i })
  ).toHaveAttribute("href", "https://aws.example.com");
});
