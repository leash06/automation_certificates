"""Mailer tests never contact Gmail: a fake SMTP server records what would be sent."""

import smtplib

import pytest

import mailer

MESSAGES = {
    "subject": "Your certificate, {name}",
    "winner_body": "Congratulations {name}! You won.",
    "participant_body": "Thank you {name} for taking part.",
}


class FakeGmail:
    """Stands in for smtplib.SMTP_SSL. failures_left makes the next sends fail."""

    sent_emails = []
    failures_left = 0
    wrong_password = False

    def __init__(self, server, port, timeout):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exception_details):
        return False

    def login(self, address, password):
        if FakeGmail.wrong_password:
            raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")

    def send_message(self, email):
        if FakeGmail.failures_left > 0:
            FakeGmail.failures_left -= 1
            raise smtplib.SMTPServerDisconnected("Connection lost")
        FakeGmail.sent_emails.append(email)


@pytest.fixture(autouse=True)
def fake_gmail(monkeypatch, tmp_path):
    FakeGmail.sent_emails = []
    FakeGmail.failures_left = 0
    FakeGmail.wrong_password = False
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeGmail)
    monkeypatch.setattr(mailer.time, "sleep", lambda seconds: None)  # keep tests fast
    monkeypatch.setenv("GMAIL_ADDRESS", "hr@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")


def make_people(tmp_path, count=2):
    people = []
    for number in range(count):
        pdf_path = tmp_path / f"person_{number}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake certificate")
        status = "winner" if number == 0 else "participant"
        people.append({"name": f"Person {number}", "email": f"p{number}@example.com", "status": status, "pdf_path": str(pdf_path)})
    return people


def test_each_person_gets_personal_message_and_own_pdf(tmp_path):
    sent, failed = mailer.send_certificates(make_people(tmp_path), MESSAGES, env_file=tmp_path / ".env")
    assert len(sent) == 2 and failed == []

    winner_email, participant_email = FakeGmail.sent_emails
    assert winner_email["To"] == "p0@example.com"
    assert winner_email["Subject"] == "Your certificate, Person 0"
    assert "Congratulations Person 0! You won." in winner_email.get_body().get_content()
    assert "Thank you Person 1" in participant_email.get_body().get_content()
    attachment = next(participant_email.iter_attachments())
    assert attachment.get_filename() == "person_1.pdf"


def test_dry_run_sends_nothing(tmp_path):
    sent, failed = mailer.send_certificates(make_people(tmp_path), MESSAGES, dry_run=True, env_file=tmp_path / ".env")
    assert len(sent) == 2
    assert FakeGmail.sent_emails == []


def test_failed_email_is_retried_once(tmp_path):
    FakeGmail.failures_left = 1
    sent, failed = mailer.send_certificates(make_people(tmp_path, count=1), MESSAGES, env_file=tmp_path / ".env")
    assert len(sent) == 1 and failed == []


def test_email_failing_twice_is_reported_and_batch_continues(tmp_path):
    FakeGmail.failures_left = 2  # first person: first try and retry both fail
    sent, failed = mailer.send_certificates(make_people(tmp_path), MESSAGES, env_file=tmp_path / ".env")
    assert [person["email"] for person in failed] == ["p0@example.com"]
    assert "Email not sent" in failed[0]["reason"]
    assert [person["email"] for person in sent] == ["p1@example.com"]


def test_missing_pdf_is_reported_not_crashing(tmp_path):
    people = make_people(tmp_path)
    people[0]["pdf_path"] = str(tmp_path / "deleted.pdf")
    sent, failed = mailer.send_certificates(people, MESSAGES, env_file=tmp_path / ".env")
    assert "missing" in failed[0]["reason"]
    assert len(sent) == 1


def test_wrong_password_gives_one_clear_message(tmp_path):
    FakeGmail.wrong_password = True
    with pytest.raises(ValueError, match="refused the login"):
        mailer.send_certificates(make_people(tmp_path), MESSAGES, env_file=tmp_path / ".env")


def test_missing_gmail_setup_gives_clear_message(monkeypatch, tmp_path):
    monkeypatch.delenv("GMAIL_ADDRESS")
    with pytest.raises(ValueError, match="not set up"):
        mailer.load_gmail_credentials(tmp_path / ".env")


def test_app_password_spaces_are_removed(tmp_path):
    address, password = mailer.load_gmail_credentials(tmp_path / ".env")
    assert password == "abcdefghijklmnop"


def test_stray_braces_in_message_do_not_crash():
    assert mailer.personalise("Hi {name} :-} {", "Amina") == "Hi Amina :-} {"
