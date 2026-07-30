import { describe, expect, it } from "vitest";
import type { WindowInstance } from "../../app/types";
import { backgroundOnly, deepLinkForAction } from "./windowTargets";
import type { BackgroundAction } from "./types";

const first: BackgroundAction = {
  key: "transfer:first",
  id: "first",
  source: "transfer",
  title: "First",
  status: "running",
  createdAt: 1,
  target: { app: "transfers", entityId: "first", detailType: "transfer" },
};

const second: BackgroundAction = {
  ...first,
  key: "transfer:second",
  id: "second",
  title: "Second",
  target: { ...first.target, entityId: "second" },
};

function transferWindow(overrides: Partial<WindowInstance> = {}): WindowInstance {
  return {
    id: "transfers-1",
    app: "transfers",
    rect: { x: 0, y: 0, width: 800, height: 600 },
    minimized: false,
    zIndex: 11,
    ...overrides,
  };
}

describe("action window visibility", () => {
  it("hides only the exact action whose detail is visible in the active window", () => {
    const window = transferWindow({ deepLink: deepLinkForAction(first) });

    expect(backgroundOnly([first, second], [window], window.id).map((action) => action.key)).toEqual(["transfer:second"]);
  });

  it("keeps an action in the center when its window is minimized or shows another view", () => {
    const linked = transferWindow({ minimized: true, deepLink: deepLinkForAction(first) });
    const unrelated = transferWindow();

    expect(backgroundOnly([first], [linked], "")).toEqual([first]);
    expect(backgroundOnly([first], [unrelated], unrelated.id)).toEqual([first]);
  });
});
