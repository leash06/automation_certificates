"""Turn an uploaded recipient list (Excel, CSV, Google Form export) into a
clean list of recipients, plus the rows that were skipped and why."""

import io
import re
from pathlib import Path

import pandas as pd
from email_validator import EmailNotValidError, validate_email

# Headers are compared after simplify_header(), so "Full name", "full_name"
# and "FULL-NAME" all become "fullname".
NAME_HEADERS = {"name", "fullname", "nom", "nomcomplet", "nometprénom", "prénometnom"}
EMAIL_HEADERS = {"email", "emailaddress", "mail", "adresseemail", "adressemail", "courriel"}
STATUS_HEADERS = {"status", "statut", "type", "category", "catégorie"}
WINNER_VALUES = {"winner", "gagnant", "gagnante"}


def read_people_table(file_name, file_bytes):
    """Return the file as a table of text, or raise ValueError with a message for HR."""
    extension = Path(file_name).suffix.lower()
    if extension == ".xlsx":
        table = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    elif extension == ".csv":
        table = read_csv(file_bytes)
    else:
        raise ValueError(
            f"'{file_name}' is not a supported list. "
            "Please upload an Excel (.xlsx) or CSV file."
        )

    # Spreadsheets often contain fully empty rows at the end; they are not
    # recipients, so we drop them instead of reporting them as errors.
    table = table.dropna(how="all").fillna("")
    if table.empty:
        raise ValueError(f"'{file_name}' has no recipients in it.")
    return table


def read_csv(file_bytes):
    # sep=None lets pandas detect the separator: Google Sheets uses commas,
    # but Excel in French uses semicolons.
    try:
        return pd.read_csv(io.BytesIO(file_bytes), sep=None, engine="python", encoding="utf-8-sig", dtype=str)
    except UnicodeDecodeError:
        # Excel on Windows saves CSV in the old Windows encoding, not UTF-8.
        return pd.read_csv(io.BytesIO(file_bytes), sep=None, engine="python", encoding="cp1252", dtype=str)


def simplify_header(header):
    return re.sub(r"[\s\-_.]", "", str(header).lower())


def find_column(columns, known_headers):
    """Return the first column whose header is known, or None so HR can choose."""
    for column in columns:
        if simplify_header(column) in known_headers:
            return column
    return None


def check_email(email):
    """Return the cleaned address, or None if it is not a valid email."""
    try:
        # Deliverability checks ask DNS servers on the internet for each
        # address: slow for a long list and impossible offline.
        return validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError:
        return None


def read_status(row, status_column):
    if status_column is None:
        return "participant"
    if row[status_column].strip().lower() in WINNER_VALUES:
        return "winner"
    return "participant"


def clean_people(table, name_column, email_column, status_column=None):
    """Split the table into valid recipients and rejected rows with a reason.

    One bad row never stops the others: it is recorded and skipped.
    """
    valid_people = []
    rejected_rows = []
    first_row_by_email = {}

    for index, row in table.iterrows():
        # +2 because spreadsheet rows start at 1 and row 1 is the header,
        # so HR can find the row in their own file.
        row_number = index + 2
        name = " ".join(row[name_column].split())
        raw_email = row[email_column].strip()
        email = check_email(raw_email) if raw_email else None

        if not name:
            reason = "Empty name"
        elif not raw_email:
            reason = "Missing email"
        elif email is None:
            reason = "Invalid email"
        elif email.lower() in first_row_by_email:
            reason = f"Duplicate of row {first_row_by_email[email.lower()]}"
        else:
            reason = None

        if reason:
            rejected_rows.append({"row": row_number, "name": name, "email": raw_email, "reason": reason})
            continue

        first_row_by_email[email.lower()] = row_number
        valid_people.append({"name": name, "email": email, "status": read_status(row, status_column)})

    return valid_people, rejected_rows
