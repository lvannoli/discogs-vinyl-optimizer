from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from email import policy
import mimetypes
import os
from pathlib import Path
import smtplib
from typing import Mapping, Sequence


DEFAULT_RESULTS_EMAIL = "leonardo.vannoli@gmail.com"


class EmailError(RuntimeError):
    """Raised when a requested results email cannot be sent."""


@dataclass(frozen=True)
class EmailSettings:
    host: str
    port: int
    sender: str
    username: str | None = None
    password: str | None = None
    use_starttls: bool = True


def load_email_settings(env: Mapping[str, str] | None = None) -> EmailSettings:
    values = env if env is not None else os.environ
    host = values.get("SMTP_HOST", "").strip()
    sender = values.get("SMTP_FROM", "").strip()
    username = values.get("SMTP_USERNAME", "").strip() or None
    password = values.get("SMTP_PASSWORD", "").strip() or None
    port_text = values.get("SMTP_PORT", "587").strip()
    starttls_text = values.get("SMTP_STARTTLS", "true").strip().lower()

    missing = []
    if not host:
        missing.append("SMTP_HOST")
    if not sender:
        missing.append("SMTP_FROM")
    if username and not password:
        missing.append("SMTP_PASSWORD")
    if password and not username:
        missing.append("SMTP_USERNAME")
    if missing:
        raise EmailError(
            "Email sending requested but missing environment variable(s): "
            + ", ".join(missing)
        )

    try:
        port = int(port_text)
    except ValueError as exc:
        raise EmailError("SMTP_PORT must be an integer.") from exc

    return EmailSettings(
        host=host,
        port=port,
        sender=sender,
        username=username,
        password=password,
        use_starttls=starttls_text not in {"0", "false", "no", "off"},
    )


def build_results_message(
    *,
    recipient: str,
    attachments: Sequence[Path],
    run_name: str,
    settings: EmailSettings | None = None,
    sender: str | None = None,
) -> EmailMessage:
    recipient = recipient.strip()
    if not recipient or "@" not in recipient:
        raise EmailError("A valid email recipient is required.")

    message = EmailMessage()
    from_address = settings.sender if settings is not None else sender
    if from_address:
        message["From"] = from_address
    message["To"] = recipient
    message["Subject"] = f"Discogs purchase options - {run_name}"
    message.set_content(
        "Attached are the Discogs vinyl optimizer results for this run:\n"
        "- purchase_options.json\n"
        "- offers_scraped.csv or the generated offers CSV for the selected mode\n"
    )

    for attachment in attachments:
        path = Path(attachment)
        if not path.exists():
            raise EmailError(f"Email attachment not found: {path}")
        content_type, encoding = mimetypes.guess_type(path.name)
        if content_type is None or encoding is not None:
            content_type = "application/octet-stream"
        maintype, subtype = content_type.split("/", 1)
        message.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )
    return message


def write_results_email_draft(
    *,
    recipient: str,
    attachments: Sequence[Path],
    run_dir: Path,
    draft_path: Path | None = None,
    sender: str | None = None,
) -> Path:
    run_path = Path(run_dir)
    output_path = Path(draft_path) if draft_path is not None else run_path / "discogs_results_email.eml"
    message = build_results_message(
        recipient=recipient,
        attachments=attachments,
        run_name=run_path.name,
        sender=sender or os.environ.get("SMTP_FROM"),
    )
    output_path.write_bytes(message.as_bytes(policy=policy.SMTP))
    return output_path


def send_results_email(
    *,
    recipient: str,
    attachments: Sequence[Path],
    run_dir: Path,
    settings: EmailSettings | None = None,
) -> None:
    email_settings = settings or load_email_settings()
    message = build_results_message(
        recipient=recipient,
        attachments=attachments,
        run_name=Path(run_dir).name,
        settings=email_settings,
    )

    try:
        with smtplib.SMTP(email_settings.host, email_settings.port, timeout=30) as smtp:
            if email_settings.use_starttls:
                smtp.starttls()
            if email_settings.username:
                smtp.login(email_settings.username, email_settings.password or "")
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailError(f"Email send failed: {exc}") from exc
