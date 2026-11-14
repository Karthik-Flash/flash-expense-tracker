# data/

Real data never lives in this repo. Everything in this folder except this
README is gitignored.

| Path                               | What                                        | Who reads it          |
| ---------------------------------- | ------------------------------------------- | --------------------- |
| `D:\FlashPrivate\raw\`             | SMS Backup & Restore XML exports            | Only you, never tools |
| `D:\FlashPrivate\private\`         | `name_map.json`, `redaction.key`, optional `keep_names.txt` | Only you, never tools |
| `data/sample/redacted_sample.json` | Output of `scripts/redact_sms.py`           | You, then the team    |

Agents are blocked from `D:\FlashPrivate\`, `data/raw/`, `data/private/` and
every `.env` file by `.claude/settings.json`. Agents run the redaction script
only on synthetic files that tests create in a temp folder.

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
   counts, no message text). Everything not marked `yes` becomes a token:

   ```powershell
   backend\.venv\Scripts\python.exe scripts\redact_sms.py --input D:\FlashPrivate\raw --private-dir D:\FlashPrivate\private --list-counterparties
   ```

   - Public brands you want kept (Swiggy, your bank): add them to
     `scripts/keep_names.txt` (committed, public brands only).
   - Anything private you still want kept (a local shop): add it to
     `D:\FlashPrivate\private\keep_names.txt` (never committed).

3. Make the sample:

   ```powershell
   backend\.venv\Scripts\python.exe scripts\redact_sms.py --input D:\FlashPrivate\raw --private-dir D:\FlashPrivate\private --output data\sample\redacted_sample.json --limit 50
   ```

   The first run creates `redaction.key` and `name_map.json` in the private
   folder. Keep both: later runs reuse them, so the same name or reference
   always gets the same fake. Losing the key changes every fake.

4. Skim `data\sample\redacted_sample.json`. Names are detected where bank
   messages put them (to/from/by/at, `UPI/P2P/.../NAME`, `; NAME credited`,
   `Dear NAME`). A name written anywhere else is not detected, so check.
5. Tell the team the sample exists. Only the sample is shared.

`--help` lists every option.
