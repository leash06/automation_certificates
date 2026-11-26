import io

import pandas as pd
import pytest

from people_loader import (
    EMAIL_HEADERS,
    NAME_HEADERS,
    STATUS_HEADERS,
    clean_people,
    find_column,
    read_people_table,
)

SAMPLE_CSV = """Full name,E-mail,Status
Amina Bello,amina.bello@example.com,winner
Hélène  Muñoz ,helene.munoz@example.com,participant
,no.name@example.com,participant
François Diop,francois.diop@not-an-email,participant
Amina Bello,AMINA.BELLO@example.com,winner
Kofi Mensah,,participant
"""


def load_and_clean(file_name, file_bytes):
    table = read_people_table(file_name, file_bytes)
    name_column = find_column(table.columns, NAME_HEADERS)
    email_column = find_column(table.columns, EMAIL_HEADERS)
    status_column = find_column(table.columns, STATUS_HEADERS)
    return clean_people(table, name_column, email_column, status_column)


def test_valid_rows_are_kept_and_names_tidied():
    valid, rejected = load_and_clean("list.csv", SAMPLE_CSV.encode("utf-8"))
    assert valid == [
        {"name": "Amina Bello", "email": "amina.bello@example.com", "status": "winner"},
        {"name": "Hélène Muñoz", "email": "helene.munoz@example.com", "status": "participant"},
    ]


def test_bad_rows_are_skipped_with_reason_and_row_number():
    valid, rejected = load_and_clean("list.csv", SAMPLE_CSV.encode("utf-8"))
    reasons = {row["row"]: row["reason"] for row in rejected}
    assert reasons == {
        4: "Empty name",
        5: "Invalid email",
        6: "Duplicate of row 2",
        7: "Missing email",
    }


def test_google_form_export_headers_are_detected():
    csv = "Timestamp,Email Address,Name\n2026/11/20,kofi@example.com,Kofi Mensah\n"
    valid, rejected = load_and_clean("form.csv", csv.encode("utf-8"))
    assert valid == [{"name": "Kofi Mensah", "email": "kofi@example.com", "status": "participant"}]


def test_french_excel_csv_with_semicolons_and_windows_encoding():
    csv = "Nom;Adresse e-mail\nHélène Muñoz;helene@example.com\n"
    valid, rejected = load_and_clean("liste.csv", csv.encode("cp1252"))
    assert valid[0]["name"] == "Hélène Muñoz"


def test_excel_file_and_empty_rows_at_the_end():
    table = pd.DataFrame({"Name": ["Amina Bello", None], "Email": ["amina@example.com", None]})
    buffer = io.BytesIO()
    table.to_excel(buffer, index=False)
    valid, rejected = load_and_clean("list.xlsx", buffer.getvalue())
    assert len(valid) == 1
    assert rejected == []


def test_unknown_headers_return_none_so_hr_can_choose():
    assert find_column(["Participant", "Contact"], NAME_HEADERS) is None


def test_other_file_types_are_rejected_with_clear_message():
    with pytest.raises(ValueError, match="Excel"):
        read_people_table("list.pdf", b"anything")


def test_empty_file_is_rejected():
    with pytest.raises(ValueError, match="no recipients"):
        read_people_table("list.csv", b"Name,Email\n")
