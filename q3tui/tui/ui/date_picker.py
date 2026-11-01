"""Calendar and DatePicker, following shadcn's Calendar and Date Picker."""

from __future__ import annotations

import calendar as _calendar
from collections.abc import Callable
from datetime import date, timedelta

from textual import events
from textual.binding import Binding
from textual.content import Content
from textual.message import Message
from textual.widgets import Static

from q3tui.tui.ui.icons import icon
from q3tui.tui.ui.popover import Popover, PopoverTrigger

__all__ = ["Calendar", "DatePicker"]

_CELL = 3  # Two digits and a space.


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    last = _calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, min(day.day, last))


class Calendar(Static, can_focus=True):
    """A month grid with a cursor. The arrow keys move the cursor by a day or a week, Home and End
    go to the start and end of its week, **PageUp and PageDown change the month** (with Shift, the
    year), `t` returns to today, and **Enter or Space picks the day**. A click picks a day, and the
    arrows in the header change the month. Days outside `minimum`..`maximum` are dimmed and cannot
    be reached. Posts `Calendar.Selected(calendar, date)`.
    """

    DEFAULT_CSS = """
    Calendar { width: auto; height: auto; padding: 0 1; color: $foreground; }
    Calendar:focus { background: $surface; }
    """
    BINDINGS = [
        Binding("left", "move(-1)", show=False),
        Binding("right", "move(1)", show=False),
        Binding("up", "move(-7)", show=False),
        Binding("down", "move(7)", show=False),
        Binding("home", "week_edge(-1)", show=False),
        Binding("end", "week_edge(1)", show=False),
        Binding("pageup", "month(-1)", show=False),
        Binding("pagedown", "month(1)", show=False),
        Binding("shift+pageup", "month(-12)", show=False),
        Binding("shift+pagedown", "month(12)", show=False),
        Binding("t", "today", show=False),
        Binding("enter,space", "pick", show=False),
    ]

    class Selected(Message):
        def __init__(self, calendar: Calendar, value: date) -> None:
            super().__init__()
            self.calendar = calendar
            self.value = value

        @property
        def control(self) -> Calendar:
            return self.calendar

    def __init__(
        self,
        value: date | None = None,
        *,
        week_start: int = 0,
        minimum: date | None = None,
        maximum: date | None = None,
        on_select: Callable[[date], object] | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes, markup=False)
        self.value = value
        self.cursor = value or date.today()
        self.week_start = week_start % 7
        self.minimum = minimum
        self.maximum = maximum
        self.on_select = on_select
        self._grid_top = 2  # Rows above the first week: the title and the weekday names.
        self._clamp_cursor()

    def on_mount(self) -> None:
        self._draw()

    def _allowed(self, day: date) -> bool:
        return (self.minimum is None or day >= self.minimum) and (
            self.maximum is None or day <= self.maximum
        )

    def _clamp_cursor(self) -> None:
        if self.minimum and self.cursor < self.minimum:
            self.cursor = self.minimum
        if self.maximum and self.cursor > self.maximum:
            self.cursor = self.maximum

    def _weeks(self) -> list[list[date]]:
        first = self.cursor.replace(day=1)
        last = _add_months(first, 1) - timedelta(days=1)
        day = first - timedelta(days=(first.weekday() - self.week_start) % 7)
        weeks = []
        while day <= last:
            weeks.append([day + timedelta(days=n) for n in range(7)])
            day += timedelta(days=7)
        return weeks

    def _draw(self) -> None:
        names = _calendar.day_abbr
        today = date.today()
        title = self.cursor.strftime("%B %Y")
        width = 7 * _CELL - 1
        lines: list[list[str | tuple[str, str]]] = [
            [icon("chevron_left"), (title.center(width - 2), "bold"), icon("chevron_right")],
            [(" ".join(names[(self.week_start + n) % 7][:2] for n in range(7)), "dim")],
        ]
        for week in self._weeks():
            row: list[str | tuple[str, str]] = []
            for n, day in enumerate(week):
                text = f"{day.day:2d}"
                styles = []
                if day.month != self.cursor.month or not self._allowed(day):
                    styles.append("dim")
                if day == today:
                    styles.append("bold")
                if day == self.value:
                    styles.append("reverse")
                if day == self.cursor and self.has_focus:
                    styles.append("underline")
                row.append((text, " ".join(styles)) if styles else text)
                if n < 6:
                    row.append(" ")
            lines.append(row)
        parts: list[str | tuple[str, str]] = []
        for number, line in enumerate(lines):
            if number:
                parts.append("\n")
            parts.extend(line)
        self.update(Content.assemble(*parts))

    def on_focus(self) -> None:
        self._draw()

    def on_blur(self) -> None:
        self._draw()

    def go(self, day: date) -> None:
        if self._allowed(day):
            self.cursor = day
            self._draw()

    def action_move(self, days: int) -> None:
        self.go(self.cursor + timedelta(days=days))

    def action_week_edge(self, direction: int) -> None:
        offset = (self.cursor.weekday() - self.week_start) % 7
        self.go(self.cursor + timedelta(days=(6 - offset) if direction > 0 else -offset))

    def action_month(self, months: int) -> None:
        target = _add_months(self.cursor, months)
        while not self._allowed(target) and target != self.cursor:
            target += timedelta(days=-1 if months > 0 else 1)
        self.go(target)

    def action_today(self) -> None:
        self.go(date.today())

    def action_pick(self) -> None:
        self.pick(self.cursor)

    def pick(self, day: date) -> None:
        if not self._allowed(day):
            return
        self.value = day
        self.cursor = day
        self._draw()
        self.post_message(self.Selected(self, day))
        if self.on_select is not None:
            self.on_select(day)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.focus()
        x, y = event.x - 1, event.y
        if y == 0:
            if x <= 1:
                self.action_month(-1)
            elif x >= 7 * _CELL - 2:
                self.action_month(1)
            return
        week = y - self._grid_top
        weeks = self._weeks()
        if 0 <= week < len(weeks) and 0 <= x < 7 * _CELL - 1:
            self.pick(weeks[week][x // _CELL])


class DatePicker(Popover):
    """`DatePicker(value=None, placeholder="Pick a date", key="ctrl+d")`: a button showing the date
    (or the placeholder) that opens a `Calendar` in a popover. Picking a day closes the popover,
    shows the date, and posts `DatePicker.Changed(picker, date)`. `picker.value` reads it."""

    class Changed(Message):
        def __init__(self, picker: DatePicker, value: date) -> None:
            super().__init__()
            self.picker = picker
            self.value = value

        @property
        def control(self) -> DatePicker:
            return self.picker

    def __init__(
        self,
        value: date | None = None,
        *,
        placeholder: str = "Pick a date",
        key: str | None = None,
        minimum: date | None = None,
        maximum: date | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self.value = value
        self.placeholder = placeholder
        self.minimum = minimum
        self.maximum = maximum
        super().__init__(
            PopoverTrigger(self._label(), key=key, icon_name="calendar"),
            factory=self._calendar,
            id=id,
            classes=classes,
        )

    def _label(self) -> str:
        return self.value.isoformat() if self.value else self.placeholder

    def _calendar(self) -> list[Calendar]:
        return [
            Calendar(
                self.value,
                minimum=self.minimum,
                maximum=self.maximum,
                on_select=self._chosen,
            )
        ]

    def _chosen(self, day: date) -> None:
        self.set_value(day)
        self.app.call_later(self.close, restore_focus=True)

    def set_value(self, value: date, *, notify: bool = True) -> None:
        changed = value != self.value
        self.value = value
        self.trigger.set_label(self._label())
        if changed and notify:
            self.post_message(self.Changed(self, value))
