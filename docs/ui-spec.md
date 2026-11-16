# UI spec (Phase 3F)

The app should feel like a calm bank statement, not a startup landing page.
Nothing on screen should look generated: no decoration that does not carry
information.

## Layout and type

- Mobile first, 360 to 430 px wide. On a desktop, one centred column of at
  most 480 px.
- System font stack (`system-ui`, `-apple-system`, `Segoe UI`, `Roboto`).
  Every number uses tabular figures.
- 8 px radius, 1 px hairline borders, no heavy shadows. Lists are bordered
  cards of rows; rows are at least 56 px tall, every control at least 44 px.
- Bottom navigation, four tabs: Home, Transactions, To-do (with a count),
  Labels. Detail screens have a back control in the header.

## Colour

Neutral greys plus one muted teal accent, used only for the active tab,
primary buttons, links and the focus ring. Money in shows a "+" in a muted
green. Red appears only for errors. The theme follows the system; dark is
near-black, not pure black. All text colours meet WCAG AA (at least 4.5:1)
on both the page and card backgrounds.

| Token | Light | Dark | Use |
| ----- | ----- | ---- | --- |
| bg | `#f6f6f4` | `#111214` | page |
| surface | `#ffffff` | `#18191b` | cards, sheets, navigation |
| ink | `#1b1c1e` | `#e7e7e4` | text (17.1:1, 14.2:1 on surface) |
| muted | `#5c6066` | `#a3a6ab` | secondary text (6.3:1, 7.2:1) |
| line | `#e2e2de` | `#2a2c2f` | hairlines |
| **accent** | **`#0e6862`** | **`#6bb7af`** | active tab, primary button, links (6.6:1, 7.6:1) |
| on-accent | `#ffffff` | `#111214` | text on the accent (6.6:1, 8.1:1) |
| positive | `#2b6a48` | `#86c3a0` | "+" money in (6.5:1, 8.7:1) |
| danger | `#b42318` | `#f2826f` | errors only (6.6:1, 6.9:1) |
| bar | `#8d9298` | `#7b8086` | category bars (neutral, never the accent) |

## Never

Gradients, glow, glass effects, emoji, illustrations, icons in coloured
circles, donut charts, a "Set budget" link on every row, ads, promo cards.

## Words and numbers

- Plain and short: "Spent", "Paid back", "To confirm", "Net". No exclamation
  marks; no "journey" or "insights".
- Rupees with Indian grouping: `₹1,23,456`. Overviews round to whole rupees
  (half away from zero); transaction detail shows paise (`₹1,23,456.78`). A
  minus is the real minus sign (`−₹1,500`).
- Dates and times in IST (fixed +05:30): "Tue 17 Nov", "14:05"; detail shows
  "Tue 17 Nov 2026, 14:05". Months: "Nov 2026".

## Screens

1. **Login**: email and password, no sign-up link. In demo mode any input
   continues.
2. **Home**: month switcher (‹ Nov 2026 ›); Net as the headline with
   "Spent ₹X · Paid back ₹Y" under it; a "To confirm: ₹Z from N people" row
   when Z > 0, opening To-do; Spent by category as a list sorted by amount
   (name, amount, percent, a thin neutral bar), each opening its detail; a
   muted footnote "N messages not counted yet".
3. **Category detail**: recipients or merchants with their totals, biggest
   first ("Sent to" for People); tap one for its transactions.
4. **Transactions**: grouped by IST day; each row shows the name, the
   category in small text and the amount right-aligned; filters for category
   and label; "Show more" pages on. A row opens a bottom sheet: amount with
   paise, time, how it is counted, category (automatic or set by you), label;
   "Change category" (then "Just this one" or "All from <name>") and "Label"
   (pick, remove, or make a new one).
5. **To-do**: senders to confirm, biggest first, each with Friend,
   Family / income (asks for a name, "Family" by default) and Ignore; then
   uncategorised merchants, biggest first, each with a category picker.
6. **Labels**: each label with Net, Spent and Paid back; tap for its category
   breakdown and transactions; make a new label.

## States

- **Server waking**: after 1.5 s without an answer, "Starting up, this can
  take about a minute" with one thin progress bar that slows as it goes. No
  spinner wall.
- **Empty month**: one line, "Nothing recorded in Nov 2026."
- **Error**: "Could not load", the reason, and "Try again".
- **Stale**: a quiet notice "Totals are being updated." above the numbers.
- While a screen reloads after a change, the old numbers stay until the new
  ones arrive.

## Demo mode (3F-1)

Every screen carries a "Demo data. Not your real numbers." banner. Its State
switch (normal, waking, empty, error, stale) is there only while the demo
adapter is in use, so every state can be checked. The data is a student's
October and November 2026 with fake names: daily chai and canteen meals, a
few large transfers to people, UPI senders to confirm, and a Goa trip label.
