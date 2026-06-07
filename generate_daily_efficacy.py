"""
Generate the GREY daily efficacy report.

Schedule this script in Windows Task Scheduler for 3:30 PM with:
python generate_daily_efficacy.py
"""

from __future__ import annotations

import os
import smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

from grey_daily_efficacy_tracker import GreyDailyEfficacyTracker


DEFAULT_SIGNAL_LOG = Path("journals") / "grey" / "phase1_signals.jsonl"
DEFAULT_REPORT_DIR = Path("daily_reports")
DEFAULT_OHLCV_CANDIDATES = (
    Path("nifty_candles.csv"),
    Path("data") / "nifty_candles.csv",
    Path("ohlcv_today.csv"),
    Path("data") / "ohlcv_today.csv",
)


def main() -> None:
    """Load inputs, generate the report, save it, print it, and email if configured."""
    print("Step 1: Loading local .env settings if present...")
    load_dotenv()

    print("Step 2: Resolving signal log and OHLCV input files...")
    signal_log = Path(os.getenv("GREY_EFFICACY_SIGNAL_LOG", str(DEFAULT_SIGNAL_LOG)))
    ohlcv_path = resolve_ohlcv_path()
    report_dir = Path(os.getenv("GREY_EFFICACY_REPORT_DIR", str(DEFAULT_REPORT_DIR)))
    report_date_text = os.getenv("GREY_EFFICACY_REPORT_DATE", "").strip() or None

    print(f"Signal log: {signal_log}")
    print(f"OHLCV file: {ohlcv_path}")
    print(f"Report folder: {report_dir}")

    print("Step 3: Building daily efficacy report...")
    tracker = GreyDailyEfficacyTracker()
    report = tracker.build_report(
        signal_log=signal_log,
        ohlcv_data=ohlcv_path,
        report_date=report_date_text,
        symbol=os.getenv("GREY_EFFICACY_SYMBOL", "NIFTY"),
    )

    print("Step 4: Saving report JSON...")
    output_file = tracker.save_report(report, report_dir)
    print(f"Saved report: {output_file}")

    print("Step 5: Printing readable report...")
    pretty_report = tracker.format_pretty_report(report)
    print(pretty_report)

    print("Step 6: Checking optional email settings...")
    if email_enabled():
        send_email_report(pretty_report, output_file, report.get("report_date", date.today().isoformat()))
    else:
        print("Email is not enabled. Skipping email step.")

    print("Daily efficacy generation complete.")


def resolve_ohlcv_path() -> Path:
    """Find the OHLCV CSV path from env or common local filenames."""
    configured = os.getenv("GREY_EFFICACY_OHLCV_PATH", "").strip()
    if configured:
        return Path(configured)

    for candidate in DEFAULT_OHLCV_CANDIDATES:
        if candidate.exists():
            return candidate

    # Return the default name so the error message is clear inside the report.
    return DEFAULT_OHLCV_CANDIDATES[0]


def email_enabled() -> bool:
    """Return True when the operator enabled email reporting."""
    value = os.getenv("GREY_EFFICACY_EMAIL_ENABLED", "").strip().lower()
    return value in ("1", "true", "yes", "on")


def send_email_report(pretty_report: str, report_file: Path, report_date: str) -> None:
    """Send the report by email when SMTP settings are available."""
    try:
        smtp_host = required_env("GREY_SMTP_HOST")
        smtp_port = int(os.getenv("GREY_SMTP_PORT", "587"))
        smtp_user = os.getenv("GREY_SMTP_USERNAME", "")
        smtp_password = os.getenv("GREY_SMTP_PASSWORD", "")
        email_from = os.getenv("GREY_EMAIL_FROM", smtp_user)
        email_to = required_env("GREY_EMAIL_TO")
        use_tls = os.getenv("GREY_SMTP_TLS", "true").strip().lower() not in ("0", "false", "no")

        message = EmailMessage()
        message["Subject"] = f"GREY Daily Efficacy Report - {report_date}"
        message["From"] = email_from
        message["To"] = email_to
        message.set_content(pretty_report)

        if report_file.exists():
            message.add_attachment(
                report_file.read_bytes(),
                maintype="application",
                subtype="json",
                filename=report_file.name,
            )

        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
            if use_tls:
                smtp.starttls()
            if smtp_user and smtp_password:
                smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)

        print(f"Email sent to {email_to}")
    except Exception as exc:
        print(f"Email step failed safely: {exc}")


def required_env(name: str) -> str:
    """Read a required environment variable for optional email mode."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required email setting: {name}")
    return value


if __name__ == "__main__":
    main()
