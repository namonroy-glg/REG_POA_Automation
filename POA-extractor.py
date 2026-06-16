# POA-extractor.py: Extract REG POAs and uploads them 
#TODO: fix S3 function names to keep naming conventions consistency across versions  
#4-1-2026: Updated to use base.py for centralized Snowflake, AWS S3, and ForthCRM auth logic
import os
import sys
#import json
#import re
import time
#5-21-2026: Not needed as API key decryption is handled through base.py
#import base64
#import shutil
#import logging
import pandas as pd
import fitz  # PyMuPDF
import shutil
from datetime import datetime
from pathlib import Path


# --- PATH FIX: Allow importing from the root 'clients' folder ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import centralized config
from auth import Config
from utils import download_file_from_url, upload_to_s3, convert_to_base64

# ----------------- Setup Logging -----------------
# Using the centralized logger factory
logger = Config.setup_logging("POA_Main")

# ----------------- Shared Resources -----------------
SESSION = Config.get_session()
S3_CLIENT = Config.get_s3_client()
S3_BUCKET = Config.get("POA_BUCKET", "encs-poas")

# ----------------- Snowflake Logic -----------------

def fetch_data_from_snowflake():
    """Fetches records using centralized Snowflake connection."""
    conn = Config.get_snowflake_connection()
    try:
        query = """
            SELECT ENROLLED_MONTH, ID, ENROLLED_DATE, CONTACT_ID, FILE_NAME, TYPE, POA_EXTRACTED
            FROM DATA_ALPS.AUTOMATIONS.VW_POA_AUTOMATION
            WHERE POA_EXTRACTED IS NULL
            LIMIT 300
            
        """
        with conn.cursor() as cur:
            logger.info("Fetching records from Snowflake...")
            cur.execute(query)
            data = cur.fetchall()
            
        df = pd.DataFrame(data, columns=['ENROLLED_MONTH', 'ID', 'ENROLLED_DATE', 'CONTACT_ID', 'FILE_NAME', 'TYPE', 'POA_EXTRACTED'])
        df['ENROLLED_DATE'] = df['ENROLLED_DATE'].astype(str)
        df['ENROLLED_MONTH'] = df['ENROLLED_MONTH'].astype(str)
        return df
    finally:
        conn.close()

# ----------------- ForthCRM & PDF Handling -----------------

def get_document(contact_id, doc_id, file_type, api_key):
    url = f"https://api.forthcrm.com/v1/contacts/{contact_id}/documents/{doc_id}/{file_type}"
    headers = {"Accept": "application/json", "Api-Key": api_key}
    
    try:
        response = SESSION.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        logger.info(f"Document fetched successfully for contact {contact_id}.") 
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching document {doc_id} for CID {contact_id}: {e}")
        return None

def download_pdf(pdf_url, file_name):
    local_dir = Path('Data/attached_files')
    local_dir.mkdir(parents=True, exist_ok=True)
    #local_path = local_dir / file_name

    try:
        # Route processing through centralized stream-handling downloader function
        return download_file_from_url(pdf_url, file_name, local_dir=local_dir, session=SESSION)
    except Exception as e:
        logger.error(f"Failed to download PDF from {pdf_url}: {e}")
        return None

def extract_page_with_text(pdf_path, text_to_search, output_name, output_dir='Data/attached_files'):
    """Original Logic: Extracts the specific page containing the legal text."""
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, output_name)

    try:
        doc = fitz.open(pdf_path)
        new_doc = fitz.open()
        found = False
        for page_num in range(doc.page_count):
            page = doc.load_page(page_num)
            if text_to_search in page.get_text():
                new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
                new_doc.save(output_path)
                found = True
                break
        new_doc.close()
        doc.close()
        return output_path if found else None
    except Exception as e:
        logger.error(f"PDF processing error: {e}")
        return None

def upload_pdf_to_forthcrm(contact_id, pdf_path, api_key):
    headers = {'Accept': 'application/json', 'Api-Key': api_key}
    
    # Route data extraction processing through shared base64 converter function
    file_content = convert_to_base64(pdf_path)
    
    body = [{
        'file_content': file_content,
        'file_name': os.path.basename(pdf_path),
        'doc_type': '17841',
        'content_type': 'application/pdf'
    }]
    #TODO: 6-8-2026: Add error handling
    response = SESSION.post(
        f'https://api.forthcrm.com/v1/contacts/{contact_id}/documents/upload',
        headers=headers,
        json=body,
        timeout=30
    )
    return response.json()

def update_id_status(contact_id, api_key):
    url = f"https://api.forthcrm.com/v1/contacts/{contact_id}"
    headers = {"Accept": "application/json", "Api-Key": api_key, "Content-Type": "application/json"}
    payload = {"customs": [{"field_id": "753179", "value": "YES", "label": "POA Extracted"}]}
    
    response = SESSION.put(url, headers=headers, json=payload, timeout=15)
    return response.status_code == 200

# ----------------- S3 Operations -----------------

def upload_pdf_to_s3(file_path, file_name):
    key = Path(file_name).name
    try:
        # Route file migration through unified upload wrapper function with built-in head checks
        return upload_to_s3(S3_CLIENT, S3_BUCKET, file_path, file_name, content_type='application/pdf')
    except Exception as e:
        logger.error(f"S3 Upload failed for {key}: {e}")
        return None

# ----------------- Cleanup -----------------

def cleanup_temp_files(attached_dir=None):
    """Deletes the temporary download directory where both downloaded and
    extracted PDFs are stored. Called unconditionally at the end of every run."""
    if attached_dir is None:
        attached_dir = os.getenv("TEMP_DIR", "Data/attached_files")

    shutil.rmtree(attached_dir, ignore_errors=True)
    logger.info(f"Cleanup: removed temp directory '{attached_dir}'.")

# ----------------- Process Loops -----------------

def download_and_extract_pdf(res):
    
    #6-1-2026: Removed to add updated function that looks for the alternate POA text in spanish.
    #TODO: Confirm if there's an alternate text in English
    text_eng = "This document is required to be signed because some creditors require it."
    text_spa = "Este documento debe ser firmado ya que alguno acreedores lo solicitan."
    #6-1-2026: Alternate wording found in some contracts.
    text_eng_alt = "This document must be executed as requested by your creditors."
    text_spa_alt = "Este documento debe firmarse porque algunos acreedores lo requieren."

    cid = res['contact_id']
    file_url = res['response']['file_content']
    file_name = res['response']['file_name']

    pdf_path = download_pdf(file_url, file_name)
    if not pdf_path: 
        return None

    output_name = f"{cid}_POA.pdf"
    # Search for English version, fallback to Spanish
    extracted_pdf = extract_page_with_text(pdf_path, text_eng, output_name) or \
                    extract_page_with_text(pdf_path, text_spa, output_name) or \
                    extract_page_with_text(pdf_path, text_eng_alt, output_name) or \
                    extract_page_with_text(pdf_path, text_spa_alt, output_name)
    
    if not extracted_pdf:
        logger.error(f"Text not found in PDF for contact {cid}.")
    
    return extracted_pdf

def upload_and_update_status(cid, extracted_pdf, api_key):
    upload_response = upload_pdf_to_forthcrm(cid, extracted_pdf, api_key)

    if upload_response.get("status", {}).get("code") == 200:
        logger.info(f"POA uploaded for contact {cid}.")
        
        # Mirror to S3
        s3_uri = upload_pdf_to_s3(extracted_pdf, os.path.basename(extracted_pdf))
        if s3_uri: 
            logger.info(f"S3 object for contact {s3_uri}")

        # Final Status Update
        if update_id_status(cid, api_key):
            logger.info(f"Status updated for contact {cid}.")
    else:
        raise Exception(f"Upload failed for contact {cid}: {upload_response}")
#TODO: confirm if both code pieces produce the same result. Add back the logging line for tracing
def process_documents(df, api_key):
    responses = []
    for i, row in enumerate(df.itertuples(index=False)):
        # Rate limiting: 60 requests then 60s sleep
        if i > 0 and i % 60 == 0:
            logger.info("Rate limit reached. Sleeping for 60 seconds...")
            time.sleep(60)

        file_kind = 'uploaded' if row.TYPE == 'UPLOADS' else row.TYPE
        response = get_document(row.CONTACT_ID, row.ID, file_kind, api_key)
        if response:
            response['contact_id'] = row.CONTACT_ID
            responses.append(response)
    return responses

# ----------------- Main -----------------

def main():
    #5-8-2026: Updated logger text to match original wording
    logger.info("Starting POA Extraction Automation")
    
    df = fetch_data_from_snowflake()
    if df.empty:
        logger.info("No new records found. Exiting.")
        return

    # Use centralized auth
    api_key = Config.get_forth_api_key()
    if not api_key:
        logger.error("Failed to obtain Forth CRM API key. Exiting.")
        return

    error_logs = []
    
    # Step 1: Fetch documents from CRM
    responses = process_documents(df, api_key)
    
    # Step 2: Extract pages and upload to CRM/S3
    for i, res in enumerate(responses):
        cid = res['contact_id']
        try:
            '''if i > 0 and i % 60 == 0:
                time.sleep(60)
            '''
            extracted_pdf = download_and_extract_pdf(res)
            if extracted_pdf:
                upload_and_update_status(cid, extracted_pdf, api_key)
            else:
                error_logs.append(f"Text match failed for CID {cid}")

        except Exception as e:
            msg = f"Unexpected error for CID {cid}: {e}"
            logger.error(msg)
            error_logs.append(msg)

    # Error Reporting
    if error_logs:
        error_dir = Path("Data/error")
        error_dir.mkdir(parents=True, exist_ok=True)
        path = error_dir / f"errors_{datetime.now().strftime('%Y%m%d')}.log"
        with open(path, 'w') as f:
            for error in error_logs:
                f.write(f"{error}\n")

    cleanup_temp_files()
    logger.info("Automation Cycle Finished.")

if __name__ == "__main__":
    main()