# UI spec (Phase 3F)

3F-3 superseded two 3F-2 rules: icons now sit on tiles tinted with their
category colour, and Home has a ring chart next to the list.

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
notice for the icons derived from Feather). Only the 28 SVGs in use are copied
into `frontend/src/icons/`; there is no icon package at runtime. Rounded line
icons, 20 px (1.25 rem), 2/24 stroke (about 1.7 px). Tab and control icons are
in the muted text colour, the accent only on the active tab. A category icon
sits on its **category tile**: a 36 px rounded square (8 px radius) tinted with
the category colour, the icon in that colour (see Category colours). Icons are
decorative (`aria-hidden`); the text beside them names them.

| Use | Icons |
| --- | ----- |
| Tabs | house, receipt-text, list-checks, tag |
| Controls | chevron-left, chevron-right, search, log-out (Sign out) |
| Categories | food_drinks utensils, groceries shopping-basket, travel bus, shopping shopping-bag, bills_recharges smartphone, subscriptions repeat, health heart-pulse, personal_care scissors, entertainment clapperboard, education graduation-cap, rent_hostel bed-double, emi_loans landmark, investments trending-up, gifts_donations gift, people users, cash banknote, card_bill credit-card, fees_charges percent, other ellipsis, uncategorised circle-help |

## Navigation and the URL

Everything the owner sees is in the URL hash, so a reload restores it and a
link opens it from cold (`frontend/src/view.ts`, tested both ways):

`#/<tab>/<detail>?m=<month>&cat=<slug>&label=<id>&q=<search>&txn=<id>`

| Part | Meaning |
| ---- | ------- |
| tab | `home`, `transactions`, `todo`, `labels` (`dev` for dev pages) |
| detail | `home/category/<slug>`, `home/category/<slug>/<name>` (for People, a person id), `labels/<id>` |
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
| faint | `#b5b8bc` | `#4a4d52` | disabled controls; the ring's "Other" slice |

## Category colours

One muted colour per category, chosen as a set in OKLCH: low chroma (0.035
to 0.11), hues spread around the circle, neighbours in hue told apart by
lightness. Uncategorised is a neutral grey. The same colour is used for the
category's icon, its tile, its bar and its ring slice. Text never takes a
category colour.

- Tile: the colour mixed into the surface, 13 % in light and 20 % in dark
  (`color-mix` in `index.css`), with the icon in the full colour.
- Every colour has at least 3:1 against the surface (lowest 3.62:1 light,
  4.83:1 dark) and against its own tile (lowest 3.16:1 light, 3.67:1 dark).
- Twenty colours cannot all be far apart at low chroma: the closest pairs
  (card bill and uncategorised; rent and cash) differ by about 4 to 5 OKLab
  units. Identity never rests on colour alone: every tile has its icon and
  every bar, slice and legend row its name.

| Category | Light | Dark |
| -------- | ----- | ---- |
| food_drinks | `#a66535` | `#dd9e73` |
| groceries | `#508659` | `#8ec094` |
| travel | `#4476a0` | `#85b4dc` |
| shopping | `#995a7e` | `#d295b7` |
| bills_recharges | `#8f7835` | `#cbb67b` |
| subscriptions | `#7d659a` | `#b9a2d5` |
| health | `#a24f4e` | `#dc8b89` |
| personal_care | `#a27a9d` | `#d6b0d1` |
| entertainment | `#49578d` | `#8796cb` |
| education | `#206173` | `#659cad` |
| rent_hostel | `#785e40` | `#b39a7d` |
| emi_loans | `#3d4e69` | `#7787a2` |
| investments | `#2c6e5a` | `#70a995` |
| gifts_donations | `#7a4058` | `#b57c91` |
| people | `#388b94` | `#65acb4` |
| cash | `#60612c` | `#979968` |
| card_bill | `#7d7d9b` | `#aeaeca` |
| fees_charges | `#804034` | `#bf8073` |
| other | `#594f3a` | `#8f8571` |
| uncategorised | `#7a7a7a` | `#b4b4b4` |

## Ring chart

Home shows Spent by category as a List (the default) or a Chart; a
segmented "List | Chart" control above the categories switches, and the
choice is remembered on the device (`localStorage`, wrapped so a private
window still works). The chart is a hand-drawn SVG ring, no chart package:
a thin stroke (7 of 120 units, about 13 px), Spent in the centre, the six
biggest categories as slices plus one "Other" slice (in the faint grey) for
the rest, 0.8 % of the ring as a gap between slices. A category that refunds
lowered to zero or below has no slice. The legend below lists the same
slices with tile, name, amount and percent. A slice (with a finger-sized
invisible target) or a legend row opens the category; "Other" switches to
the list. Each slice is a labelled button ("Food & Drinks, ₹1,240, 37%"),
and List stays the default view, so a screen reader meets the list first.

## Logo

An original mark, drawn as paths with no font: the **$ mark** is three
horizontal bars joined by two half circles, with a stub above and below,
monoline with round ends (`frontend/src/brand.tsx`). It is not slanted and
not on a green tile, to stay clear of well-known dollar-sign app icons, and
it is not a lightning bolt. The **wordmark** "FLA$H" uses the same geometry
for the S, slanted 10 degrees for speed: letters in the text colour, the $ in
the accent. The wordmark sits at the top of Home and on the login screen.

The app icon is the $ mark in `#7cc4bb` on a `#16191b` tile (8.7:1), which
reads on light and dark launchers and browser tabs: `favicon.svg`,
`pwa-192x192.png` and `pwa-512x512.png` (rounded tile),
`maskable-512x512.png` (full bleed, mark inside the safe circle) and
`apple-touch-icon.png` (180 px, full bleed). The PNGs were rendered from
the same path with headless Edge. `#/dev/logos` (local demo only) shows
them all in light and dark. Not checked against a trademark register.

## Never

Gradients, glow, glass effects, emoji, illustrations, saturated or neon
colours, more than one chart, a chart without its legend, a "Set budget"
link on every row, ads, promo cards.

## Words and numbers

- Plain and short: "Spent", "Paid back", "To confirm", "Net". No exclamation
  marks; no "journey" or "insights".
- Rupees with Indian grouping: `₹1,23,456`. Overviews round to whole rupees
  (half away from zero); transaction detail shows paise (`₹1,23,456.78`). A
  minus is the real minus sign (`−₹1,500`).
- Dates and times in IST (fixed +05:30): "Tue 17 Nov", "14:05"; detail shows
  "Tue 17 Nov 2026, 14:05". Months: "Nov 2026".

## Screens

1. **Login**: the wordmark, email and password, no sign-up link. Supabase
   Auth (`@supabase/supabase-js`) keeps the session and refreshes the token.
   A wrong password says "Email or password is wrong."; after a 401 the
   screen says "Your session ended. Sign in again." A login the API does not
   know (403) shows "This account has no access" with Sign out. In demo mode
   any input continues.
2. **Home**, in this order: the wordmark, the version line and a Sign out button; month
   switcher (‹ Nov 2026 ›); Net as the
   headline; "Spent ₹X · Paid back ₹Y"; one plain line comparing Spent with
   last month ("Spent ₹7,580 more than this time last month": the current
   month compares with last month up to the same IST day, a past month with
   the whole month before it); a "To confirm: ₹Z from N people" row when
   Z > 0, opening To-do; Spent by category with the List | Chart control.
   List, sorted by amount: tile, name, amount, percent of Spent, a thin bar
   in the category colour filled to that share (37 % fills 37 %), and a small
   change versus last month ("₹889 more", "same", "new"; a caption names what
   it compares with). Chart: the ring above. Then "Recent", the last five
   transactions; a muted footnote "N messages not counted yet". The
   comparison comes from `/summary` (`previous`).
3. **Category detail**: the category tile beside the title; merchants with
   their totals, biggest first ("Paid to"); tap one for its transactions.
4. **People ledger** (People's category detail): one row per person (the
   API's `person_id`) with Net, and Sent and Got back under it, biggest Sent
   first. Sent is People spending to them; Got back is their confirmed
   paybacks (they count as Paid back); paybacks still to confirm show as "To
   confirm" and never lower Net. A person's view shows Sent, Got back, To
   confirm and Net, then both directions by day; money in is marked "+" in
   the muted green, and a payback row says "Paid back" or "Money in, to
   confirm".
5. **Transactions**: month switcher, a name search (every word must appear,
   any case), category and label filters. The whole month is loaded, so
   search and filters cover all of it. Grouped by IST day; day headers stay at
   the top while their rows scroll. Each row: category tile, name, category in
   small text, amount right-aligned. A row opens a bottom sheet: amount with paise, time,
   how it is counted, category (automatic or set by you), label; "Change
   category" (a picker with each category's tile, then "Just this one" or "All
   from <name>") and "Label" (pick, remove, or make a new one). A link to a
   transaction that is not in the list loads it by id.
6. **To-do**: compact rows. "Who sent you money?": senders to confirm,
   biggest first, each with Friend, Family and Ignore on one line (they wrap
   only at large text sizes). Family means income; its label defaults to
   "Family" and can be edited (trimmed, 1 to 30 characters; several senders
   may share one). "Pick a category": uncategorised merchants with a category
   picker. An answered row collapses away in 200 ms (at once with reduced
   motion). "Answered": senders already answered (friend, income or ignored),
   with the answer as the server saved it ("Income: Pocket money") and
   "Change", which offers Friend, Family, Ignore and "Ask me again later"
   (the sender goes back to "Who sent you money?").
7. **Labels**: each label with Spent, Paid back and Net, and its number of
   payments; tap for its category breakdown (bars are shares of the label's
   Spent) and transactions; make a new label.

Sheets were checked at 360 px and at 200 % text: the panel scrolls, values
wrap under their terms and buttons grow.

## Label names

Trimmed (inner runs of spaces become one), 1 to 30 characters, and refused
when another label has the same name in any case. The API applies the same
rules (a duplicate is a 409), so a name the app lets through is saved as
shown. The reason shows under the
field as the owner types ("A label with this name already exists.", "Use at
most 30 characters."); Create stays disabled until the name is fine.

## Freshness, offline and Speed (4B-1)

- **Freshness line** under the month switcher on Home and Transactions,
  one line of muted `text-xs`, IST: "Updated just now", "Updated 5 min
  ago", "Updated 2 h ago", "Updated yesterday 21:40", older "Updated Mon 16
  Nov 21:40"; while a refresh runs "Updating…"; after a failed refresh
  "Offline · showing data from 5 min ago". No spinner over the numbers, no
  banner. The screens show the phone copy at once (D-089).
- **Owner actions** (4B-2) are saved on the phone first and sent in the
  background, online or offline; see "Waiting to sync".
- **Speed sheet**: tap the version line on Home. The usual sheet: the two
  targets ("Open from phone copy: 2 s or less", "Fresh data, server awake:
  5 s or less"), the last launch (phone copy ms, fresh data s, request ms,
  size, result) and a plain table of the last 10 launches (time IST, local
  ms, fresh s, result; "cold" when the request took over 10 s), and a Sync
  block (waiting, couldn't save, last drain: time, sent, seconds; last
  error). Measured on the phone and kept there (D-090). In the URL as
  `?speed`, so Back closes it.

## Waiting to sync (4B-2, D-091, D-093)

- **A tap is saved at once.** Every owner action goes to the outbox on the
  phone and is sent in the background, online or offline. No spinner, no
  banner, no toast per tap.
- **Pending item**: the item shows the owner's choice with muted "Waiting
  to sync" (and Undo while it has not started sending). A transaction row
  shows the new category tile and name, or the label, then "· Waiting to
  sync"; the sheet shows it under Category or Label. Once the server
  confirms, the choice stays without the note until the fresh numbers
  arrive. Totals, the ring, percentages, ledger sums and comparisons never
  change for a pending tap (D-088).
- **To-do**: a sender or merchant with an answer waiting leaves its list
  and the tab's count, and shows in "Waiting to sync" at the top: "Rohit V",
  then "Friend · Waiting to sync · Undo".
- **Labels**: a label being made shows at the top of the list with
  "Waiting to sync" and no totals.
- **Sync line**: the freshness line gains "· 3 waiting to sync"; "1 couldn't
  save" is a link to the **Couldn't save** sheet (`?unsaved`): each refused
  change with what it was, its item, the server's reason, Retry and Discard.
  After a lasting 401 the line says "Sign in to sync" (a link to the login;
  nothing is lost).
- **Sign out** with changes not synced: a sheet "2 changes haven't synced
  yet. If you sign out now they will be lost." with "Stay signed in"
  (primary) and "Sign out anyway".
- **To-do merchant cards** say when, like sender cards: "1 payment · Tue 12
  Nov", "3 payments · last Tue 12 Nov".

## Update bar and version line

- **Update bar** (D-085): when a new version has installed and waits, a
  bordered surface card at the bottom, 8 px above the navigation (above the
  safe area when there is no navigation): "New version available", then
  Later (plain button) and Reload (primary button), the same 44 px buttons
  as elsewhere. It wraps at large text sizes. Reload switches to the new
  version and reloads once; Later hides it until the next launch. It sits in
  a `role="status"` region, so a screen reader announces it, and it never
  appears or reloads on its own beyond that. No animation.
- **Version line** (D-087): Home's header, left of Sign out, one line of
  `text-xs` muted text: "Version 0.1.0 · build 1a2b3c4" (`dev` on a local
  build). It wraps under 360 px or at large text sizes. It is a button: it
  opens the Speed sheet.

## States

- **Server waking**: only when the session's first request takes over 3 s:
  "Starting up, this can take about a minute" with one thin progress bar that
  slows as it goes. No spinner wall. After any answer, a slow load shows only
  "Loading".
- **Empty month**: one line, "Nothing recorded in Nov 2026."
- **Error**: "Could not load", the reason, and "Try again". No network:
  "Could not reach the server. Check the connection and try again." A 503:
  "The server is not ready yet. Try again in a minute."
- **Signed out**: a 401 from the API signs out on this device and shows the
  login with "Your session ended. Sign in again."
- **No access**: a 403 shows "This account has no access" and Sign out.
- **Stale**: a quiet notice "Totals are being updated." above the numbers.
- While a screen reloads after a change, the old numbers stay until the new
  ones arrive.

## Demo mode

Only in local development with `VITE_DEMO=1`: a production build always
uses the HTTP adapter and leaves the demo adapter, banner, State switch and
`#/dev` page out of the bundle. Every screen carries a "Demo data. Not your real numbers." banner at the top,
in the page flow: it scrolls away with the page and never covers content, at
any width or text size. Its State switch (normal, waking, empty, error, stale)
is there only while the demo adapter is in use; picking a state starts a new
session, so "waking" shows "Starting up" again. The data is a student's
October and November 2026 with fake names: daily chai and canteen meals, a few
large transfers to people, UPI senders to confirm, and a Goa trip label.

## API gaps

3F-3 closed every "Backend" gap of the 3F-2 list (role basis, label totals,
last month, person id, ignored senders and undo, the income label, a
transaction by id, label name rules; `docs/api.md`). What stays in the
client on purpose:

| What | Why it is fine in the client |
| ---- | ---------------------------- |
| Name search | Transactions loads the whole month (pages of 200); fine at a few hundred rows a month. Add `q` to the API if months grow far larger. |
| Merchant groups | Category detail and To-do group by display name; `/merchants?category=` if it grows. |
| Merchant answers | No list of "All from" answers yet; one is changed from any of its transactions. Backend, later. |
| The waking probe | The session's first request is the probe. |
