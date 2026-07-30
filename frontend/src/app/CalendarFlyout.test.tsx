import { fireEvent, render, screen } from "@testing-library/react";
import { createRef, useRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CalendarFlyout, buildCalendarDays } from "./CalendarFlyout";
import type { Translate } from "./types";

const NOW = new Date(2026, 6, 30, 12);
const translations: Record<string, Record<string, string>> = {
  "en-US": {
    "calendar.open": "Open calendar",
    "calendar.title": "Calendar",
    "calendar.selectedDate": "Selected date",
    "calendar.previousMonth": "Previous month",
    "calendar.nextMonth": "Next month",
    "calendar.today": "Today",
  },
  "pl-PL": {
    "calendar.open": "Otwórz kalendarz",
    "calendar.title": "Kalendarz",
    "calendar.selectedDate": "Wybrana data",
    "calendar.previousMonth": "Poprzedni miesiąc",
    "calendar.nextMonth": "Następny miesiąc",
    "calendar.today": "Dzisiaj",
  },
};

function translator(locale: string): Translate {
  return (key) => translations[locale]?.[key] || key;
}

function day(date: string) {
  const element = document.querySelector<HTMLButtonElement>(`[data-date="${date}"]`);
  if (!element) throw new Error(`Calendar day ${date} was not rendered`);
  return element;
}

function renderCalendar(locale = "en-US") {
  const triggerRef = createRef<HTMLButtonElement>();
  const onClose = vi.fn();
  const view = render(
    <>
      <button ref={triggerRef} type="button">
        Trigger
      </button>
      <CalendarFlyout
        now={NOW}
        locale={locale}
        t={translator(locale)}
        triggerRef={triggerRef}
        onClose={onClose}
      />
    </>,
  );
  return { onClose, triggerRef, unmount: view.unmount };
}

function DismissibleCalendar({ locale = "en-US" }: { locale?: string }) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(true);
  return (
    <>
      <button ref={triggerRef} type="button">
        Trigger
      </button>
      {open && (
        <CalendarFlyout
          now={NOW}
          locale={locale}
          t={translator(locale)}
          triggerRef={triggerRef}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

describe("CalendarFlyout", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("builds six complete Monday-first weeks including adjacent months", () => {
    const days = buildCalendarDays(NOW);
    expect(days).toHaveLength(42);
    expect(days[0]).toEqual(new Date(2026, 5, 29, 12));
    expect(days[41]).toEqual(new Date(2026, 7, 9, 12));

    renderCalendar();
    expect(screen.getAllByRole("gridcell")).toHaveLength(42);
    expect(day("2026-06-29")).toHaveClass("outside-month");
    expect(day("2026-08-09")).toHaveClass("outside-month");
  });

  it("opens on today, marks it independently, and moves focus into the grid", () => {
    renderCalendar();
    const today = day("2026-07-30");
    expect(screen.getByRole("heading", { name: "July 2026" })).toBeInTheDocument();
    expect(today).toHaveAttribute("aria-current", "date");
    expect(today).toHaveAttribute("aria-selected", "true");
    expect(today).toHaveAttribute("tabindex", "0");
    expect(today).toHaveFocus();
  });

  it("navigates between months with the header controls", () => {
    renderCalendar();
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(screen.getByRole("heading", { name: "June 2026" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next month" }));
    fireEvent.click(screen.getByRole("button", { name: "Next month" }));
    expect(screen.getByRole("heading", { name: "August 2026" })).toBeInTheDocument();
  });

  it("selects a day and updates the full selected-date header", () => {
    renderCalendar();
    fireEvent.click(day("2026-07-15"));
    expect(day("2026-07-15")).toHaveAttribute("aria-selected", "true");
    expect(day("2026-07-30")).toHaveAttribute("aria-current", "date");
    expect(screen.getByText("Wednesday, July 15")).toBeInTheDocument();
  });

  it("selects an adjacent-month day and changes the visible month", () => {
    renderCalendar();
    fireEvent.click(day("2026-08-01"));
    expect(screen.getByRole("heading", { name: "August 2026" })).toBeInTheDocument();
    expect(day("2026-08-01")).toHaveAttribute("aria-selected", "true");
  });

  it("returns to the real current day with the Today action", () => {
    renderCalendar();
    fireEvent.click(screen.getByRole("button", { name: "Next month" }));
    fireEvent.click(day("2026-08-12"));
    fireEvent.click(screen.getByRole("button", { name: "Today" }));
    expect(screen.getByRole("heading", { name: "July 2026" })).toBeInTheDocument();
    expect(day("2026-07-30")).toHaveAttribute("aria-current", "date");
    expect(day("2026-07-30")).toHaveAttribute("aria-selected", "true");
  });

  it("uses the profile locale for headings, selected dates, and Monday-first weekdays", () => {
    const first = renderCalendar("pl-PL");
    expect(screen.getByRole("dialog", { name: "Kalendarz" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "lipiec 2026" })).toBeInTheDocument();
    expect(screen.getByText("czwartek, 30 lipca")).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "pon",
      "wt",
      "śr",
      "czw",
      "pt",
      "sob",
      "niedz",
    ]);
    first.unmount();

    renderCalendar("en-US");
    expect(screen.getByRole("dialog", { name: "Calendar" })).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Mon",
      "Tue",
      "Wed",
      "Thu",
      "Fri",
      "Sat",
      "Sun",
    ]);
  });

  it("moves focus by day and by week with arrow keys", () => {
    renderCalendar();
    fireEvent.keyDown(day("2026-07-30"), { key: "ArrowLeft" });
    expect(day("2026-07-29")).toHaveFocus();
    fireEvent.keyDown(day("2026-07-29"), { key: "ArrowUp" });
    expect(day("2026-07-22")).toHaveFocus();
    fireEvent.keyDown(day("2026-07-22"), { key: "ArrowDown" });
    expect(day("2026-07-29")).toHaveFocus();
    fireEvent.keyDown(day("2026-07-29"), { key: "ArrowRight" });
    expect(day("2026-07-30")).toHaveFocus();
  });

  it("supports PageUp, PageDown, Home, End, Enter, and Space", () => {
    renderCalendar();
    fireEvent.keyDown(day("2026-07-30"), { key: "PageUp" });
    expect(day("2026-06-30")).toHaveFocus();
    fireEvent.keyDown(day("2026-06-30"), { key: "PageDown" });
    expect(day("2026-07-30")).toHaveFocus();
    fireEvent.keyDown(day("2026-07-30"), { key: "Home" });
    expect(day("2026-07-27")).toHaveFocus();
    fireEvent.keyDown(day("2026-07-27"), { key: "Enter" });
    expect(day("2026-07-27")).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(day("2026-07-27"), { key: "End" });
    expect(day("2026-08-02")).toHaveFocus();
    fireEvent.keyDown(day("2026-08-02"), { key: " " });
    expect(day("2026-08-02")).toHaveAttribute("aria-selected", "true");
  });

  it("closes on Escape and returns focus to the clock trigger", () => {
    render(<DismissibleCalendar />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Calendar" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Trigger" })).toHaveFocus();
  });

  it("closes on an outside pointer action and returns focus to the trigger", () => {
    render(<DismissibleCalendar />);
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("dialog", { name: "Calendar" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Trigger" })).toHaveFocus();
  });
});
