import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { expect, test } from "vitest";

import { ServiceMultiSelect } from "./service-multiselect";

function Harness({ options }: { options: string[] }) {
  const [selected, setSelected] = useState<string[]>([]);
  return (
    <ServiceMultiSelect
      options={options}
      selected={selected}
      onChange={setSelected}
    />
  );
}

const OPTIONS = ["inventory", "wfm-service", "pos-ingestion"];

test("trigger shows 'All services' when nothing is selected", () => {
  render(<Harness options={OPTIONS} />);
  expect(screen.getByTestId("service-filter-trigger")).toHaveTextContent(
    "All services",
  );
});

test("selecting one service shows its name; selecting a second shows a count", async () => {
  render(<Harness options={OPTIONS} />);
  const trigger = screen.getByTestId("service-filter-trigger");

  fireEvent.click(trigger);
  fireEvent.click(await screen.findByRole("option", { name: /inventory/i }));
  await waitFor(() => expect(trigger).toHaveTextContent("inventory"));

  fireEvent.click(await screen.findByRole("option", { name: /wfm-service/i }));
  await waitFor(() => expect(trigger).toHaveTextContent("2 services"));
});

test("search filters the option list", async () => {
  render(<Harness options={OPTIONS} />);
  fireEvent.click(screen.getByTestId("service-filter-trigger"));

  const search = await screen.findByPlaceholderText(/search services/i);
  fireEvent.change(search, { target: { value: "pos" } });

  await waitFor(() =>
    expect(screen.queryByRole("option", { name: /inventory/i })).toBeNull(),
  );
  expect(screen.getByRole("option", { name: /pos-ingestion/i })).toBeInTheDocument();
});

test("clear resets the selection", async () => {
  render(<Harness options={OPTIONS} />);
  const trigger = screen.getByTestId("service-filter-trigger");

  fireEvent.click(trigger);
  fireEvent.click(await screen.findByRole("option", { name: /inventory/i }));
  await waitFor(() => expect(trigger).toHaveTextContent("inventory"));

  fireEvent.click(await screen.findByRole("option", { name: /clear filter/i }));
  await waitFor(() => expect(trigger).toHaveTextContent("All services"));
});
