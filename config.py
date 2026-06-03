import os
from dotenv import load_dotenv

# Load once
load_dotenv()

class Config:
    EMAIL_USER = os.getenv("EMAIL_USER")
    EMAIL_PASS = os.getenv("EMAIL_PASS")
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = os.getenv("SMTP_PORT")
    EMAIL_BODY = os.getenv("EMAIL_BODY")
    EMAIL_SUBJECT = os.getenv("EMAIL_SUBJECT")
    EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT")
    ATTACHMENT_FILE_PATH = os.getenv("ATTACHMENT_FILE_PATH")

    _cc_raw = os.getenv("RECIPIENTS_CC", "")
    RECIPIENTS_CC = [email.strip() for email in _cc_raw.split(",") if email.strip()]

    @classmethod
    def validate(cls):
        """Ensures all required settings are present."""
        if not cls.EMAIL_USER or not cls.EMAIL_PASS:
            raise ValueError("Missing credentials in .env file!")

# Validate on import
Config.validate()