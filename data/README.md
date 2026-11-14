# data/

Real data never lives in this repo. Everything in this folder except this
README is gitignored.

| Path                               | What                                        | Who reads it          |
| ---------------------------------- | ------------------------------------------- | --------------------- |
| `D:\FlashPrivate\raw\`             | SMS Backup & Restore XML exports            | Only you, never tools |
| `D:\FlashPrivate\private\`         | `name_map.json`, `redaction.key`, `seen_ids.json`; optional `keep_names.txt`, `always_redact.txt` | Only you, never tools |
| `data/sample/redacted_sample.json` | Output of `scripts/redact_sms.py`           | You, then the team    |

Agents are blocked from `D:\FlashPrivate\`, `data/raw/`, `data/private/` and
every `.env` file by `.claude/settings.json`. Agents run the redaction script
only on synthetic files that tests create in a temp folder.

**Never paste `--list-counterparties` output into a chat.** It shows real
names and UPI IDs. Only the redacted sample and `--verify` output (tokens and
positions only) are safe to share.

## One-time setup: always_redact.txt

Create `D:\FlashPrivate\private\always_redact.txt` with one entry per line:
your name variants, family names, your phone number. Lines starting with `#`
are comments. Every whole-word occurrence of an entry is replaced in a final
pass, wherever it appears in a message; phone numbers get the usual 10-digit
fake. Entries are never printed.

## Make a redacted sample

Run these yourself, from the repo root, in PowerShell.

1. See which senders exist (IDs and counts only, no message text):

   ```powershell
   backend\.venv\Scripts\python.exe scripts\redact_sms.py --input D:\FlashPrivate\raw --private-dir D:\FlashPrivate\private --list-senders
   ```

   Senders are grouped by their normalised core: `VKSBIBNK`, `VM-SBIBNK-S`
   and `SBIBNK` all count as `SBIBNK`. `VARIANTS` shows how many raw IDs were
   merged. The allowlist is banks and UPI only (data minimisation; brokers,
   exchanges and investment apps stay out until Phase 6). To add a bank, put
   its core in `DEFAULT_SENDERS` in `scripts/redact_sms.py`, or pass
   `--senders CORE1,CORE2,...` (this replaces the default list).

2. See which counterparties will be pseudonymised (names and UPI IDs with
   counts). Everything not marked `yes` becomes a token. Read it locally only:

   ```powershell
   backend\.venv\Scripts\python.exe scripts\redact_sms.py --input D:\FlashPrivate\raw --private-dir D:\FlashPrivate\private --list-counterparties
   ```

   - Public brands you want kept (Swiggy, your bank): add them to
     `scripts/keep_names.txt` (committed, public brands only).
   - Anything private you still want kept (a local shop): add it to
     `D:\FlashPrivate\private\keep_names.txt` (never committed).

3. Make the sample. This is the **standard command**; use it every time:

   ```powershell
   backend\.venv\Scripts\python.exe scripts\redact_sms.py --input D:\FlashPrivate\raw --private-dir D:\FlashPrivate\private --output data\sample\redacted_sample.json --limit 100 --seed 42 --verify
   ```

   - `--limit 100 --seed 42`: up to 100 messages per sender, the same random
     pick every run.
   - `--verify` scans the written sample for leaks: every `always_redact.txt`
     entry (as a substring, so joined words are caught), every 2+ word name in
     `name_map.json`, and every real UPI ID and reference seen during
     redaction (compared by keyed digest; the real values are never stored).
     It prints only tokens and message numbers, for example
     `LEAK PARTY_014 in message 37`, then `Leaks: N`. Single-word map names
     are counted separately as `possible (single word): N`.
   - The command exits with code 1 if `Leaks` is above 0. Do not share the
     sample until it says `Leaks: 0`. If a leak is reported, add the name to
     `always_redact.txt` and run again.

   The first run creates `redaction.key`, `name_map.json` and `seen_ids.json`
   in the private folder. Keep them: later runs reuse them, so the same name or
   reference always gets the same fake. Losing the key changes every fake.

4. Optional re-check of an existing sample without re-running the redaction:

   ```powershell
   backend\.venv\Scripts\python.exe scripts\redact_sms.py --private-dir D:\FlashPrivate\private --output data\sample\redacted_sample.json --verify
   ```

5. Tell the team the sample exists. Only the sample is shared.

`--help` lists every option.
