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
  size scales everything; at 200 % on a 360 px screen rows grow, a row's
  amount moves under its name (a name keeps at least `min(6rem, 35vw)`), buttons wrap,
  and nothing scrolls sideways (4H). Four figures are capped by the screen
  width so they fit at 200 %: Net (`min(2.25rem, 12vw)`), a label's or a
  transaction's amount (`min(1.875rem, 11vw)`), the ring (`min(14rem,
  78vw)`) and its centre, and the tab names (`min(0.75rem, 3.3vw)`).
- 8 px radius, 1 px hairline borders, no shadows. Lists are bordered cards
  of rows; rows are at least 56 px tall, every control at least 44 px.
- Long names truncate with an ellipsis. Amounts never wrap.

### Tokens (D-113)

Every screen uses these and nothing else (Tailwind names; `index.css`).

| Token | Values | Used for |
| --- | --- | --- |
| Spacing | 4 px steps: 1 (4), 2 (8), 3 (12), 4 (16), 6 (24), 10 (40); half steps 0.5, 1.5, 2.5 inside rows | 16 px side gutter (`px-4`), 8 px between buttons, 12 px between a tile and its text |
| Radius | `rounded-lg` 8 px; `rounded-md` 6 px inside a segmented control; `rounded-full` for bars and the To-do count | cards, buttons, inputs, sheets (top corners), tiles |
| Type | `text-xs` 12, `text-sm` 14, base 16, `text-lg` 18 (screen titles), `text-xl` 20 (a full-page message); figures 24 to 36 (capped as above) | muted notes, rows, titles, Net |
| Weight | 400; 500 for names and buttons; 600 for titles and figures | |
| Lines | 1 px `line` borders and dividers | cards, rows, sheet header |
| Colour | the tokens under Colour; category colours only for tiles, bars and slices | |
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

`#/<tab>/<detail>?m=<month>&cat=<slug>&label=<id>&q=<search>&txn=<id>&who=<person>&person=<person>&do=<step>`

| Part | Meaning |
| ---- | ------- |
| tab | `home`, `transactions`, `todo`, `labels` (`dev` for dev pages) |
| detail | `home/category/<slug>`, `home/category/<slug>/<name>` (for People, a person id), `labels/<id>` |
| `m` | the month, `2026-11`; none means the current IST month |
| `cat`, `label`, `q` | Transactions: category filter, label filter, name search |
| `txn` | the transaction whose sheet is open |
| `who` | Transactions of one person, every month ("See payments", 4E) |
| `person`, `do` | the person sheet, opened at `name` or `join` (4E) |

- Opening a layer (a detail or a sheet) adds a history entry. Back closes the
  topmost layer: an app-wide sheet, the person sheet, the transaction sheet,
  one person's payments, then the detail, then the tab's root. "See
  payments" opens as a layer, so Back returns to the To-do card or sheet it
  came from. The same
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
- Every two colours are at least 10 apart in CIEDE2000, in both themes, so
  neighbouring ring segments and list rows read apart whatever the order
  (4H). Eight pairs were closer (light: entertainment and EMI 7.4, health
  and fees 9.4, rent and other 9.7; dark: education and people 6.9, health
  and fees 7.6, shopping and personal care 7.8, entertainment and EMI 8.5,
  subscriptions and personal care 8.5, subscriptions and card bill 9.1,
  shopping and gifts 9.3, groceries and investments 9.97). The less used
  colour of each moved by the smallest step that clears 10 (0.4 to 3.7):
  light EMI, fees, other; dark education, fees, personal care, EMI, card
  bill, gifts, investments. `src/colours.test.ts` checks all of this and the
  text contrast. Identity still never rests on colour alone: every tile has
  its icon and every bar, slice and legend row its name.

| Category | Light | Dark |
| -------- | ----- | ---- |
| food_drinks | `#a66535` | `#dd9e73` |
| groceries | `#508659` | `#8ec094` |
| travel | `#4476a0` | `#85b4dc` |
| shopping | `#995a7e` | `#d295b7` |
| bills_recharges | `#8f7835` | `#cbb67b` |
| subscriptions | `#7d659a` | `#b9a2d5` |
| health | `#a24f4e` | `#dc8b89` |
| personal_care | `#a27a9d` | `#e1bbdc` |
| entertainment | `#49578d` | `#8796cb` |
| education | `#206173` | `#6193a7` |
| rent_hostel | `#785e40` | `#b39a7d` |
| emi_loans | `#34485e` | `#73829b` |
| investments | `#2c6e5a` | `#6fa996` |
| gifts_donations | `#7a4058` | `#b2798e` |
| people | `#388b94` | `#65acb4` |
| cash | `#60612c` | `#979968` |
| card_bill | `#7d7d9b` | `#acafca` |
| fees_charges | `#7d3e32` | `#b77c6c` |
| other | `#574d38` | `#8f8571` |
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

Logo **C2** (4F-A; the owner picked option C of 4E,
`docs/design/logo-options.html` shows C next to C2). An original mark drawn
as paths with no font (`frontend/src/brand.tsx`): a flat-topped lightning
bolt slanted 10 degrees like the wordmark, with the app's $ (three bars
joined by half circles, a stub above and below) cut through it, centred on
the bolt's centre of area. The cut is a fixed share of the bolt, so it stays
open at 48 px. One colour on a dark tile; no gradient, glow or outline. The
**wordmark** "FLA$H" uses the same bolt, cut the same way, as its S: letters
in the text colour, the bolt in the accent. It sits at the top of Home and on
the login screen.

The app icon is the bolt in `#7cc4bb` on a `#16191b` tile (8.7:1), the $ cut
in the tile colour: `pwa-192x192.png` and `pwa-512x512.png` (rounded tile),
`maskable-512x512.png` (full bleed; the bolt stays inside the safe circle,
radius 0.395 of 512) and `apple-touch-icon.png` (180 px, full bleed), all
rendered from the SVG with headless Edge (no package). `favicon.svg` uses the
same bolt larger (a tab has no launcher mask), so it reads at 16 to 24 px.
The manifest `id` and `start_url` are unchanged. `#/dev/logos` (local demo
only) shows them in light and dark. Not checked against a trademark
register.

## Never

Gradients, glow, glass effects, emoji, illustrations, saturated or neon
colours, more than one chart, a chart without its legend, a "Set budget"
link on every row, ads, promo cards.

## Words and numbers

- Plain and short: "Spent", "Paid back", "To confirm", "Net". No exclamation
  marks; no "journey" or "insights".
- Money (D-113), one formatter (`lib/money.ts` `rupees`): Indian grouping
  everywhere (`₹1,00,000`, `₹12,34,567`). Totals (Net, Spent, a category, a
  person, a merchant, a label) in whole rupees, half away from zero. A
  transaction's own amount (its row, its sheet, a To-do check, the person
  sheet's recent payments) shows paise only when they are not zero:
  `₹450`, `₹450.25`. Money in has a plus (`+₹450`); a minus is the real
  minus sign (`−₹1,500`).
- Dates and times in IST (fixed +05:30), one set (D-113): a day "Tue 17
  Nov" (rows, day headers, cards); a moment "Tue 17 Nov, 14:05" (sync
  details, Speed, freshness after yesterday); a transaction in full "Tue 17
  Nov 2026, 14:05" (its sheet); a time "14:05"; a month "Nov 2026".
- One voice: Indian English spellings as used ("Uncategorised"); errors
  start "Could not …"; a change the server refused is "Not saved" (its
  item, the line under the month, the sheet title).

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
   first. A named person shows its identifiers in small muted text under the
   name. A row opens the **person sheet** (see "People", 4E). Sent is People spending to them; Got back is their confirmed
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

## People (4E, D-096)

- **A name and its identifiers**: wherever a named person appears (To-do,
  the ledger, transaction rows and the sheet) the owner's name is shown,
  with the identifier the bank used ("Rohit V", "*r203@okhdfcbank") in small
  muted text under it, or after it on a transaction row.
- **To-do sender card**: under Friend / Family / Ignore, quiet text buttons
  "Name", "Same as…" and "See payments".
- **Person sheet actions** (4H, D-110), first in the sheet, quiet and
  compact, in this order:
  - "Payments to them count as": the category chips (the owner's most used,
    up to four; the one every payment to them has now is pressed) and
    "More…". A pick is the party default ("All from"): every payment to the
    person, whichever name or UPI ID the bank used, also future ones. Shown
    only when they were paid.
  - "Money from them is": Friend / Family / Ignore / Income (Income asks for
    its label). Shown only when they sent money. One write per sender.
  - "Recent payments": the last 10 (day, category or what the row is,
    amount); a spending row opens the same chips for "just this one". "See
    all payments" below.
  Each change goes through the outbox and shows "Saved on phone · syncing"
  on the changed row or line; no total moves on the phone. The sheet opens
  from a ledger row, from "Person" on a To-do sender card and from "Person"
  on a transaction sheet.
- **Person sheet** (`?person=`): the name, "Answer: Friend", the identifiers
  (each with Separate when the person has more than one; "From the owner
  file" instead when the file set it), then Rename (Name), Same as…, Clear
  name; from the ledger also "This month with <name>" (the
  month's Sent, Got back and rows). A footnote: "Names and joins are yours:
  they change no amount, only who is who."
- **Same as…**: a list of everyone (search by name or UPI ID), each with its
  answer. Picking one joins at once, unless both have different answers:
  then "Rohit V is Friend; *k77@okhdfcbank is Ignore. Which answer does the
  person keep?" with "Keep Friend" (primary: the person joined into), "Use
  Ignore" and Cancel. Nothing is chosen silently.
- **Transaction sheet**: a Person line (name and identifier) with Rename,
  Same as… and Separate (when the person has more than one identifier).
- **Offline**: each action waits in the outbox; the card or sheet shows the
  new name or "Same as Rohit V" with "Saved on phone · syncing" and Undo. Totals never
  move until the server's numbers arrive.
- **See payments** (sender and merchant cards, the person sheet):
  Transactions of that person across all months, titled "Payments with
  <name>" with "Show all" instead of the month switcher.
- **Merchant cards**: the same chips component as the person sheet: up to four one-tap category chips (the owner's most
  used categories, by how many rows they set, then all rows; never by money)
  and "More…" for the full list. A chip means "All from" that merchant.

## Checks (4F-A, D-101, D-103)

- **To-do, "Check these payments"**: rows the app read automatically from a
  bank with no parser of its own yet: name, amount, "date · Read
  automatically", then "Looks right" and "Not a payment". An answer leaves
  the list at once and waits under "Saved on phone" until it syncs. The To-do
  badge counts these rows too.
- **Transaction sheet**: a generic row shows "Read automatically" in small
  muted text under the amount. Quiet buttons under the main ones: "Looks
  right" (only while it asks), and "Not a payment" on any row except a
  duplicate, which becomes "Count it again" once the row is ignored. The
  Counted line shows a waiting choice with "Saved on phone · syncing" and Undo.
- Offline, all three wait in the outbox like every other answer (D-091).

## Moved between your accounts? (4A, D-115)

- **To-do section** "Moved between your accounts?", after "Saved on phone"
  and before "Check these payments": one card per pair the engine is not
  sure of (the same amount left one of the owner's accounts and reached
  another within 30 minutes, with no shared reference). The card: "HDFC to
  SBI" and the amount (paise only when not zero); under it "Tue 17 Nov,
  10:00 out · 10:12 in"; buttons "Yes, my accounts" and "No"; a muted
  line "Yes: neither counts as spending or money in."
- An answer leaves the list at once, waits under "Saved on phone" ("Moved
  between my accounts" or "Not a transfer") and goes through the outbox,
  offline too. Totals change only when the server's numbers arrive. The To-do
  badge counts these cards.
- A pair with a shared 12-digit reference is never asked: it is a transfer
  already.

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
  background, online or offline; see "Saved on phone".
- **Speed sheet**: tap the version line on Home. The usual sheet: the two
  targets ("Open from phone copy: 2 s or less", "Fresh data, server awake:
  5 s or less"), the last launch (phone copy ms, fresh data s, request ms,
  size, result) and a plain table of the last 10 launches (time IST, local
  ms, fresh s, result; "cold" when the request took over 10 s), and a Sync
  block (waiting, not saved, last drain: time, sent, seconds; last
  error). Measured on the phone and kept there (D-090). In the URL as
  `?speed`, so Back closes it.
- **Speed: Boot** (4B-3, D-095): a Boot block (path of the last launch:
  "local copy", "online", "login" or "error screen"; time to the first
  screen in ms; the count of boot errors, then the last 5, time IST and
  message), and a Boot column in the launches table ("–" for launches
  before 4B-3).

## Saved on phone (4B-2, 4F-B: D-091, D-093, D-105, D-107)

- **A tap is saved at once.** Every owner action goes to the outbox on the
  phone and is sent in the background, online or offline. No spinner, no
  banner, no toast per tap.
- **Pending item**: the item shows the owner's choice with muted "Saved on
  phone · syncing" (and Undo while it has not started sending). A
  transaction row shows the new category tile and name, or the label; the
  sheet shows the note under Category, Label or Counted. Once the server
  confirms, it says "Synced" for 2 s, then the choice stays without a note
  until the fresh numbers arrive. Totals, the ring, percentages, ledger sums
  and comparisons never change for a pending tap (D-088).
- **After 2 minutes** still waiting: "Saved on phone · not synced yet: no
  connection" (or: server didn't answer, server error, the server refused
  the request, needs sign-in, needs your choice). Tapping it opens a small
  sheet: when it was saved, attempts, last try (IST), the reason, "Try now"
  (and Undo while it has not started sending).
- **To-do**: a sender or merchant with an answer waiting leaves its list
  and the tab's count, and shows in "Saved on phone" at the top: "Rohit V",
  then "Friend · Saved on phone · syncing · Undo". A change the server
  answered with a conflict stays there with "Not saved · needs your
  choice", "Try again" and "Discard".
- **Refused on its item** (4H): a change the server refused also stays on
  the item it was about (transaction row and sheet, person sheet, To-do
  card): "Not saved · <reason>" with "Try again" and "Discard". The item
  keeps the server's value meanwhile.
- **Labels**: a label being made shows at the top of the list with
  "Waiting to sync" and no totals. A transaction sheet lists it among the
  labels ("saved on phone") so another payment can take it before it syncs;
  that sends the same name as `new_label`, and the server finds the label
  the first change made (D-110).
- **Sync line**: the freshness line gains "· 3 saved on phone, syncing"; "1 not
  saved" is a link to the **Not saved** sheet (`?unsaved`): each refused
  change with what it was, its item, the server's reason, Retry and Discard.
  After a lasting 401, or when the server refused the stored session at
  launch, the line says "Not synced · showing data from …" and "Sign in to
  sync" (a link to the login; the data and the waiting changes stay on
  screen and on the phone). Signing in with the same login keeps them and
  sends the changes; another login deletes them first (D-095).
- **Sign out** with changes not synced: a sheet "2 changes haven't synced
  yet. If you sign out now they will be lost." with "Stay signed in"
  (primary) and "Sign out anyway".
- **To-do merchant cards** say when, like sender cards: "1 payment · Tue 12
  Nov", "3 payments · last Tue 12 Nov".

**Speed sheet**: the Sync block comes first: saved on phone, failed, last
attempt (IST time and result code), last success, last error. Then the
targets, the last launch, the launches table and the boot block.

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
- **Empty** (one calm line, no illustration): a month "Nothing recorded in
  Nov 2026."; a month with no spending "No spending this month."; To-do
  "Nothing to do."; Labels "No labels yet."; People "No money to or from
  people this month."; Not saved "Everything is saved."
- **No spinner over content**: loading is the word "Loading" where the
  content goes, or "Updating…" on the freshness line while the old numbers
  stay.
- **Error**: "Could not load", the reason, and "Try again". No network:
  "Could not reach the server. Check the connection and try again." A 503:
  "The server is not ready yet. Try again in a minute."
- **Launch** (4B-3, D-095): the first screen never waits on the network.
  Signed in on this phone, the phone copy shows at once, even offline with
  an expired session; with no stored session, the login. Offline, the login
  says "You're offline. Connect to sign in." and Sign in answers that at
  once instead of spinning.
- **Session refused**: a 401 from the API, or a stored session the server
  refused, keeps the screen and shows "Sign in to sync" on the freshness
  line (see "Saved on phone"). Tapping it opens the login with "Sign in
  again to sync your changes."
- **No access**: a 403 shows "This account has no access" and Sign out.
- **Stale**: a quiet notice "Totals are being updated." above the numbers.
- **Something went wrong** (D-095): an exception anywhere shows a plain
  page: "Something went wrong", "Your data on this phone is safe. Reload to
  start the app again.", Reload (primary) and Copy details (plain), and the
  message in small muted text. The error is kept for the Speed sheet.
- **Could not start** (D-095): when the app's code does not start 3 s after
  load (a file failed to load), `index.html` itself shows "Flash could not
  start", "Part of the app did not load. Your data on this phone is safe.
  Connect to the internet and reload." and Reload, in the page colours. Never
  a blank screen.
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
