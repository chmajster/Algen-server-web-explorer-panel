import { describe, expect, it } from "vitest";
import { moveInHistory, pushPath } from "./navigation";

describe("directory history", () => {
  it("supports back, forward and truncates forward history on a new branch", () => {
    let state = { entries: ["/home"], index: 0 };
    state = pushPath(state, "/home/docs");
    state = pushPath(state, "/home/docs/reports");
    state = moveInHistory(state, -1);
    expect(state.entries[state.index]).toBe("/home/docs");
    state = moveInHistory(state, 1);
    expect(state.entries[state.index]).toBe("/home/docs/reports");
    state = moveInHistory(state, -2);
    state = pushPath(state, "/home/photos");
    expect(state).toEqual({ entries: ["/home", "/home/photos"], index: 1 });
  });
});
