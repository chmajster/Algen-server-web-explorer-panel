import { beforeEach, describe, expect, it } from "vitest";

import { loadStoredTransaction } from "./NetworkManagementPanels";

const key = "webnas_network_transaction";

describe("network transaction persistence", () => {
  beforeEach(() => sessionStorage.clear());

  it("rejects malformed and wrong-shaped persisted transactions", () => {
    sessionStorage.setItem(key, "{");
    expect(loadStoredTransaction()).toBeNull();
    sessionStorage.setItem(key, JSON.stringify([]));
    expect(loadStoredTransaction()).toBeNull();
    sessionStorage.setItem(key, JSON.stringify({ id: "tx-1", deadline: "soon" }));
    expect(loadStoredTransaction()).toBeNull();
    sessionStorage.setItem(key, JSON.stringify({ id: "tx-1", deadline: 123, deadline_at: "soon" }));
    expect(loadStoredTransaction()).toBeNull();
  });

  it("restores a transaction only when its countdown fields are finite", () => {
    const transaction = { id: "tx-1", provider: "network", state: "pending_confirmation", started_at: 1, deadline: 123, deadline_at: 120, rollback_unit: null, target: "eth0" };
    sessionStorage.setItem(key, JSON.stringify(transaction));
    expect(loadStoredTransaction()).toMatchObject({ id: "tx-1", deadline: 123, deadline_at: 120 });
  });
});
