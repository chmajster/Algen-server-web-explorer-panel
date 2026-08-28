import { render, screen } from "@testing-library/react";
import { FormField, TextInput } from "./forms";

describe("FormField", () => {
  it("associates label and error with a field", () => {
    render(<FormField label="Name" htmlFor="name" error="Required"><input id="name" /></FormField>);
    expect(screen.getByLabelText("Name")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Required");
  });

  it("forwards disabled state from TextInput", () => {
    render(<TextInput label="Host" disabled />);
    expect(screen.getByLabelText("Host")).toBeDisabled();
  });
});
