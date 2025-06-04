import os
import json
import base64
import logging
import re
from email.utils import parsedate_to_datetime
from datetime import datetime

import ollama
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from tqdm import tqdm

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration Loading ---
def load_config():
    try:
        with open("config.json", 'r') as f:
            config_data = json.load(f)
        logger.setLevel(getattr(logging, config_data.get("log_level", "INFO").upper(), logging.INFO))
        return config_data
    except FileNotFoundError:
        logger.error("CRITICAL ERROR: config.json not found. Please ensure it exists in the script's directory.")
        exit(1)
    except json.JSONDecodeError:
        logger.error("CRITICAL ERROR: config.json is not valid JSON.")
        exit(1)

CONFIG = load_config()

# --- Gmail Authentication ---
def authenticate_gmail():
    creds = None
    if os.path.exists('token.json'):
        try:
            creds = Credentials.from_authorized_user_file('token.json', CONFIG["gmail_scopes"])
        except Exception as e:
            logger.warning(f"Could not load token.json: {e}. A new authorization will be requested.")
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logger.info("Refreshing Gmail access token...")
                creds.refresh(Request())
            except Exception as e:
                logger.warning(f"Token refresh failed: {e}. New authorization is required.")
                if os.path.exists('token.json'):
                    try: os.remove('token.json')
                    except OSError as oe: logger.warning(f"Could not remove old token.json: {oe}")
                creds = None
        if not creds:
            if not os.path.exists('credentials.json'):
                logger.error("CRITICAL ERROR: credentials.json not found. Download it from Google Cloud Console.")
                exit(1)
            logger.info("Starting Gmail authorization flow (a browser window may open)...")
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', CONFIG["gmail_scopes"])
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token_file:
            token_file.write(creds.to_json())
        logger.info("Gmail access token saved to token.json.")
    try:
        service = build('gmail', 'v1', credentials=creds)
        logger.info("Gmail authentication successful.")
        return service
    except Exception as e:
        logger.error(f"CRITICAL ERROR: Could not build Gmail service: {e}")
        exit(1)

# --- Gmail Functions ---
def get_labels(service):
    try:
        results = service.users().labels().list(userId='me').execute()
        return {label['name']: label['id'] for label in results.get('labels', [])}
    except HttpError as error:
        logger.error(f"HTTP error fetching Gmail labels: {error.resp.status} {error.reason}. Content: {error.content}")
        if error.resp.status == 403: logger.error("Error 403: Gmail API might not be enabled or user lacks permissions.")
        exit(1)
    except Exception as e:
        logger.error(f"Generic error fetching Gmail labels: {e}")
        exit(1)

def get_ai_auto_folders(service, all_labels_map):
    ai_folders = {}
    for name, label_id in all_labels_map.items():
        if name.startswith(CONFIG["ai_folder_prefix"]):
            category_name = name[len(CONFIG["ai_folder_prefix"]):]
            ai_folders[category_name] = {"id": label_id, "name": name, "examples": []}
    if not ai_folders: logger.warning(f"No folders found with prefix '{CONFIG['ai_folder_prefix']}'.")
    else: logger.info(f"Found {len(ai_folders)} AI folders: {list(ai_folders.keys())}")
    return ai_folders

def get_email_content(message_data):
    payload = message_data.get('payload', {})
    headers = payload.get('headers', [])
    subject, sender, date_str_header = "", "", ""
    received_datetime_obj = None
    for header in headers:
        name_lower = header['name'].lower()
        if name_lower == 'subject': subject = header['value']
        elif name_lower == 'from': sender = header['value']
        elif name_lower == 'date':
            date_str_header = header['value']
            try: received_datetime_obj = parsedate_to_datetime(date_str_header)
            except Exception as e: logger.debug(f"Could not parse date '{date_str_header}' for email {message_data.get('id', 'N/A')}: {e}")
    formatted_date = received_datetime_obj.strftime('%Y-%m-%d %H:%M:%S %Z') if received_datetime_obj else "Unknown Date"

    body_text_content = ""
    def extract_text_from_part(part_data):
        mime_type = part_data.get('mimeType', '')
        part_body = part_data.get('body', {})
        if 'data' in part_body:
            try:
                decoded_data = base64.urlsafe_b64decode(part_body['data']).decode('utf-8', errors='ignore')
                if mime_type == 'text/plain': return decoded_data, 'plain'
                elif mime_type == 'text/html':
                    html_text = re.sub('<style[^<]*?</style>', ' ', decoded_data, flags=re.IGNORECASE | re.DOTALL)
                    html_text = re.sub('<script[^<]*?</script>', ' ', html_text, flags=re.IGNORECASE | re.DOTALL)
                    html_text = re.sub('<[^<]+?>', ' ', html_text)
                    return html_text, 'html'
            except Exception: pass
        return None, None
    plain_parts, html_parts = [], []
    if 'parts' in payload:
        for part_item in payload['parts']:
            text, type = extract_text_from_part(part_item)
            if text: (plain_parts if type == 'plain' else html_parts).append(text)
            if 'parts' in part_item:
                for sub_part_item in part_item['parts']:
                    sub_text, sub_type = extract_text_from_part(sub_part_item)
                    if sub_text: (plain_parts if sub_type == 'plain' else html_parts).append(sub_text)
    elif 'body' in payload:
        text, type = extract_text_from_part(payload)
        if text: (plain_parts if type == 'plain' else html_parts).append(text)
    body_text_content = "\n".join(plain_parts) if plain_parts else "\n".join(html_parts)
    body_text_content = ' '.join(body_text_content.split())
    max_len = CONFIG.get("max_body_length_for_llm", 1000)

    return {
        "id": message_data.get("id"), "snippet": message_data.get("snippet", ""),
        "subject": subject.strip(), "sender": sender.strip(),
        "body": body_text_content.strip()[:max_len] + ("..." if len(body_text_content.strip()) > max_len else ""),
        "received_date_str": formatted_date, "received_datetime": received_datetime_obj
    }

def fetch_example_emails(service, ai_folders_map):
    logger.info("Fetching example emails for AI folders...")
    for category_name, folder_data in tqdm(ai_folders_map.items(), desc="Example Folders"):
        try:
            results = service.users().messages().list(
                userId='me', labelIds=[folder_data['id']],
                maxResults=CONFIG.get("max_examples_per_folder", 1) # Use configured value
            ).execute()
            messages = results.get('messages', [])
            if not messages: logger.warning(f"No example emails in {folder_data['name']}. Skipped."); continue
            loaded_count = 0
            for msg_meta in messages:
                content = get_email_content(service.users().messages().get(userId='me', id=msg_meta['id'], format='full').execute())
                if content["subject"] or content["body"]:
                    folder_data["examples"].append(content)
                    loaded_count += 1
                    logger.debug(f"Loaded example for '{category_name}': ID {content['id']}, Date: {content['received_date_str']}")
                else: logger.warning(f"Example {msg_meta['id']} in {folder_data['name']} (Date: {content.get('received_date_str', 'N/A')}) has no content.")
            if loaded_count > 0: logger.info(f"Loaded {loaded_count} example(s) for '{category_name}'.")
            else: logger.warning(f"No valid examples from {folder_data['name']}. Ignored.")
        except HttpError as e: logger.error(f"HTTP error fetching examples for {folder_data['name']}: {e.reason}")
        except Exception as e: logger.error(f"Generic error fetching examples for {folder_data['name']}: {e}")
    final_folders = {k: v for k, v in ai_folders_map.items() if v.get("examples")}
    if not final_folders: logger.error("CRITICAL: No AI folders with valid examples loaded. Exiting."); exit(1)
    logger.info(f"Found {len(final_folders)} AI folder(s) with valid examples.")
    return final_folders

# MODIFIED fetch_inbox_emails to exclude already AI-labeled emails
def fetch_inbox_emails(service, all_labels_map, ai_auto_label_ids_to_exclude):
    inbox_label_name_config = CONFIG.get('inbox_label_name', 'INBOX')
    
    inbox_label_id = all_labels_map.get(inbox_label_name_config)
    if not inbox_label_id:
        logger.error(f"CRITICAL: Label '{inbox_label_name_config}' not found in Gmail account. Check config. Exiting.")
        exit(1)

    # Construct the query part to exclude AI_AUTO_ labels
    exclude_labels_query_parts = []
    if ai_auto_label_ids_to_exclude:
        for label_id_to_exclude in ai_auto_label_ids_to_exclude:
            exclude_labels_query_parts.append(f"-label:{label_id_to_exclude}")
    
    base_query = "-in:spam -in:trash"
    full_query_string = f"{base_query} {' '.join(exclude_labels_query_parts)}".strip()

    logger.info(f"Fetching emails from '{inbox_label_name_config}' (max {CONFIG['max_emails_to_scan_inbox']}), using query: '{full_query_string}'")

    try:
        results = service.users().messages().list(
            userId='me',
            labelIds=[inbox_label_id], # Email must have the inbox label
            q=full_query_string,      # And match the query (e.g., not have AI_AUTO labels)
            maxResults=CONFIG["max_emails_to_scan_inbox"]
        ).execute()
        messages_meta = results.get('messages', [])
        
        fetched_emails_content = []
        if not messages_meta:
            logger.info(f"No new emails (matching query criteria) found in '{inbox_label_name_config}'.")
            return fetched_emails_content

        messages_meta.reverse() # Process newest of this batch first
        logger.info(f"Retrieved {len(messages_meta)} email metadata entries from '{inbox_label_name_config}' (matching query). Fetching content...")

        for msg_meta in tqdm(messages_meta, desc=f"Fetching content for '{inbox_label_name_config}'"):
            msg_id = msg_meta['id']
            try:
                msg_data = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
                content = get_email_content(msg_data)
                if content["subject"] or content["body"]:
                    fetched_emails_content.append(content)
                    logger.debug(f"Fetched content: ID {content['id']}, Date: {content['received_date_str']}")
            except HttpError as error:
                logger.warning(f"HTTP error ({error.resp.status}) fetching full email {msg_id}: {error.reason}. Skipped.")
            except Exception as e:
                 logger.warning(f"Generic error fetching full email {msg_id}: {e}. Skipped.")
        
        if fetched_emails_content:
            first_date = fetched_emails_content[0]['received_date_str']
            last_date = fetched_emails_content[-1]['received_date_str']
            logger.info(f"Fetched content for {len(fetched_emails_content)} emails. Batch date range (approx): {first_date} to {last_date}")
        
        return fetched_emails_content
    except HttpError as error:
        logger.error(f"HTTP error ({error.resp.status}) listing emails from '{inbox_label_name_config}': {error.reason}")
        return []
    except Exception as e:
        logger.error(f"Generic error listing emails from '{inbox_label_name_config}': {e}")
        return []

def move_email(service, msg_id, target_label_id, all_labels_map, source_label_name="INBOX"):
    source_id = all_labels_map.get(source_label_name)
    remove_ids = [source_id] if source_id else []
    if not source_id: logger.warning(f"Could not find ID for source label '{source_label_name}' for removal (email {msg_id}).")
    logger.info(f"Moving email {msg_id} from label ID(s) '{remove_ids}' to label ID '{target_label_id}'...")
    try:
        body = {'addLabelIds': [target_label_id]}
        if remove_ids: body['removeLabelIds'] = remove_ids
        service.users().messages().modify(userId='me', id=msg_id, body=body).execute()
        logger.info(f"Email {msg_id} successfully moved to folder ID {target_label_id}.")
        return True
    except HttpError as e: logger.error(f"HTTP error moving email {msg_id}: {e.reason}"); return False
    except Exception as e: logger.error(f"Generic error moving email {msg_id}: {e}"); return False

# --- Ollama Logic ---
def ollama_check_similarity(category_name, example_emails_list, new_email_content):
    try:
        client = ollama.Client(host=CONFIG["ollama_host"])
    except Exception as e:
        logger.error(f"CRITICAL ERROR: Could not connect to Ollama client at {CONFIG['ollama_host']}: {e}")
        return False

    example_texts_formatted = []
    # Use up to max_examples_per_folder from config
    for i, ex_email in enumerate(example_emails_list[:CONFIG.get("max_examples_per_folder", 1)]):
        text = (
            f"Example {i+1}:\n"
            f"  Sender: {ex_email['sender']}\n"
            f"  Subject: {ex_email['subject']}\n"
            f"  Received Date: {ex_email['received_date_str']}\n"
            f"  Body Snippet: {ex_email['snippet']}\n"
            f"  Body (first {CONFIG.get('max_body_length_for_llm', 1000)} chars): {ex_email['body']}\n"
            f"-----------------------------"
        )
        example_texts_formatted.append(text)
    full_examples_text = "\n".join(example_texts_formatted)

    prompt_template_lines = CONFIG.get("similarity_prompt_v3")
    if not prompt_template_lines:
        logger.error("CRITICAL: 'similarity_prompt_v3' not found in config.json.")
        return False
    
    prompt_string = "\n".join(prompt_template_lines)
    max_body_len_val = CONFIG.get('max_body_length_for_llm', 1000) # Renamed for clarity

    full_prompt_for_llm = prompt_string.format(
        category_name=category_name,
        example_emails_formatted_text=full_examples_text,
        new_email_sender=new_email_content['sender'],
        new_email_subject=new_email_content['subject'],
        new_email_date=new_email_content['received_date_str'],
        new_email_snippet=new_email_content['snippet'],
        new_email_body=new_email_content['body'],
        max_body_length_for_llm=max_body_len_val
    )

    logger.debug(f"Sending V3 prompt to Ollama for category '{category_name}', email ID {new_email_content['id']}. Prompt approx length: {len(full_prompt_for_llm)} chars.\nPrompt Start:\n{full_prompt_for_llm[:1000]}...")
    
    try:
        response = client.chat(
            model=CONFIG.get("ollama_model", "qwen:14b"), # Use configured model
            messages=[{'role': 'user', 'content': full_prompt_for_llm}],
            options={"temperature": CONFIG.get("ollama_temperature", 0.1)}
        )
        raw_answer = response['message']['content'].strip()
        logger.debug(f"Ollama ({CONFIG.get('ollama_model')}) RAW response for email ID {new_email_content['id']}:\n'{raw_answer}'")
        
        processed_answer = raw_answer.upper()
        
        if processed_answer == "YES":
            logger.info(f"Ollama classified as YES for email ID {new_email_content['id']}")
            return True
        elif processed_answer == "NO":
            logger.info(f"Ollama classified as NO for email ID {new_email_content['id']}")
            return False
        else:
            if re.search(r'\bYES\b', processed_answer) and not re.search(r'\bNO\b', processed_answer):
                logger.info(f"Ollama classified as YES (fallback regex) for email ID {new_email_content['id']}")
                return True
            if re.search(r'\bNO\b', processed_answer) and not re.search(r'\bYES\b', processed_answer):
                logger.info(f"Ollama classified as NO (fallback regex) for email ID {new_email_content['id']}")
                return False
        logger.warning(f"Ambiguous or non-direct YES/NO response from Ollama: '{raw_answer}'. Defaulting to 'NO' for email ID {new_email_content['id']}.")
        return False

    except ollama.ResponseError as e:
        logger.error(f"Ollama API response error: Status {e.status_code}, Details: {e.error}")
        if e.status_code == 404: logger.error(f"Model '{CONFIG.get('ollama_model')}' not found.")
        return False
    except Exception as e:
        logger.error(f"Generic error with Ollama: {e}")
        return False

# --- Main Logic ---
def main():
    logger.info(f"=== STARTING GMAIL OLLAMA EMAIL FILTERING SCRIPT (Ollama Model: {CONFIG.get('ollama_model', 'N/A')}) ===") # Added model to log
    gmail_service = authenticate_gmail()
    all_labels_map = get_labels(gmail_service)
    
    ai_folders_map_initial = get_ai_auto_folders(gmail_service, all_labels_map) # Renamed for clarity
    ai_folders_with_examples = fetch_example_emails(gmail_service, ai_folders_map_initial)
    
    if not ai_folders_with_examples:
        logger.warning("No AI_AUTO_ folders with valid examples were found or loaded. The script will terminate.")
        return

    # Extract the IDs of AI_AUTO_ folders to be excluded from the inbox fetch query
    ai_auto_label_ids_to_exclude = [folder_data["id"] for folder_data in ai_folders_with_examples.values()]

    inbox_label_name = CONFIG.get('inbox_label_name', 'INBOX')
    # Pass the list of AI_AUTO_ label IDs to exclude
    inbox_emails_list = fetch_inbox_emails(gmail_service, all_labels_map, ai_auto_label_ids_to_exclude) 
    
    if not inbox_emails_list:
        logger.info(f"No new emails (not already in AI_AUTO folders) to process in '{inbox_label_name}'. Exiting.")
        return

    logger.info(f"Processing {len(inbox_emails_list)} email(s) from '{inbox_label_name}' (newest of batch first)...")
    emails_moved_count = 0
    emails_analyzed_count = 0

    for new_email_item in tqdm(inbox_emails_list, desc="Analyzing Inbox Emails"):
        emails_analyzed_count += 1
        logger.info(f"Analyzing email {emails_analyzed_count}/{len(inbox_emails_list)}: ID {new_email_item['id']}, Date: {new_email_item['received_date_str']}, Sender: <{new_email_item['sender']}>, Subject: '{new_email_item['subject'][:40]}...'")
        
        match_found_for_email = False
        for category, folder_meta in ai_folders_with_examples.items():
            logger.debug(f"Checking category: '{category}' for email ID {new_email_item['id']}")
            
            # Optional: Hard-coded sender check for highly specific categories (like newsletters)
            # This can be a pragmatic way to ensure accuracy for certain known senders.
            # Example:
            # if category.upper() == "MEDIUM_DAILY_DIGEST":
            #     sender_email_lower = new_email_item['sender'].lower()
            #     # More robust check for sender domain
            #     # Extracts email from "Display Name <email@domain.com>"
            #     match = re.search(r'<([^>]+)>', sender_email_lower)
            #     actual_sender_address = match.group(1) if match else sender_email_lower
            #
            #     if "medium.com" not in actual_sender_address:
            #         logger.info(f"SENDER MISMATCH (Hard-coded rule): Email ID {new_email_item['id']} from '{new_email_item['sender']}' is not from medium.com. Skipping LLM for '{category}'.")
            #         continue # Skip Ollama call for this category if sender domain doesn't match

            if ollama_check_similarity(category, folder_meta["examples"], new_email_item):
                logger.info(f"MATCH! Email ID {new_email_item['id']} (Sender: <{new_email_item['sender']}>) classified as '{category}'.")
                if move_email(gmail_service, new_email_item['id'], folder_meta["id"], all_labels_map, source_label_name=inbox_label_name):
                    emails_moved_count += 1
                match_found_for_email = True
                break # Email classified, move to next inbox email
        
        if not match_found_for_email:
            logger.info(f"No matching AI_AUTO_ category for email ID {new_email_item['id']} (Sender: <{new_email_item['sender']}>). Remains in '{inbox_label_name}'.")

    logger.info(f"=== PROCESSING COMPLETE ===")
    logger.info(f"Emails analyzed: {emails_analyzed_count}")
    logger.info(f"Emails moved: {emails_moved_count}")

if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        pass # Allow controlled exits
    except Exception as e:
        logger.critical(f"UNHANDLED SCRIPT ERROR: {e}", exc_info=True)