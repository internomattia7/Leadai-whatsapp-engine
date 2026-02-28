import os
import smtplib
import ssl
from email.message import EmailMessage


def send_email(to: str, subject: str, body: str):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    from_name = os.getenv("SMTP_FROM_NAME", "Lead-AI Control")

    if not host or not user or not password:
        raise RuntimeError("SMTP non configurato: controlla SMTP_HOST/SMTP_USER/SMTP_PASS nel .env")

    msg = EmailMessage()
    msg["From"] = f"{from_name} <{user}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    # STARTTLS (porta 587)
    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        smtp.login(user, password)
        smtp.send_message(msg)

