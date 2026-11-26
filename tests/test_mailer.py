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
    # A test .env in the test's own temporary folder, never the real one.
    # Notepad sometimes adds an invisible marker (a BOM, character number
    # 0xFEFF) at the start of a file; it must not matter.
    invisible_marker = chr(0xFEFF)
    (tmp_path / ".env").write_text(
        invisible_marker + "GMAIL_ADDRESS=hr@example.com\nGMAIL_APP_PASSWORD=wxyz wxyz wxyz wxyz\n", encoding="utf-8"
    )


def make_people(tmp_path, count=2):
    people = []
    for number in range(count):
        pdf_path = tmp_path / f"person_{number}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake certificate")
        status = "winner" if number == 0 else "participant"
        people.append({"name": f"Person {number}", "email": f"p{number}@example.com", "status": status, "pdf_path": str(pdf_path)})
    return people


def send(people, tmp_path, dry_run=False):
    # tmp_path keeps the test's .env and history away from the real ones.
    return mailer.send_certificates(
        people, MESSAGES, "template-a", dry_run=dry_run,
        env_file=tmp_path / ".env", history_file=tmp_path / "history.csv",
    )


def test_each_person_gets_personal_message_and_own_pdf(tmp_path):
    sent, failed = send(make_people(tmp_path), tmp_path)
    assert len(sent) == 2 and failed == []

    winner_email, participant_email = FakeGmail.sent_emails
    assert winner_email["To"] == "p0@example.com"
    assert winner_email["Subject"] == "Your certificate, Person 0"
    assert "Congratulations Person 0! You won." in winner_email.get_body().get_content()
    assert "Thank you Person 1" in participant_email.get_body().get_content()
    attachment = next(participant_email.iter_attachments())
    assert attachment.get_filename() == "person_1.pdf"


def test_dry_run_sends_nothing(tmp_path):
    sent, failed = send(make_people(tmp_path), tmp_path, dry_run=True)
    assert len(sent) == 2
    assert FakeGmail.sent_emails == []


def test_failed_email_is_retried_once(tmp_path):
    FakeGmail.failures_left = 1
    sent, failed = send(make_people(tmp_path, count=1), tmp_path)
    assert len(sent) == 1 and failed == []


def test_email_failing_twice_is_reported_and_batch_continues(tmp_path):
    FakeGmail.failures_left = 2  # first person: first try and retry both fail
    sent, failed = send(make_people(tmp_path), tmp_path)
    assert [person["email"] for person in failed] == ["p0@example.com"]
    assert "Email not sent" in failed[0]["reason"]
    assert [person["email"] for person in sent] == ["p1@example.com"]


def test_missing_pdf_is_reported_not_crashing(tmp_path):
    people = make_people(tmp_path)
    people[0]["pdf_path"] = str(tmp_path / "deleted.pdf")
    sent, failed = send(people, tmp_path)
    assert "missing" in failed[0]["reason"]
    assert len(sent) == 1


def test_wrong_password_gives_one_clear_message(tmp_path):
    FakeGmail.wrong_password = True
    with pytest.raises(ValueError, match="refused the login"):
        send(make_people(tmp_path), tmp_path)


def test_empty_password_gives_clear_message(tmp_path):
    (tmp_path / ".env").write_text("GMAIL_ADDRESS=hr@example.com\nGMAIL_APP_PASSWORD=\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing or empty"):
        mailer.load_gmail_credentials(tmp_path / ".env")


def test_missing_env_file_gives_clear_message(tmp_path):
    (tmp_path / ".env").unlink()
    with pytest.raises(ValueError, match="not found"):
        mailer.load_gmail_credentials(tmp_path / ".env")


def test_env_saved_as_txt_by_notepad_is_pointed_out(tmp_path):
    (tmp_path / ".env").rename(tmp_path / ".env.txt")
    with pytest.raises(ValueError, match="rename it to exactly .env"):
        mailer.load_gmail_credentials(tmp_path / ".env")


def test_app_password_spaces_are_removed(tmp_path):
    address, password = mailer.load_gmail_credentials(tmp_path / ".env")
    assert password == "wxyzwxyzwxyzwxyz"


def test_stray_braces_in_message_do_not_crash():
    assert mailer.personalise("Hi {name} :-} {", "Amina") == "Hi Amina :-} {"


def test_sent_people_are_remembered_per_template(tmp_path):
    people = make_people(tmp_path)
    history_file = tmp_path / "history.csv"
    assert mailer.find_already_sent(people, "template-a", history_file) == []

    send(people[:1], tmp_path)
    assert mailer.find_already_sent(people, "template-a", history_file) == people[:1]
    # The same person with another template is a different certificate.
    assert mailer.find_already_sent(people, "template-b", history_file) == []


def test_dry_run_and_failed_emails_are_not_remembered(tmp_path):
    FakeGmail.failures_left = 2
    send(make_people(tmp_path), tmp_path, dry_run=True)
    send(make_people(tmp_path, count=1), tmp_path)
    assert mailer.find_already_sent(make_people(tmp_path), "template-a", tmp_path / "history.csv") == []


def test_example_values_left_in_env_are_pointed_out(tmp_path):
    (tmp_path / ".env").write_text(
        "GMAIL_ADDRESS=your.address@gmail.com\nGMAIL_APP_PASSWORD=abcd efgh ijkl mnop\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="still contains the example values"):
        mailer.load_gmail_credentials(tmp_path / ".env")


def test_gmail_error_is_not_reported_as_network_problem(monkeypatch, tmp_path):
    def gmail_closes_connection(self, address, password):
        raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

    monkeypatch.setattr(FakeGmail, "login", gmail_closes_connection)
    with pytest.raises(ValueError, match="Gmail answered with an error: Connection unexpectedly closed"):
        send(make_people(tmp_path), tmp_path)


def test_real_network_problem_says_could_not_reach(monkeypatch, tmp_path):
    def no_network(*args, **kwargs):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", no_network)
    with pytest.raises(ValueError, match="Could not reach Gmail"):
        send(make_people(tmp_path), tmp_path)
