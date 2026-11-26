"""Send each recipient their certificate by Gmail, with a delay and one retry."""

import csv
import logging
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from dotenv import dotenv_values

logger = logging.getLogger(__name__)

ENV_FILE = Path(__file__).parent / ".env"
# The placeholder values in .env.example, to warn if they were not replaced.
EXAMPLE_ADDRESS = "your.address@gmail.com"
EXAMPLE_PASSWORD = "abcdefghijklmnop"
# Who already received which template, to warn before sending twice.
# It lives in output/, which is never pushed to GitHub.
HISTORY_FILE = Path(__file__).parent / "output" / "sent_history.csv"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465  # SSL port: the connection is encrypted from the start

# Gmail blocks accounts that send too fast, so we wait between emails.
DELAY_BETWEEN_EMAILS_SECONDS = 1.5
WAIT_BEFORE_RETRY_SECONDS = 5


def load_gmail_credentials(env_file=ENV_FILE):
    """Return (address, app password) from .env, or raise ValueError for HR."""
    env_file = Path(env_file)
    if not env_file.exists():
        hint = " A file named .env.txt was found: rename it to exactly .env" if env_file.with_name(".env.txt").exists() else ""
        raise ValueError(
            f"The Gmail settings file was not found. It must be named exactly .env "
            f"(not .env.txt) and be in {env_file.parent}.{hint}"
        )
    # The file is read fresh each time, so a fix to .env works without
    # restarting the app. utf-8-sig ignores the invisible marker that
    # Notepad sometimes adds at the start of a file.
    settings = dotenv_values(env_file, encoding="utf-8-sig")
    address = (settings.get("GMAIL_ADDRESS") or "").strip()
    password = (settings.get("GMAIL_APP_PASSWORD") or "").strip()
    if not address or not password:
        raise ValueError(
            "The .env file was found, but GMAIL_ADDRESS or GMAIL_APP_PASSWORD is "
            "missing or empty. Write them exactly as in .env.example."
        )
    if address == EXAMPLE_ADDRESS or password.replace(" ", "") == EXAMPLE_PASSWORD:
        raise ValueError(
            "The .env file still contains the example values from .env.example. "
            "Replace them with your Gmail address and App Password, then save the file."
        )
    # Google shows App Passwords as 4 groups of 4 letters; the spaces are not part of it.
    return address, password.replace(" ", "")


def personalise(text, name):
    # replace() instead of format(): a stray { or } typed by HR would make
    # format() crash, while replace() only touches {name}.
    return text.replace("{name}", name)


def build_email(sender, person, messages):
    pdf_path = Path(person["pdf_path"])

    email = EmailMessage()
    email["From"] = sender
    email["To"] = person["email"]
    email["Subject"] = personalise(messages["subject"], person["name"])
    email.set_content(personalise(messages["message_template"], person["name"]))
    email.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf", filename=pdf_path.name)
    return email


def check_gmail_login(sender, password):
    """Fail once with a clear message, instead of failing for every recipient."""
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.login(sender, password)
    except smtplib.SMTPAuthenticationError as error:
        logger.error("Gmail refused the login: %s", error)
        raise ValueError(
            "Gmail refused the login. Check GMAIL_ADDRESS and GMAIL_APP_PASSWORD in the .env file. "
            "The password must be an App Password, not your normal Gmail password."
        )
    # SMTPException is itself a kind of OSError in Python, so it must be
    # caught first; otherwise every Gmail answer would look like a network problem.
    except smtplib.SMTPException as error:
        logger.error("Gmail answered with an error: %s", error)
        raise ValueError(f"Gmail answered with an error: {error}")
    except OSError as error:
        logger.error("Could not connect to Gmail: %r", error)
        raise ValueError(
            "Could not reach Gmail. Check the internet connection, or whether an "
            "antivirus or company network blocks sending email. Details are in certificates.log."
        )


def send_one_email(email, sender, password):
    # A fresh connection per email: if Gmail drops the connection during a
    # long batch, only that one email is affected, and the retry reconnects.
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
        server.login(sender, password)
        server.send_message(email)


def send_with_one_retry(email, sender, password):
    """Return None if the email was sent, or the error text if both attempts failed."""
    try:
        send_one_email(email, sender, password)
        return None
    except (smtplib.SMTPException, OSError) as error:
        logger.warning("First attempt to %s failed: %s", email["To"], error)

    time.sleep(WAIT_BEFORE_RETRY_SECONDS)
    try:
        send_one_email(email, sender, password)
        return None
    except (smtplib.SMTPException, OSError) as error:
        logger.error("Retry to %s failed: %s", email["To"], error)
        return str(error)


def record_sent(person, template_key, history_file=HISTORY_FILE):
    history_file.parent.mkdir(parents=True, exist_ok=True)
    is_new_file = not history_file.exists()
    with history_file.open("a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if is_new_file:
            writer.writerow(["sent_at", "template_key", "email", "name"])
        writer.writerow([datetime.now().isoformat(timespec="seconds"), template_key, person["email"], person["name"]])


def find_already_sent(people, template_key, history_file=HISTORY_FILE):
    """Return the people who already received a certificate for this template."""
    if not history_file.exists():
        return []
    with history_file.open(newline="", encoding="utf-8") as file:
        emails_sent_before = {
            row["email"].lower() for row in csv.DictReader(file) if row["template_key"] == template_key
        }
    return [person for person in people if person["email"].lower() in emails_sent_before]


def send_certificates(generated_people, messages, template_key, dry_run=False, env_file=ENV_FILE, history_file=HISTORY_FILE):
    """Email each person their PDF. Returns (sent, failed).

    In a dry run every email is prepared (so missing PDFs are still caught)
    but nothing is sent and Gmail is not contacted.
    """
    if dry_run:
        sender, password = "dry-run", None
    else:
        sender, password = load_gmail_credentials(env_file)
        check_gmail_login(sender, password)

    sent = []
    failed = []
    for number, person in enumerate(generated_people):
        try:
            email = build_email(sender, person, messages)
        except OSError as error:
            failed.append({**person, "reason": f"Certificate file missing: {error}"})
            continue

        if dry_run:
            logger.info("Dry run: email prepared for %s", person["email"])
            sent.append(person)
            continue

        if number > 0:
            time.sleep(DELAY_BETWEEN_EMAILS_SECONDS)
        error_text = send_with_one_retry(email, sender, password)
        if error_text:
            failed.append({**person, "reason": f"Email not sent: {error_text}"})
            continue
        logger.info("Email sent to %s", person["email"])
        # Recorded right away, so the history is correct even if the app
        # is closed in the middle of a batch.
        record_sent(person, template_key, history_file)
        sent.append(person)

    outcome = "prepared (dry run, nothing sent)" if dry_run else "sent"
    logger.info("Batch finished: %d %s, %d failed", len(sent), outcome, len(failed))
    return sent, failed
