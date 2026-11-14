"""Tests for redact_sms.py. Synthetic messages in temp folders only; never real data."""

import json
import re
import tracemalloc
from pathlib import Path
from xml.sax.saxutils import quoteattr

import pytest
import redact_sms as r

SENDERS = "HDFCBK,ICICIT,AXISBK,SBIUPI,KOTAKB"
REPLACEMENT_CHAR = chr(0xFFFD)


def write_backup(path: Path, rows: list[tuple[str, str]], mms: int = 0) -> Path:
    """Write a minimal SMS Backup & Restore file. Bodies may contain raw char refs."""
    with path.open("w", encoding="utf-8") as f:
        f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<smses count="{len(rows)}">\n')
        for i, (address, body) in enumerate(rows):
            body_attr = quoteattr(body).replace("&amp;#", "&#")  # keep test char refs raw
            f.write(f'<sms address="{address}" date="{1762300000000 + i}" body={body_attr} />\n')
        for _ in range(mms):
            f.write('<mms date="1762300000000"><parts><part data="' + "QUFB" * 5000)
            f.write('" /></parts><addrs><addr address="+919876543210" /></addrs></mms>\n')
        f.write("</smses>\n")
    return path


def run(xml: Path, private: Path, out: Path, *extra: str) -> list[dict]:
    args = ["--input", str(xml), "--private-dir", str(private), "--output", str(out)]
    assert r.main([*args, "--senders", SENDERS, *extra]) == 0
    return json.loads(out.read_text(encoding="utf-8"))


P2P_ROWS = [
    (
        "VM-HDFCBK",
        "Sent Rs.500.00\nFrom HDFC Bank A/C *1234\nTo RAHUL KUMAR\nOn 12/11/26\n"
        "Ref 612345678901\nNot You?\nCall 18002586161/SMS BLOCK UPI to 7308080808",
    ),
    (
        "JD-ICICIT-T",
        "ICICI Bank Acct XX123 debited for Rs 500.00 on 12-Nov-26; Rahul Kumar credited.",
    ),
    ("AD-AXISBK-S", "INR 200.00 debited A/c no. XX1234 UPI/P2A/612345678903/PRIYA S Not you?"),
    ("VM-SBIUPI", "Rs 900 credited to a/c XX1234 by IMPS from Mr. ANIL VERMA. Ref 612345678904"),
    ("VM-KOTAKB", "Rs 120 paid via UPI to CHAI POINT on 12-11-26. UPI Ref 612345678905"),
    ("VM-HDFCBK", "Rs 99 spent on HDFC Bank Card XX9876 at ZOMATO LTD on 2026-11-12"),
    ("VM-HDFCBK", "Dear Asha, Rs 5 debited from A/c XX1234"),
]
REAL_NAMES = ("RAHUL", "KUMAR", "PRIYA", "ANIL", "VERMA", "CHAI", "POINT", "ZOMATO LTD", "ASHA")


# --- CLI ----------------------------------------------------------------------
def test_input_private_dir_and_output_are_required(tmp_path: Path) -> None:
    xml = write_backup(tmp_path / "a.xml", [("VM-HDFCBK", "Rs 5 debited")])
    with pytest.raises(SystemExit):
        r.main([])
    with pytest.raises(SystemExit):
        r.main(["--input", str(xml)])
    with pytest.raises(SystemExit):
        r.main(["--input", str(xml), "--private-dir", str(tmp_path / "p")])


# --- Filtering ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("JXSBIINBS", ("SBIINB", "S")),  # 9 chars: prefix + core + suffix
        ("vmhdfcbkp", ("HDFCBK", "P")),  # 9 chars, lowercase input
        ("VKSBIBNK", ("SBIBNK", "")),  # 8 chars: prefix + core
        ("CPSBIBNK", ("SBIBNK", "")),
        ("HDFCBKT", ("HDFCBK", "T")),  # 7 chars: core + suffix
        ("SBIBNK", ("SBIBNK", "")),  # 6 chars: already a core
        ("CP388558", ("388558", "")),  # numeric short code with prefix
        ("388558", ("388558", "")),
        ("ABC123@RBM.GOOG", ("ABC123@RBM.GOOG", "")),  # RCS ID: unchanged
        ("+919876543210", ("+919876543210", "")),  # phone number: unchanged
    ],
)
def test_parse_sender_length_rules(address: str, expected: tuple[str, str]) -> None:
    assert r.parse_sender(address) == expected


@pytest.mark.parametrize(
    "variants",
    [
        ("SBIBNK", "VKSBIBNK", "VMSBIBNK", "JKSBIBNK", "CPSBIBNK", "VK-SBIBNK", "VM-SBIBNK-S"),
        ("CBSSBI", "VMCBSSBI", "JKCBSSBI", "AXCBSSBI", "AX-CBSSBI", "AX-CBSSBI-T"),
        ("SBIINB", "JXSBIINBS", "JX-SBIINB-S", "SBIINB-S", "SBIINBS"),
    ],
)
def test_hyphen_and_no_hyphen_forms_share_a_core(variants: tuple[str, ...]) -> None:
    assert {r.parse_sender(v)[0] for v in variants} == {variants[0]}


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("AB-ABCDE-P", ("ABCDE", "P")),  # short core + suffix: promo kept
        ("AB-ABCD", ("ABCD", "")),
        ("AB-ABCDEF-S", ("ABCDEF", "S")),
        ("ABABCDEF", ("ABCDEF", "")),  # no hyphen: length rule, unchanged
        ("AB-123456", ("123456", "")),
    ],
)
def test_hyphenated_ids_split_on_hyphens(address: str, expected: tuple[str, str]) -> None:
    assert r.parse_sender(address) == expected


def test_short_core_promo_with_hyphens_is_dropped(tmp_path: Path, capsys) -> None:
    rows = [("AB-ABCDE-P", "Rs 33 promo"), ("AB-ABCDE-T", "Rs 44 debited from A/c XX0001")]
    xml = write_backup(tmp_path / "h.xml", rows)
    args = ["--input", str(xml), "--private-dir", str(tmp_path / "p")]
    out = tmp_path / "out.json"
    assert r.main([*args, "--output", str(out), "--senders", "ABCDE"]) == 0
    assert [m["body"] for m in json.loads(out.read_text(encoding="utf-8"))] == [
        "Rs 44 debited from A/c XX0001"
    ]
    assert re.search(r"promotional \(-P\)\s+1\b", capsys.readouterr().out)


def test_default_allowlist_matches_after_normalisation() -> None:
    allow = {r.parse_sender(s)[0] for s in r.DEFAULT_SENDERS.split(",")}
    assert len(allow) == 14
    for raw in ("VMSBIBNK", "AX-CBSSBI-T", "JXSBIINBS", "JM-HDFCBN", "VKPHONPE"):
        assert r.is_allowlisted(r.parse_sender(raw)[0], allow), raw
    for raw in ("VMZERODHA", "AD-NSEIND", "CP388558", "+919876543210"):
        assert not r.is_allowlisted(r.parse_sender(raw)[0], allow), raw


def test_rcs_ids_are_never_allowlisted() -> None:
    core = r.parse_sender("HDFCBK@RBM.GOOG")[0]
    assert not r.is_allowlisted(core, {core, "HDFCBK"})


def test_promo_dropped_in_both_hyphen_forms(tmp_path: Path, capsys) -> None:
    rows = [
        ("VMHDFCBKP", "Rs 1 promo no hyphen"),
        ("VM-HDFCBK-P", "Rs 2 promo hyphen"),
        ("VMHDFCBKS", "Rs 3 debited from A/c XX1234"),
    ]
    data = run(write_backup(tmp_path / "p.xml", rows), tmp_path / "pd", tmp_path / "out.json")
    assert [m["body"] for m in data] == ["Rs 3 debited from A/c XX1234"]
    assert re.search(r"promotional \(-P\)\s+2\b", capsys.readouterr().out)


def test_otp_detection_keeps_alerts_with_share_warning() -> None:
    assert r.is_otp("123456 is your OTP for txn of Rs 500 at AMAZON")
    assert r.is_otp("Your one-time password is 4321")
    assert not r.is_otp("Rs 500 debited from A/c XX1234. Never share your OTP with anyone.")


# --- Names: default-deny ------------------------------------------------------
def test_unlisted_names_never_appear_in_output(tmp_path: Path) -> None:
    xml = write_backup(tmp_path / "p2p.xml", P2P_ROWS)
    data = run(xml, tmp_path / "private", tmp_path / "out.json")

    text = json.dumps(data).upper()
    assert not [n for n in REAL_NAMES if n in text]
    assert "PARTY_" in text
    bodies = [m["body"] for m in data]
    assert any("To PARTY_" in b and "\nOn 12/11/26" in b for b in bodies)
    assert any(re.search(r"; PARTY_\d{3} credited", b) for b in bodies)


def test_same_name_gets_same_token_across_runs(tmp_path: Path) -> None:
    private = tmp_path / "private"
    first = run(write_backup(tmp_path / "1.xml", P2P_ROWS[:1]), private, tmp_path / "1.json")
    second = run(write_backup(tmp_path / "2.xml", P2P_ROWS[1:2]), private, tmp_path / "2.json")

    token = re.search(r"To (PARTY_\d{3})", first[0]["body"]).group(1)
    assert f"; {token} credited" in second[0]["body"]  # RAHUL KUMAR, new run, same token
    names = json.loads((private / "name_map.json").read_text(encoding="utf-8"))
    assert names["RAHUL KUMAR"] == token


def test_keep_listed_brands_survive(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir()
    (private / "keep_names.txt").write_text("Chai Point  # local favourite\n", encoding="utf-8")
    rows = [
        ("VM-HDFCBK", "Rs 250 debited from A/c XX1234 to SWIGGY via UPI"),
        ("VM-HDFCBK", "Rs 99 spent on HDFC Bank Card XX9876 at Amazon on 2026-11-12"),
        ("VM-HDFCBK", "Paid via UPI to amazon.pay@apl and to CHAI POINT on 12-11-26"),
        ("VM-HDFCBK", "Rs 10 sent via UPI to RAHUL KUMAR"),
    ]
    data = run(write_backup(tmp_path / "k.xml", rows), private, tmp_path / "out.json")
    text = json.dumps(data)

    assert "to SWIGGY via" in text and "at Amazon on" in text and "HDFC Bank Card" in text
    assert "amazon.pay@apl" in text and "to CHAI POINT on" in text
    assert "RAHUL" not in text


# --- Shapes and keys ----------------------------------------------------------
@pytest.fixture
def redactor(tmp_path: Path) -> r.Redactor:
    return r.Redactor(tmp_path / "private")


# --- Bank vocabulary ----------------------------------------------------------
BANK_WORDING = [
    (
        "Spent Rs.33 From HDFC Bank Card x0002 At TEST STORE On 2026-01-01:10:00:00",
        "From HDFC Bank Card x0002 At PARTY_",
    ),
    (
        "Alert:\nINR.33.00 will be debited on 01/01/2026 from HDFC Bank Card 0002 for TEST CO",
        "from HDFC Bank Card 0002 for TEST CO",
    ),
    (
        "Biometric authentication! You have enabled your biometric authentication for "
        "HDFC Bank App.",
        "Biometric authentication! You have enabled your biometric authentication for "
        "HDFC Bank App.",
    ),
    (
        "Rs.33 from your HDFC Bank A/c XX0001 for Money Transfer via HDFC Bank Online Banking.",
        "for Money Transfer via HDFC Bank Online Banking.",
    ),
]


@pytest.mark.parametrize(("body", "kept"), BANK_WORDING)
def test_bank_wording_is_never_pseudonymised(redactor: r.Redactor, body: str, kept: str) -> None:
    assert kept in redactor.redact(body)


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("HDFC Bank Card x", "X"),  # leading bank wording dropped, rest too short
        ("HDFC Bank Debit Card", ""),
        ("TEST STORE HDFC Bank App", "TEST STORE"),  # bank wording ends a name
        ("authentication", ""),
    ],
)
def test_name_key_skips_bank_vocabulary(raw: str, key: str) -> None:
    assert r.name_key(raw) == key


def test_stale_map_entries_for_bank_wording_are_ignored(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir()
    stale = {"HDFC BANK CARD X": "PARTY_001", "AUTHENTICATION": "PARTY_002", "HTTPS": "PARTY_003"}
    (private / "name_map.json").write_text(json.dumps(stale), encoding="utf-8")
    red = r.Redactor(private)

    body = "Biometric authentication! See https://example.invalid/a From HDFC Bank Card x0002"
    out = red.redact(body + " to TEST PAYEE")
    assert out.startswith("Biometric authentication! See https://example.invalid/")
    assert "From HDFC Bank Card x0002" in out
    assert "to PARTY_004" in out  # new token numbers continue after stale ones


# --- Links --------------------------------------------------------------------
def test_link_keeps_scheme_and_host_and_fakes_path(redactor: r.Redactor) -> None:
    link = "https://1.example.bank.in/TESTBK/a/xYz123?u=99"
    out = redactor.redact(f"Act:{link} now")
    fake = re.search(r"Act:(\S+) now", out).group(1)

    assert fake.startswith("https://1.example.bank.in/")
    assert len(fake) == len(link) and fake != link
    assert [c for c in fake if not c.isalnum()] == [c for c in link if not c.isalnum()]
    assert redactor.redact(f"Act:{link} now") == out  # same link, same fake
    assert redactor.redact("Visit www.example.in today") == "Visit www.example.in today"


def test_masked_values_keep_their_shape(redactor: r.Redactor) -> None:
    out = redactor.redact(
        "A/c no. 50100123456789, card 4111 1111 1111 1234, A/c *4321, Acct XX123. "
        "UPI Ref No 612345678901. UTR No. SBIN326317123456. "
        "VPA rahul.k99@okhdfcbank. Call +91 9876543210 or 9876543210@ybl."
    )
    assert "A/c no. XXXXXXXXXX6789" in out
    assert "card XXXX XXXX XXXX 1234" in out
    assert "A/c *4321" in out and "Acct XX123" in out  # bank's own mask kept

    ref = re.search(r"Ref No (\S+)\.", out).group(1)
    assert re.fullmatch(r"\d{12}", ref) and ref != "612345678901"
    utr = re.search(r"UTR No\. (\S+)\.", out).group(1)
    assert re.fullmatch(r"[A-Z]{4}\d{12}", utr) and utr != "SBIN326317123456"

    local = re.search(r"VPA (\S+)@okhdfcbank", out).group(1)  # real handle kept
    assert re.fullmatch(r"[a-z]{5}\.[a-z]\d\d", local) and local != "rahul.k99"

    phone = re.search(r"\+91 (\d+)", out).group(1)
    assert re.fullmatch(r"[6-9]\d{9}", phone) and phone != "9876543210"
    assert f"{phone}@ybl" in out  # same number in a UPI ID gets the same fake


def test_fakes_come_from_a_secret_key_not_a_bare_hash(tmp_path: Path) -> None:
    msg = "UPI Ref No 612345678901"
    a1 = r.Redactor(tmp_path / "a").redact(msg)
    a2 = r.Redactor(tmp_path / "a").redact(msg)
    b = r.Redactor(tmp_path / "b").redact(msg)

    assert a1 == a2  # same key file, same fake
    assert a1 != b  # different random key, different fake
    key = (tmp_path / "a" / "redaction.key").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"[0-9a-f]{64}", key)


# --- Streaming ----------------------------------------------------------------
def test_invalid_char_refs_do_not_break_parsing(tmp_path: Path) -> None:
    xml = write_backup(tmp_path / "emoji.xml", [("VM-HDFCBK", "Paid Rs 5 &#55357;&#56832; &#1;")])
    [(tag, sms)] = list(r.iter_files([xml]))
    c = REPLACEMENT_CHAR
    assert tag == "sms" and sms["body"] == f"Paid Rs 5 {c}{c} {c}"


def test_char_ref_split_across_chunks_is_fixed() -> None:
    class Chunks:
        def __init__(self, parts: list[bytes]) -> None:
            self.parts = parts

        def read(self, n: int) -> bytes:
            return self.parts.pop(0) if self.parts else b""

    cleaner = r.CharRefCleaner(Chunks([b"<a>x &#553", b"57; y</a>"]))
    data = b"".join(iter(lambda: cleaner.read(64), b""))
    assert data == b"<a>x &#65533; y</a>"


def test_streams_20k_messages_with_bounded_memory(tmp_path: Path, capsys) -> None:
    rows = []
    for i in range(20_000):
        if i % 4 == 0:
            rows.append(
                ("VM-HDFCBK-S", f"Rs {i} sent via UPI to RAHUL KUMAR Ref {612000000000 + i}")
            )
        elif i % 4 == 1:
            rows.append(("AD-SBIUPI-P", "Get a pre-approved loan today!"))
        elif i % 4 == 2:
            rows.append(("JD-ICICIT-T", f"{100000 + i} is your OTP. Do not share."))
        else:
            rows.append(("+919876543210", "hey, call me back"))
    xml = write_backup(tmp_path / "big.xml", rows, mms=20)

    tracemalloc.start()
    n = sum(1 for _ in r.iter_files([xml]))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert n == 20_020
    # Measured: streaming ~0.1x file size, iterparse without root.clear() ~0.7x,
    # ET.parse ~4x. So /4 fails both non-streaming versions.
    assert peak < xml.stat().st_size / 4

    data = run(xml, tmp_path / "private", tmp_path / "out.json", "--limit", "50")
    assert len(data) == 50 and {m["sender"] for m in data} == {"HDFCBK"}
    text = json.dumps(data)
    assert "RAHUL" not in text and "612000000000" not in text

    summary = capsys.readouterr().out
    assert "Kept 5,000" in summary
    for reason in (r"promotional \(-P\)", "otp", "sender not allowlisted"):
        assert re.search(rf"{reason}\s+5,000", summary)
    assert re.search(r"mms \(skipped\)\s+20", summary)
    assert re.search(r"names pseudonymised\s+1\b", summary)
    assert re.search(r"names kept \(keep-list\)\s+0\b", summary)


# --- Listing modes ------------------------------------------------------------
def test_list_senders_prints_counts_but_no_bodies_or_numbers(tmp_path: Path, capsys) -> None:
    xml = write_backup(
        tmp_path / "s.xml",
        [
            ("VM-HDFCBK", "secret body one"),
            ("AD-HDFCBK-P", "secret body two"),
            ("VMHDFCBK", "secret body five"),
            ("VM-HDFCBK", "secret body six"),
            ("JD-NEWBNK-T", "secret body three"),
            ("+919876543210", "secret body four"),
        ],
    )
    args = ["--input", str(xml), "--private-dir", str(tmp_path / "p"), "--list-senders"]
    assert r.main([*args, "--senders", "HDFCBK"]) == 0
    out = capsys.readouterr().out
    # MESSAGES PROMO VARIANTS: 4 messages, 1 promo, 3 distinct raw IDs merged.
    assert re.search(r"HDFCBK\s+4\s+1\s+3\s+yes", out)
    assert re.search(r"NEWBNK\s+1\s+0\s+1\s*$", out, re.M)
    assert "secret" not in out and "9876543210" not in out
    assert "1 messages from 1 numbers" in out


def test_list_counterparties_prints_names_and_upi_ids_only(tmp_path: Path, capsys) -> None:
    xml = write_backup(
        tmp_path / "c.xml",
        [
            ("VM-HDFCBK", "Rs 10 sent via UPI to RAHUL KUMAR on 12-11-26. secret one"),
            ("VM-HDFCBK", "Rs 20 sent via UPI to RAHUL KUMAR on 13-11-26. secret two"),
            ("VM-HDFCBK", "Rs 30 paid to SWIGGY via UPI from rahul.k@okaxis secret three"),
        ],
    )
    args = ["--input", str(xml), "--private-dir", str(tmp_path / "p"), "--list-counterparties"]
    assert r.main([*args, "--senders", "HDFCBK"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"\s2\s+RAHUL KUMAR", out)
    assert re.search(r"\s1\s+yes\s+SWIGGY", out)
    assert re.search(r"\s1\s+rahul\.k@okaxis", out)
    assert "secret" not in out.lower() and "Rs 10" not in out
    assert not (tmp_path / "p" / "redaction.key").exists()  # listing writes nothing


# --- Always-redact and --verify ----------------------------------------------
def private_with_always(tmp_path: Path, *entries: str) -> Path:
    private = tmp_path / "private"
    private.mkdir()
    lines = "# own and family names, own phone\n" + "\n".join(entries) + "\n"
    (private / "always_redact.txt").write_text(lines, encoding="utf-8")
    return private


def verify_only(private: Path, out: Path) -> int:
    return r.main(["--private-dir", str(private), "--output", str(out), "--verify"])


def test_always_redact_replaces_names_in_any_position(tmp_path: Path, capsys) -> None:
    private = private_with_always(tmp_path, "Asha", "+91 98765 43210")
    rows = [("VM-HDFCBK", "Rs 33 debited. Thanks Asha, call 98765-43210 now")]
    data = run(write_backup(tmp_path / "a.xml", rows), private, tmp_path / "out.json")

    body = data[0]["body"]
    names = json.loads((private / "name_map.json").read_text(encoding="utf-8"))
    assert f"Thanks {names['ASHA']}, call" in body and "asha" not in body.lower()
    phone = re.search(r"call (\S+) now", body).group(1)
    assert re.fullmatch(r"[6-9]\d{9}", phone) and phone != "9876543210"
    out = capsys.readouterr().out
    assert re.search(r"Always-redact final-pass replacements: [12]$", out, re.M)
    assert "asha" not in out.lower()


def test_clean_run_with_verify_reports_zero_leaks(tmp_path: Path, capsys) -> None:
    private = private_with_always(tmp_path, "Asha")
    rows = [
        ("VM-HDFCBK", "Sent Rs.33 to RAHUL KUMAR via UPI Ref 612345678901 VPA test.user@okaxis"),
        ("VM-HDFCBK", "Dear Asha, Rs 44 credited"),
    ]
    args = ["--input", str(write_backup(tmp_path / "c.xml", rows)), "--private-dir", str(private)]
    out = tmp_path / "out.json"
    assert r.main([*args, "--output", str(out), "--senders", "HDFCBK", "--verify"]) == 0
    printed = capsys.readouterr().out
    assert "Leaks: 0" in printed and "LEAK " not in printed


def test_verify_finds_planted_leaks_and_prints_only_tokens(tmp_path: Path, capsys) -> None:
    private = private_with_always(tmp_path, "Asha")
    rows = [
        ("VM-HDFCBK", "Sent Rs.33 to RAHUL KUMAR via UPI Ref 612345678901 VPA test.user@okaxis"),
        ("VM-HDFCBK", "Rs 44 credited to A/c XX0001"),
        ("VM-HDFCBK", "Rs 55 paid to PRIYA via UPI"),
    ]
    out = tmp_path / "out.json"
    run(write_backup(tmp_path / "p.xml", rows), private, out)
    capsys.readouterr()
    names = json.loads((private / "name_map.json").read_text(encoding="utf-8"))

    data = json.loads(out.read_text(encoding="utf-8"))
    data[1]["body"] += " ashakumar"  # joined word: whole-word redaction cannot catch it
    data[2]["body"] += " Rahul Kumar, ref 612345678901, test.user@okaxis, Priya"
    out.write_text(json.dumps(data), encoding="utf-8")

    assert verify_only(private, out) == 1
    printed = capsys.readouterr().out
    assert f"LEAK {names['ASHA']} in message 2" in printed
    assert f"LEAK {names['RAHUL KUMAR']} in message 3" in printed
    assert "LEAK REFERENCE in message 3" in printed and "LEAK UPI_ID in message 3" in printed
    assert "possible (single word): 1" in printed  # PRIYA is a single-word map entry
    assert "Leaks: 4" in printed
    for real in ("asha", "rahul", "kumar", "priya", "612345678901", "test.user"):
        assert real not in printed.lower()


def test_verify_alone_needs_an_existing_output(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        verify_only(tmp_path / "p", tmp_path / "missing.json")
