# UI spec (Phase 3F)

The app should feel like a calm bank statement, not a startup landing page.
Nothing on screen should look generated: no decoration that does not carry
information.

## Layout and type

- Mobile first, 360 to 430 px wide. On a desktop, one centred column of at
  most 480 px.
- System font stack (`system-ui`, `-apple-system`, `Segoe UI`, `Roboto`).
  Every number uses tabular figures. Sizes are in rem, so the system text
  size scales everything; at 200 % rows grow and buttons wrap, and nothing is
  cut off except long names.
- 8 px radius, 1 px hairline borders, no heavy shadows. Lists are bordered
  cards of rows; rows are at least 56 px tall, every control at least 44 px.
- Long names truncate with an ellipsis. Amounts never wrap.
- Bottom navigation, four tabs: Home, Transactions, To-do (with a count),
  Labels, each an icon above its label. Detail screens have a back control
  in the header.

## Icons

Lucide 1.74.0 (ISC; `frontend/src/icons/LICENSE`, which also carries the MIT
notice for the icons derived from Feather). Only the 27 SVGs in use are copied
into `frontend/src/icons/`; there is no icon package at runtime. Rounded line
icons, 20 px (1.25 rem), 2/24 stroke (about 1.7 px), in the muted text colour;
the accent only on the active tab. No coloured circles behind icons. Icons are
decorative (`aria-hidden`); the text beside them names them.

| Use | Icons |
| --- | ----- |
| Tabs | house, receipt-text, list-checks, tag |
| Controls | chevron-left, chevron-right, search |
| Categories | food_drinks utensils, groceries shopping-basket, travel bus, shopping shopping-bag, bills_recharges smartphone, subscriptions repeat, health heart-pulse, personal_care scissors, entertainment clapperboard, education graduation-cap, rent_hostel bed-double, emi_loans landmark, investments trending-up, gifts_donations gift, people users, cash banknote, card_bill credit-card, fees_charges percent, other ellipsis, uncategorised circle-help |

## Navigation and the URL

Everything the owner sees is in the URL hash, so a reload restores it and a
link opens it from cold (`frontend/src/view.ts`, tested both ways):

`#/<tab>/<detail>?m=<month>&cat=<slug>&label=<id>&q=<search>&txn=<id>`

| Part | Meaning |
| ---- | ------- |
| tab | `home`, `transactions`, `todo`, `labels` (`dev` for dev pages) |
| detail | `home/category/<slug>`, `home/category/<slug>/<name>`, `labels/<id>` |
| `m` | the month, `2026-11`; none means the current IST month |
| `cat`, `label`, `q` | Transactions: category filter, label filter, name search |
| `txn` | the transaction whose sheet is open |

- Opening a layer (a detail or a sheet) adds a history entry. Back closes the
  topmost layer: the sheet, then the detail, then the tab's root. The same
  holds for the app's back control, the sheet's Done and Escape, the browser
  button and Android back.
- A link opened from cold gets the layers under it in history, so Back steps
  out the same way.
- Month, filters and search replace the current entry: they are not layers.
- Switching tabs keeps the month and starts the tab at its root.
- Returning to a list puts it back where it was scrolled. A sheet opens and
  closes over the list without moving it. A new screen starts at the top.
- Loaded data is kept for the session. Moving around the app shows it at once
  and never shows "Starting up". A write reloads; the old numbers stay until
  the new ones arrive.

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
2. **Home**, in this order: month switcher (‹ Nov 2026 ›); Net as the
   headline; "Spent ₹X · Paid back ₹Y"; one plain line comparing Spent with
   last month ("Spent ₹7,580 more than this time last month": the current
   month compares with last month up to the same IST day, a past month with
   the whole month before it); a "To confirm: ₹Z from N people" row when
   Z > 0, opening To-do; Spent by category, sorted by amount: icon, name,
   amount, percent of Spent, a thin neutral bar filled to that share (37 %
   fills 37 %), and a small change versus last month ("₹889 more", "same",
   "new"); "Recent", the last five transactions; a muted footnote "N messages
   not counted yet".
3. **Category detail**: merchants with their totals, biggest first ("Paid
   to"); tap one for its transactions.
4. **People ledger** (People's category detail): one row per person with
   Net, and Sent and Got back under it, biggest Sent first. Sent is People
   spending to them; Got back is their paybacks, confirmed or not. A person's
   view shows Sent, Got back and Net, then both directions by day; money in is
   marked "+" in the muted green and "Money in, not part of Spent".
5. **Transactions**: month switcher, a name search (every word must appear,
   any case), category and label filters. The whole month is loaded, so
   search and filters cover all of it. Grouped by IST day; day headers stay at
   the top while their rows scroll. Each row: name, category in small text,
   amount right-aligned. A row opens a bottom sheet: amount with paise, time,
   how it is counted, category (automatic or set by you), label; "Change
   category" (then "Just this one" or "All from <name>") and "Label" (pick,
   remove, or make a new one).
6. **To-do**: compact rows. "Who sent you money?": senders to confirm,
   biggest first, each with Friend, Family and Ignore on one line (they wrap
   only at large text sizes). Family means income; its label defaults to
   "Family" and can be edited (trimmed, 1 to 30 characters; several senders
   may share one). "Pick a category": uncategorised merchants with a category
   picker. An answered row collapses away in 200 ms (at once with reduced
   motion). "Confirmed": senders already answered, with the answer and
   "Change".
7. **Labels**: each label with Spent, Paid back and Net, and its number of
   payments; tap for its category breakdown (bars are shares of the label's
   Spent) and transactions; make a new label.

Sheets were checked at 360 px and at 200 % text: the panel scrolls, values
wrap under their terms and buttons grow.

## Label names

Trimmed (inner runs of spaces become one), 1 to 30 characters, and refused
when another label has the same name in any case. The reason shows under the
field as the owner types ("A label with this name already exists.", "Use at
most 30 characters."); Create stays disabled until the name is fine.

## States

- **Server waking**: only when the session's first request takes over 3 s:
  "Starting up, this can take about a minute" with one thin progress bar that
  slows as it goes. No spinner wall. After any answer, a slow load shows only
  "Loading".
- **Empty month**: one line, "Nothing recorded in Nov 2026."
- **Error**: "Could not load", the reason, and "Try again".
- **Stale**: a quiet notice "Totals are being updated." above the numbers.
- While a screen reloads after a change, the old numbers stay until the new
  ones arrive.

## Demo mode

Every screen carries a "Demo data. Not your real numbers." banner at the top,
in the page flow: it scrolls away with the page and never covers content, at
any width or text size. Its State switch (normal, waking, empty, error, stale)
is there only while the demo adapter is in use; picking a state starts a new
session, so "waking" shows "Starting up" again. The data is a student's
October and November 2026 with fake names: daily chai and canteen meals, a few
large transfers to people, UPI senders to confirm, and a Goa trip label.

## Logo options (dev page)

`#/dev/logos` (in development, or while the demo adapter is in use) shows
three original monochrome marks, drawn from plain shapes, at 16, 24, 32, 48
and 96 px and beside the name, in light and dark. Nothing else uses them yet;
the PWA icons stay as they are until the owner picks one.

1. **Tally**: three left-aligned bars, longest first, like Spent by category.
2. **Split**: a solid rounded tile parted by a stepped line into two parts.
3. **Step**: a level line that drops once and carries on.

None is a letter or a lightning bolt, to stay clear of existing "Flash" marks.
They were not checked against a trademark register.

## API gaps the demo papers over (for 3F-3)

| Gap | What the client does now | Where it belongs |
| --- | ------------------------ | ---------------- |
| `role_basis` on transaction items | A payback row says "Money in, not part of Spent"; it cannot say "to confirm" or "paid back". Got back in the people ledger mixes both. | Backend: add `role_basis` (or a `confirmed` flag) to `/transactions` items. |
| Totals on `/labels` | The Labels list calls `/labels/{id}` once per label. | Backend: Spent, Paid back and Net on `/labels` items. Fine in the client for a handful of labels. |
| Last-month figures | Home loads last month's whole transaction list to compute Spent and Spent by category, to the same IST day for the current month. | Backend: a `previous` block in `/summary`, so the comparison follows the same Spent rules (refund links, recompute). Works in the client meanwhile. |
| The person ledger | Groups People spending and payback credits by display name. One person seen under two names (a UPI ID and a name) shows twice. | Backend: a party id on transaction items, or `/people?month=`. |
| "Unanswer" and ignored senders | `/senders` never lists ignored senders, so Ignore cannot be changed in the app, and no answer can be taken back to "to confirm". | Backend: `status=ignored` on `/senders`, and `DELETE /senders/{id}` to remove the owner answer. |
| The income label of a sender | Confirmed shows "Family: income", not the name given. | Backend: return the label on sender items. |
| A transaction by id | `?txn=` opens a sheet only when that transaction is in the list on screen. | Backend: `GET /transactions/{id}`. Small. |
| Name search | Transactions loads the whole month (pages of 200) and filters. | Fine in the client at a few hundred rows a month; add `q` only if months grow far larger. |
| Merchant groups | Category detail and To-do group transactions by display name; To-do loads every uncategorised row, all months. | Fine in the client for now; `/merchants?category=` if it grows. |
| Merchant answers | There is no list of "All from" answers; one is changed by opening any of its transactions. | Backend, later: list owner merchant categories. |
| Label name rules | The app refuses names over 30 characters and duplicates in any case. The API accepts 1 to 80 and answers a duplicate with the existing label (200). | Backend: align to 30 and answer a duplicate with 409. |
| The waking probe | The session's first request is the probe. | Fine in the client. |
