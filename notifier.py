"""Notification module for the Morning Scanner.

Supported channels (in priority order):
  1. Slack Webhook  — set SLACK_WEBHOOK_URL
  2. Email (SMTP)   — set SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / NOTIFY_EMAIL
  3. Local file     — always written to output/ regardless of notification success

Usage (called from scanner.py):
    from notifier import send_notification
    send_notification(report_text, logger)
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_message(message: str, limit: int = 3_900) -> list[str]:
    """Split *message* into chunks ≤ *limit* chars, breaking at line boundaries."""
    if len(message) <= limit:
        return [message]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in message.splitlines(keepends=True):
        line_len = len(line)
        if current and current_len + line_len > limit:
            chunks.append("".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append("".join(current))

    return chunks


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


def send_slack(message: str, webhook_url: str) -> None:
    """Post *message* to a Slack incoming webhook, splitting if needed."""
    chunks = _split_message(message)
    for chunk in chunks:
        resp = requests.post(
            webhook_url,
            json={"text": chunk},
            timeout=15,
        )
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


def send_email(
    subject: str,
    body: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
    recipient: str,
) -> None:
    """Send a plain-text email via SMTP with STARTTLS."""
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def send_notification(
    report: str,
    logger: Optional[logging.Logger] = None,
) -> None:
    """
    Dispatch *report* to the first configured channel.
    Falls back gracefully and logs all errors without raising.
    """
    if logger is None:
        logger = logging.getLogger("scanner")

    # ── Try Slack first ────────────────────────────────────────────────
    slack_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if slack_url:
        try:
            send_slack(report, slack_url)
            logger.info("Slack通知送信完了")
            return
        except Exception as exc:  # noqa: BLE001
            logger.error("[ERROR] Slack通知エラー: %s", exc)
            # Fall through to email

    # ── Try email ─────────────────────────────────────────────────────
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port_str = os.getenv("SMTP_PORT", "587").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASS", "").strip()
    notify_email = os.getenv("NOTIFY_EMAIL", "").strip()

    if smtp_host and smtp_user and smtp_pass and notify_email:
        try:
            smtp_port = int(smtp_port_str)
            # Extract date from report header for the subject line
            subject_date = ""
            for line in report.splitlines():
                if "Morning Scan" in line:
                    subject_date = line.strip()
                    break
            subject = subject_date or "📊 Morning Scan"

            send_email(
                subject=subject,
                body=report,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                smtp_user=smtp_user,
                smtp_pass=smtp_pass,
                recipient=notify_email,
            )
            logger.info("メール通知送信完了 → %s", notify_email)
            return
        except Exception as exc:  # noqa: BLE001
            logger.error("[ERROR] メール通知エラー: %s", exc)

    logger.warning(
        "通知先が設定されていません。"
        "SLACK_WEBHOOK_URL または SMTP_* / NOTIFY_EMAIL を .env に設定してください。"
    )
