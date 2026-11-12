# data/

Everything in this folder except this README is gitignored.

| Path                               | What                                       | Who reads it          |
| ---------------------------------- | ------------------------------------------ | --------------------- |
| `data/raw/`                        | SMS Backup & Restore XML exports (private) | Only you, never tools |
| `data/private/`                    | `name_map.json`, `ref_map.json` (real to fake) | Only you, never tools |
| `data/sample/redacted_sample.json` | Output of `scripts/redact_sms.py`          | You, then the team    |

Agents are blocked from `data/raw/` and `data/private/` by
`.claude/settings.json`.

## Make a redacted sample

Run these from the repo root in PowerShell.

1. Put the `.xml` export in `data/raw/`.
2. See which senders exist (IDs and counts only, no message text):

   ```powershell
   backend\.venv\Scripts\python.exe scripts\redact_sms.py --list-senders
   ```

   Add any missing bank, card, UPI or wallet IDs to `DEFAULT_SENDERS` in
   `scripts/redact_sms.py`, or pass `--senders ID1,ID2,...` (this replaces the
   default list).
3. Make the sample:

   ```powershell
   backend\.venv\Scripts\python.exe scripts\redact_sms.py --limit 50
   ```

   It prints progress every 5,000 messages, then a summary of kept and dropped
   counts.
4. Review before sharing:
   - Open `data/sample/redacted_sample.json` and skim it.
   - Open `data/private/name_map.json`. If a merchant was mistaken for a
     person, set its value to the name itself (for example
     `"CHAI POINT": "CHAI POINT"`) and run step 3 again.
5. Tell the team the sample exists. Only the sample is shared, never
   `data/raw/` or `data/private/`.

Run `--help` for all options (`--senders`, `--limit`, `--seed`, `-o`,
`--private-dir`).
