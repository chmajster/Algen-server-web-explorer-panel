import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { DataTable, type DataTableColumn } from "./DataTable";

type Row = { id: string; name: string };
const columns: DataTableColumn<Row>[] = [{ key: "name", header: "Name", render: (row) => row.name }];

function SelectableTable() {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  return <DataTable rows={[{ id: "1", name: "Alpha" }]} columns={columns} getRowId={(row) => row.id} selected={selected} onSelectionChange={setSelected} actions={(row) => <button>Open {row.name}</button>} />;
}

describe("DataTable", () => {
  it("renders rows and actions", () => {
    render(<SelectableTable />);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Alpha" })).toBeInTheDocument();
  });

  it("renders empty state", () => {
    render(<DataTable rows={[]} columns={columns} getRowId={(row) => row.id} emptyTitle="Nothing here" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });

  it("renders loading state", () => {
    render(<DataTable rows={[]} columns={columns} getRowId={(row) => row.id} loading loadingLabel="Fetching rows" />);
    expect(screen.getByRole("status")).toHaveTextContent("Fetching rows");
  });

  it("updates selection", () => {
    render(<SelectableTable />);
    const checkbox = screen.getByRole("checkbox", { name: "Select row 1" });
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
  });
});
