import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

import { DateTimePicker } from "@/components/date-time-picker";

describe("DateTimePicker open", () => {
  it("opens the calendar popover on trigger click", async () => {
    render(<DateTimePicker value="2026-06-05T09:46" onChange={vi.fn()} />);
    fireEvent.click(screen.getByTestId("datetime-trigger"));
    expect(await screen.findByRole("grid")).toBeTruthy();
  });
});
