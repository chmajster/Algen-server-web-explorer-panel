import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type ActivityResponse, type ActivitySummary } from "../../api";
import { ActivityCenter } from "./ActivityCenter";

vi.mock("../../api", () => ({ api: { activity: vi.fn(), activitySummary: vi.fn() } }));

const translations: Record<string, string> = {
  "activity.action.login": "Sign in",
  "activity.action.mkdir": "Create folder",
  "activity.actor": "User",
  "activity.category": "Category",
  "activity.search": "Search activity",
  "activity.status": "Status",
};
const t = (key: string) => translations[key] || key;
const summary: ActivitySummary = {
  total: 2,
  categories: { login: 1, file: 1, configuration: 0, administration: 0, module: 0 },
  statuses: { success: 2, failure: 0, info: 0, queued: 0, cancelled: 0 },
  latest_at: 1_700_000_100,
  scope: "global",
};
const response: ActivityResponse = {
  items: [
    { id: 2, created_at: 1_700_000_100, actor: "bob", category: "file", action: "mkdir", target: "/home/bob/docs", status: "success", summary: "", details: {}, source: "files" },
    { id: 1, created_at: 1_700_000_000, actor: "alice", category: "login", action: "login", target: "", status: "success", summary: "", details: {}, source: "auth" },
  ],
  total: 2,
  page: 1,
  page_size: 50,
  total_pages: 1,
  scope: "global",
};

describe("ActivityCenter", () => {
  const activity = vi.mocked(api.activity);
  const activitySummary = vi.mocked(api.activitySummary);

  beforeEach(() => {
    activity.mockReset().mockResolvedValue(response);
    activitySummary.mockReset().mockResolvedValue(summary);
  });

  it("renders global login, file and actor activity with status text", async () => {
    render(<ActivityCenter locale="en-US" t={t} />);

    expect(await screen.findByText("Create folder")).toBeInTheDocument();
    expect(screen.getByText("Sign in")).toBeInTheDocument();
    expect(screen.getByText("/home/bob/docs")).toBeInTheDocument();
    expect(screen.getByLabelText("User")).toBeInTheDocument();
    expect(document.querySelectorAll(".activity-status.success")).toHaveLength(2);
  });

  it("sends category and debounced search filters to the API", async () => {
    render(<ActivityCenter locale="en-US" t={t} />);
    await screen.findByText("Create folder");

    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "file" } });
    fireEvent.change(screen.getByLabelText("Search activity"), { target: { value: "docs" } });

    await waitFor(() => expect(activity).toHaveBeenCalledWith(expect.objectContaining({ category: "file", search: "docs", page: 1 })));
  });

  it("keeps the actor filter hidden for a regular user's private scope", async () => {
    activity.mockResolvedValue({ ...response, scope: "own", items: [response.items[1]], total: 1 });
    activitySummary.mockResolvedValue({ ...summary, scope: "own", total: 1 });
    render(<ActivityCenter locale="en-US" t={t} />);

    expect(await screen.findByText("Sign in")).toBeInTheDocument();
    expect(screen.queryByLabelText("User")).not.toBeInTheDocument();
    expect(screen.getByText("activity.subtitleOwn")).toBeInTheDocument();
  });
});
