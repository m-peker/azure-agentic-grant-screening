from grant_screening.intake import pii
from grant_screening.intake.pii import Pseudonymizer, build_pseudonymizer, regex_entities

BLOCK = (
    "Ad Soyad: Dr. Elif Arslan\nT.C. Kimlik No: 00000000146\nORCID: 0000-0000-0000-0147\n"
    "Kurum: Karadeniz Kıyı Bilimleri Enstitüsü (kurgusal)\nE-posta: elif.arslan@kkbe.example\n"
    "Telefon: 0 (000) 000 01 47"
)
TEXTS = ["Başvuru No: MGA-2026-0147", *BLOCK.splitlines(), "Ön Onay No: ON-2025-031"]


def test_regex_detects_fixed_formats():
    labels = {label for label, _ in regex_entities(BLOCK)}
    assert {"KIMLIK", "ORCID", "EPOSTA", "TELEFON"} <= labels


def test_language_false_positives_on_business_ids_are_rejected(monkeypatch):
    # Real behaviour seen on 2026-10-01: Language tagged these as phone numbers.
    monkeypatch.setattr(pii, "language_entities", lambda texts: [
        ("KISI", "Elif Arslan"), ("TELEFON", "2026-0147"), ("TELEFON", "0000-0000-0000"),
    ])
    ps = build_pseudonymizer(BLOCK, TEXTS)
    values = set(ps.mapping.values())
    assert "2026-0147" not in values          # fragment of protected application id
    assert "0000-0000-0000" not in values     # fragment of the ORCID already accepted
    assert "Elif Arslan" in values


def test_protected_ids_survive_pseudonymisation(monkeypatch):
    monkeypatch.setattr(pii, "language_entities", lambda texts: [])
    ps = build_pseudonymizer(BLOCK, TEXTS)
    out = ps.apply("\n".join(TEXTS))
    assert "MGA-2026-0147" in out
    assert "ON-2025-031" in out
    assert "00000000146" not in out and "elif.arslan@kkbe.example" not in out


def test_same_value_gets_same_token_and_longest_match_wins():
    ps = Pseudonymizer()
    a = ps.token_for("KISI", "Elif Arslan")
    b = ps.token_for("KISI", "Elif Arslan")
    ps.token_for("KISI", "Dr. Elif Arslan")
    assert a == b == "[KISI_1]"
    assert ps.apply("Dr. Elif Arslan ve Elif Arslan") == "[KISI_2] ve [KISI_1]"
