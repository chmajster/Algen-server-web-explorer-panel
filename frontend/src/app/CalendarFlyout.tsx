import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type RefObject,
} from "react";
import type { Translate } from "./types";

function localDate(year: number, month: number, day: number) {
  return new Date(year, month, day, 12);
}

function startOfDay(value: Date) {
  return localDate(value.getFullYear(), value.getMonth(), value.getDate());
}

function startOfMonth(value: Date) {
  return localDate(value.getFullYear(), value.getMonth(), 1);
}

function sameDay(left: Date, right: Date) {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  );
}

function sameMonth(left: Date, right: Date) {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth()
  );
}

function addDays(value: Date, amount: number) {
  return localDate(value.getFullYear(), value.getMonth(), value.getDate() + amount);
}

function addMonths(value: Date, amount: number) {
  const first = localDate(value.getFullYear(), value.getMonth() + amount, 1);
  const lastDay = localDate(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  return localDate(first.getFullYear(), first.getMonth(), Math.min(value.getDate(), lastDay));
}

function mondayOffset(value: Date) {
  return (value.getDay() + 6) % 7;
}

function dateKey(value: Date) {
  return [
    value.getFullYear(),
    String(value.getMonth() + 1).padStart(2, "0"),
    String(value.getDate()).padStart(2, "0"),
  ].join("-");
}

export function buildCalendarDays(month: Date) {
  const first = startOfMonth(month);
  const gridStart = addDays(first, -mondayOffset(first));
  return Array.from({ length: 42 }, (_, index) => addDays(gridStart, index));
}

export function CalendarFlyout({
  now,
  locale,
  t,
  triggerRef,
  onClose,
}: {
  now: Date;
  locale: string;
  t: Translate;
  triggerRef: RefObject<HTMLButtonElement>;
  onClose: () => void;
}) {
  const today = useMemo(() => startOfDay(now), [now]);
  const [selectedDate, setSelectedDate] = useState(today);
  const [focusedDate, setFocusedDate] = useState(today);
  const [visibleMonth, setVisibleMonth] = useState(() => startOfMonth(today));
  const panelRef = useRef<HTMLElement>(null);
  const dayRefs = useRef(new Map<string, HTMLButtonElement>());
  const days = useMemo(() => buildCalendarDays(visibleMonth), [visibleMonth]);
  const monthFormatter = useMemo(
    () => new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" }),
    [locale],
  );
  const selectedFormatter = useMemo(
    () => new Intl.DateTimeFormat(locale, { weekday: "long", day: "numeric", month: "long" }),
    [locale],
  );
  const dayLabelFormatter = useMemo(
    () => new Intl.DateTimeFormat(locale, { weekday: "long", day: "numeric", month: "long", year: "numeric" }),
    [locale],
  );
  const weekdayFormatter = useMemo(
    () => new Intl.DateTimeFormat(locale, { weekday: "short" }),
    [locale],
  );
  const weekdays = useMemo(
    () =>
      Array.from({ length: 7 }, (_, index) =>
        weekdayFormatter.format(addDays(localDate(2024, 0, 1), index)).replace(/\.$/, ""),
      ),
    [weekdayFormatter],
  );

  useLayoutEffect(() => {
    dayRefs.current.get(dateKey(focusedDate))?.focus({ preventScroll: true });
  }, [focusedDate, visibleMonth]);

  useEffect(() => {
    function outside(event: MouseEvent) {
      const target = event.target as Node;
      if (panelRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      onClose();
    }
    function escape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [onClose, triggerRef]);

  useEffect(
    () => () => {
      triggerRef.current?.focus({ preventScroll: true });
    },
    [triggerRef],
  );

  function focus(value: Date) {
    const normalized = startOfDay(value);
    setFocusedDate(normalized);
    if (!sameMonth(normalized, visibleMonth)) setVisibleMonth(startOfMonth(normalized));
  }

  function select(value: Date) {
    const normalized = startOfDay(value);
    setSelectedDate(normalized);
    setFocusedDate(normalized);
    setVisibleMonth(startOfMonth(normalized));
  }

  function moveMonth(amount: number) {
    const target = addMonths(focusedDate, amount);
    setVisibleMonth(startOfMonth(target));
    setFocusedDate(target);
  }

  function dayKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    let target: Date;
    if (event.key === "ArrowLeft") target = addDays(focusedDate, -1);
    else if (event.key === "ArrowRight") target = addDays(focusedDate, 1);
    else if (event.key === "ArrowUp") target = addDays(focusedDate, -7);
    else if (event.key === "ArrowDown") target = addDays(focusedDate, 7);
    else if (event.key === "PageUp") target = addMonths(focusedDate, -1);
    else if (event.key === "PageDown") target = addMonths(focusedDate, 1);
    else if (event.key === "Home") target = addDays(focusedDate, -mondayOffset(focusedDate));
    else if (event.key === "End") target = addDays(focusedDate, 6 - mondayOffset(focusedDate));
    else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      select(focusedDate);
      return;
    } else {
      return;
    }
    event.preventDefault();
    focus(target);
  }

  return (
    <section
      ref={panelRef}
      id="calendar-flyout"
      className="calendar-flyout"
      role="dialog"
      aria-modal="false"
      aria-label={t("calendar.title")}
    >
      <header className="calendar-selected-date">
        <span>{t("calendar.selectedDate")}</span>
        <strong>{selectedFormatter.format(selectedDate)}</strong>
      </header>
      <div className="calendar-month-navigation">
        <h2 aria-live="polite">{monthFormatter.format(visibleMonth)}</h2>
        <div>
          <button
            type="button"
            aria-label={t("calendar.previousMonth")}
            onClick={() => moveMonth(-1)}
          >
            <ChevronLeft />
          </button>
          <button
            type="button"
            aria-label={t("calendar.nextMonth")}
            onClick={() => moveMonth(1)}
          >
            <ChevronRight />
          </button>
        </div>
      </div>
      <div
        className="calendar-grid"
        role="grid"
        aria-label={monthFormatter.format(visibleMonth)}
        aria-colcount={7}
        aria-rowcount={6}
      >
        <div className="calendar-weekdays" role="row">
          {weekdays.map((weekday, index) => (
            <span role="columnheader" key={`${weekday}-${index}`}>
              {weekday}
            </span>
          ))}
        </div>
        <div className="calendar-days" role="rowgroup">
          {Array.from({ length: 6 }, (_, week) => (
            <div className="calendar-week" role="row" key={week}>
              {days.slice(week * 7, week * 7 + 7).map((day) => {
                const key = dateKey(day);
                const currentMonth = sameMonth(day, visibleMonth);
                const currentDay = sameDay(day, today);
                const selected = sameDay(day, selectedDate);
                const focused = sameDay(day, focusedDate);
                return (
                  <button
                    ref={(element) => {
                      if (element) dayRefs.current.set(key, element);
                      else dayRefs.current.delete(key);
                    }}
                    key={key}
                    type="button"
                    role="gridcell"
                    tabIndex={focused ? 0 : -1}
                    className={`${currentMonth ? "" : "outside-month"} ${currentDay ? "today" : ""} ${selected ? "selected" : ""}`.trim()}
                    aria-label={dayLabelFormatter.format(day)}
                    aria-current={currentDay ? "date" : undefined}
                    aria-selected={selected}
                    data-date={key}
                    onClick={() => select(day)}
                    onFocus={() => {
                      if (!focused) setFocusedDate(day);
                    }}
                    onKeyDown={dayKeyDown}
                  >
                    <span>{day.getDate()}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
      <footer>
        <button type="button" onClick={() => select(today)}>
          {t("calendar.today")}
        </button>
      </footer>
    </section>
  );
}
