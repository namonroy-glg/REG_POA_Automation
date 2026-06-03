#auth.py: Loads all necesary credentials from the provided .env file
import os
#import sys
import logging
#3-24-2026: added lib to control TTL for Forth CRM key
import time
import boto3 #3-18-2026: Added as necessary import to centralize AWS login
import snowflake.connector #3-23-2026: Added to centralize Snowflake auth and other related operations
#33-24-2026: Added lib to inititiate HTTPS connection for Forth CRM
import requests
from pathlib import Path
from dotenv import load_dotenv
#3-18-2026: Added as necessary import to centralize AWS login
from botocore.config import Config as BotoConfig
#3-24-2026: Added library to initiate HTTP requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
#4-1-2026
from datetime import datetime
# Automatically determine the project root (where the .env usually sits)
# This assumes base.py is inside 'clients/' which is inside the project root.
ROOT_DIR = Path(__file__).resolve().parent

class Config:

    #3-24-2026: Added new variables to handle Forth CRM auth
    _forth_api_key = None
    _forth_key_last_refresh = 0
    _session = None

    @staticmethod
    def initialize():
        """Loads the .env file from the project root."""
        env_path = ROOT_DIR / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
        else:
            logging.warning(f"No .env file found at {env_path}")

    @staticmethod
    def get(key, default=None):
        """Fetches an environment variable."""
        return os.getenv(key, default)
    

    @staticmethod
    def setup_logging(name="app"):
        """Centralized logging configuration for all scripts."""
        log_dir = ROOT_DIR / "Data" / "Logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d")
        log_file = log_dir / f"{name}_{timestamp}.log"

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] (%(name)s): %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        return logging.getLogger(name)
    
    # 3-24-2026: Added to create a centralized Forth CRM auth logic

    @classmethod
    def get_session(cls):
        """Returns a resilient requests session with automatic retries."""
        if cls._session is None:
            cls._session = requests.Session()
            retry_strategy = Retry(
                total=5,
                backoff_factor=1.5,
                status_forcelist=(429, 500, 502, 503, 504)
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            cls._session.mount("https://", adapter)
            cls._session.mount("http://", adapter)
        return cls._session
    
    @classmethod
    def get_forth_api_key(cls, force=False):
        """Handles Forth CRM authentication with built-in TTL caching."""
        now = time.time()
        ttl = int(cls.get("FORTH_KEY_TTL_SECONDS", "3600"))
        
        if not force and cls._forth_api_key and (now - cls._forth_key_last_refresh) < ttl:
            return cls._forth_api_key

        logging.info("[ForthCRM] Refreshing API Key...")
        session = cls.get_session()
        try:
            resp = session.post(
                "https://api.forthcrm.com/v1/auth/token",
                headers={"Accept": "application/json"},
                json={
                    "client_id": cls.get("FORTH_CLIENT_ID"),
                    "client_secret": cls.get("FORTH_CLIENT_SECRET")
                },
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status", {}).get("code") == 200:
                cls._forth_api_key = data["response"]["api_key"]
                cls._forth_key_last_refresh = now
                return cls._forth_api_key
        except Exception as e:
            logging.error(f"[ForthCRM] Auth error: {e}")
        return None

    @staticmethod
    def get_s3_client():
        """Centralized S3 client factory."""
        return boto3.client(
            "s3",
            region_name=Config.get("AWS_REGION", "us-east-1"),
            aws_access_key_id=Config.get("S3_ACCESS_KEY"),
            aws_secret_access_key=Config.get("S3_SECRET_KEY"),
            config=BotoConfig(
                retries={"max_attempts": 5, "mode": "standard"},
                connect_timeout=5,
                read_timeout=60,
            ),
        )

    #3-23-2026: Added updated Snowflake auth method
    @staticmethod
    def get_snowflake_connection():
        """Centralized Snowflake connection factory."""
        try:
            return snowflake.connector.connect(
                user=Config.get('SNOWFLAKE_USER'),
                private_key=Config.get('SNOWFLAKE_PRIVATE_KEY'), # Ensure this is the correct format in .env
                account=Config.get('SNOWFLAKE_ACCOUNT'),
                warehouse=Config.get('SNOWFLAKE_WAREHOUSE'),
                database=Config.get('SNOWFLAKE_DATABASE'),
                schema=Config.get('SNOWFLAKE_SCHEMA')
            )
        except Exception as e:
            logging.error(f"[Snowflake] Connection failed: {e}")
            raise

    #5-26-2026: Added code to centralize Google Authentication
    @staticmethod
    def get_google_credentials(scopes):
        """Centralized Google Credentials factory."""
        from google.oauth2 import service_account
        import json
        google_json_str = Config.get("GOOGLE_CREDENTIALS_JSON")
        if google_json_str:
            creds_info = json.loads(google_json_str)
            return service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
        else:
            service_file = "POA_and_ATC/Credentials/config.json"
            return service_account.Credentials.from_service_account_file(service_file, scopes=scopes)
    


# Initialize immediately when this module is imported
Config.initialize()
