#POA-automailer: Gets all extracted POAs and sends them via email to the creditors
#VERY IMPORTANT: This is placeholder code for testing. This isn't meant for Production sue
import smtplib
import ssl
import os
#4-22-2026: added necessary lib to add basic loggging
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

# Import our custom config
from config import Config   

# --- LOGGING CONFIGURATION ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("REG_POA_automation.log"), # Saves to this file
        logging.StreamHandler()                # Also prints to terminal
    ]
)
logger = logging.getLogger(__name__)


def send_automated_report(receiver_email, subject, body, pdf_path):
    # 1. Validate credentials from .env via Config
    try:
        Config.validate()
        #Added to keep record of succesful config access
        logger.info("Configuration validated successfully.")
    except ValueError as e:
        #Check if it creates double prompts
        logger.error(f"Configuration Validation Failed: {e}")
        print(f"Configuration Error: {e}")
        return

    # 2. Build the email headers
    message = MIMEMultipart()
    message["From"] = Config.EMAIL_USER
    message["To"] = receiver_email
    if Config.RECIPIENTS_CC:
        message["Cc"] = ", ".join(Config.RECIPIENTS_CC)
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    # 3. Handle the PDF attachment
    try:
        if not os.path.exists(pdf_path):
            print(f"Error: The file '{pdf_path}' does not exist.")
            return

        with open(pdf_path, "rb") as f:
            attachment = MIMEApplication(f.read(), _subtype="pdf")
            filename = os.path.basename(pdf_path)
            attachment.add_header('Content-Disposition', 'attachment', filename=filename)
            message.attach(attachment)
            logger.info(f"File '{filename}' successfully attached.")
    except Exception as e:
        print(f"Failed to attach file: {e}")
        return

    # 4. Connect and Send
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(Config.SMTP_SERVER, Config.SMTP_PORT, context=context) as server:
            server.login(Config.EMAIL_USER, Config.EMAIL_PASS)
            server.sendmail(Config.EMAIL_USER, receiver_email, message.as_string())
        #Confirm if it adds double logging
        logger.info(f"Success: Email sent to {receiver_email}")  
        print(f"Success: Email sent to {receiver_email} with attachment: {filename}")
    except Exception as e:
        logger.error(f"SMTP Error: {e}")
        print(f" SMTP Error: {e}")

if __name__ == "__main__":
    # This constructs the outbound  email content pulling the values from the .env file
    RECIPIENT = Config.EMAIL_RECIPIENT
    SUBJECT = Config.EMAIL_SUBJECT
    BODY = Config.EMAIL_BODY
    
    #Thins handles what file is going to be attached to the outbound email
    FILE_PATH = Config.ATTACHMENT_FILE_PATH
    
    send_automated_report(RECIPIENT, SUBJECT, BODY, FILE_PATH)