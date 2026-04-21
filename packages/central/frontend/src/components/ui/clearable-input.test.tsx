import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { ClearableInput } from "./clearable-input.tsx";

/**
 * Regression anchor: the clear button must stay in the DOM at all times,
 * hidden via CSS (`opacity-0 pointer-events-none`). Removing it when the
 * input is empty causes focus loss mid-typing — the exact bug this primitive
 * was designed to avoid.
 */
describe("ClearableInput", () => {
  it("renders the clear button even when the value is empty (hidden, not removed)", () => {
    render(<ClearableInput value="" onClear={() => {}} onChange={() => {}} />);
    const btn = screen.getByRole("button");
    expect(btn).toBeInTheDocument();
    expect(btn.className).toContain("opacity-0");
    expect(btn.className).toContain("pointer-events-none");
  });

  it("shows the clear button (opacity-100) when the value is non-empty", () => {
    render(
      <ClearableInput value="abc" onClear={() => {}} onChange={() => {}} />,
    );
    const btn = screen.getByRole("button");
    expect(btn.className).toContain("opacity-100");
    expect(btn.className).not.toContain("pointer-events-none");
  });

  it("invokes onClear when the visible X button is clicked", async () => {
    const user = userEvent.setup();
    const onClear = vi.fn();
    render(
      <ClearableInput value="abc" onClear={onClear} onChange={() => {}} />,
    );
    await user.click(screen.getByRole("button"));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("keeps focus on the input when the value transitions empty → non-empty", async () => {
    // This is the core anti-regression check for the focus-loss bug the
    // primitive exists to fix. We type into a controlled input; focus must
    // survive the CSS-driven button reveal.
    function Harness() {
      const [val, setVal] = useState("");
      return (
        <ClearableInput
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onClear={() => setVal("")}
        />
      );
    }
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole("textbox");
    input.focus();
    expect(input).toHaveFocus();
    await user.type(input, "hello");
    expect(input).toHaveFocus();
    expect((input as HTMLInputElement).value).toBe("hello");
  });
});
