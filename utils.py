# clients/utils.py
#Centralized, shared functions used in all POA and ATC scripts (excluding authentication functions)
import os
import logging
import base64
import time
#5-26-2026: added io library to handle in-memory file operations
import io
from pathlib import Path
from botocore.exceptions import ClientError

logger = logging.getLogger("SharedUtils")

def download_file_from_url(url, file_name, local_dir="Data/attached_files", session=None):
    """
    Downloads a file safely from a given URL using a requests Session.
    
    Parameters:
    - url (str): The file download URL.
    - file_name (str): The target filename to save as.
    - local_dir (str/Path): Local directory where files will be stored.
    - session (requests.Session): Optional resilient session. If None, uses standard requests.
    
    Returns:
    - str: Full path to the downloaded file if successful, None otherwise.
    """
    import requests
    target_dir = Path(local_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    local_path = target_dir / file_name

    try:
        http_client = session if session is not None else requests
        response = http_client.get(url, stream=True, timeout=60)
        response.raise_for_status()
        
        with open(local_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)
        return str(local_path)
    except Exception as e:
        logger.error(f"Failed to download file from {url}: {e}")
        return None

def upload_to_s3(s3_client, bucket, file_path, file_name, content_type="application/pdf", max_retries=3):
    """
    Uploads a local file or file stream to an AWS S3 Bucket with AES256 server-side encryption
    and verifies its presence using head_object.
    
    Parameters:
    - s3_client (boto3.client): The initialized S3 client.
    - bucket (str): S3 Bucket name.
    - file_path (str/Path): Path to the local file.
    - file_name (str): Name of the file target key.
    - content_type (str): MIME type for S3 metadata (e.g., 'application/pdf').
    - max_retries (int): Total retry attempts for transient network issues.
    
    Returns:
    - str: The S3 URI (s3://bucket/key) if successful, None otherwise.
    """
    key = Path(file_name).name
    
    if not os.path.exists(file_path):
        logger.error(f"S3 Upload failed: Local file does not exist at {file_path}")
        return None

    with open(file_path, "rb") as f:
        body = f.read()

    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            s3_client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
            # Verify the file successfully landed in S3
            s3_client.head_object(Bucket=bucket, Key=key)
            s3_uri = f"s3://{bucket}/{key}"
            logger.info(f"S3 upload success: {s3_uri} (attempt {attempt})")
            return s3_uri
        except ClientError as ce:
            last_exc = ce
            logger.warning(f"S3 client error on attempt {attempt} for key={key}: {ce}")
            time.sleep(min(2 ** attempt, 10))
        except Exception as e:
            last_exc = e
            logger.warning(f"Unexpected S3 error on attempt {attempt} for key={key}: {e}")
            time.sleep(min(2 ** attempt, 10))

    logger.error(f"S3 upload completely FAILED after {max_retries} attempts for key={key}: {last_exc}")
    return None

def download_from_s3(s3_client, bucket, key):
    """
    Streams a remote object from an AWS S3 bucket directly into an 
    in-memory BytesIO buffer, avoiding any local disk writes.
    
    Parameters:
    - s3_client: The initialized S3 client instance.
    - bucket (str): S3 Bucket name.
    - key (str): The specific object key/path inside the bucket.
    
    Returns:
    - io.BytesIO: A binary stream positioned at the start, or None if failed.
    """
    stream = io.BytesIO()
    try:
        s3_client.download_fileobj(bucket, key, stream)
        stream.seek(0)
        return stream
    except Exception as e:
        logger.error(f"In-memory S3 download failed for key '{key}': {e}")
        return None

def convert_to_base64(file_path):
    """
    Encodes a local file into a base64 UTF-8 string. Useful for CRM uploads.
    
    Parameters:
    - file_path (str/Path): Path to the file.
    
    Returns:
    - str: Base64 encoded string.
    """
    try:
        with open(file_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to convert file to base64 {file_path}: {e}")
        raise

#5-29-2026: Added to code to centralize Google-related functions

def create_drive_folder(drive_service, folder_name, parent_id):
    """Creates a unified folder within Google Drive under a designated parent tracking link."""
    from googleapiclient.errors import HttpError
    try:
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        folder = drive_service.files().create(
            body=file_metadata, fields='id', supportsAllDrives=True).execute()
        logger.info(f"Created Drive folder '{folder_name}' (ID: {folder.get('id')})")
        return folder.get('id')
    except HttpError as e:
        raise Exception(f"Drive error: {e}")

def upload_pdf_to_drive(drive_service, file_stream, filename, folder_id):
    """Streams binary byte payloads straight up into a verified Google Drive folder location."""
    from googleapiclient.http import MediaIoBaseUpload
    file_metadata = {'name': filename, 'parents': [folder_id]}
    media = MediaIoBaseUpload(file_stream, mimetype='application/pdf', resumable=True)
    uploaded = drive_service.files().create(
        body=file_metadata, media_body=media, fields='id', supportsAllDrives=True).execute()
    logger.info(f"Uploaded '{filename}' to Drive (ID: {uploaded.get('id')})")
    return uploaded.get('id')

def fetch_contacts_and_refs(sheets_service, sheet_id, sheet_name):
    """Fetches operational metrics grid tables and maps column records regardless of variable headers style."""
    import pandas as pd
    result = sheets_service.values().get(spreadsheetId=sheet_id, range=sheet_name).execute()
    values = result.get("values", [])
    if not values:
        logger.warning(f"No data found in sheet '{sheet_name}'.")
        return []
    
    df = pd.DataFrame(values[1:], columns=values[0])
    cid_col = "Contac_id" if "Contac_id" in df.columns else "CONTACT_ID"
    ref_col = "Reference_id" if "Reference_id" in df.columns else "FILENAME"

    pairs = []
    for _, row in df.iterrows():
        contact_id = str(row.get(cid_col, "")).strip()
        reference = str(row.get(ref_col, "")).strip()
        if contact_id:
            pairs.append({"contact_id": contact_id, "reference": reference})
    return pairs

