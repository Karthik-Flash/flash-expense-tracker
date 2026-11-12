# data/

Everything in this folder except this README is gitignored.

| Path                                | What                                       | Who reads it          |
| ----------------------------------- | ------------------------------------------ | --------------------- |
| `data/raw/`                         | SMS Backup & Restore XML exports (private) | Only you, never tools |
| `data/sample/redacted_sample.json`  | Output of `scripts/redact_sms.py`          | You, then the team    |

## Make a redacted sample

1. Export SMS with the SMS Backup & Restore app. Copy the `.xml` file into
   `data/raw/`.
2. From the repo root, run:

   ```powershell
   backend\.venv\Scripts\python.exe scripts\redact_sms.py --limit 50
   ```

   ```bash
   backend/.venv/bin/python scripts/redact_sms.py --limit 50
   ```

3. Open `data/sample/redacted_sample.json` and check it yourself before you
   share it. The script masks account and card numbers, UPI IDs and phone
   numbers. It does not mask person names in P2P transfers.

Run `python scripts/redact_sms.py --help` for all options (`--senders`,
`--limit`, `--seed`, `-o`).
