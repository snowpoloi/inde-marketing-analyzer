"""One-time local consent. Never print tokens; never put the output inside Git."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google_auth_oauthlib.flow import InstalledAppFlow

from app.connectors.supplier_gmail import MAILBOX, READONLY_SCOPE, SupplierGmailReader
from app.core.config import settings


def main():
    parser = argparse.ArgumentParser(description="Authorize only info@inde.gr with gmail.readonly.")
    parser.add_argument("--client", type=Path, required=True, help="Google Desktop client JSON, outside the repository")
    parser.add_argument("--output", type=Path, required=True, help="New private .env file, outside the repository")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    client_path, output = args.client.resolve(), args.output.resolve()
    if client_path.is_relative_to(root) or output.is_relative_to(root) or output.exists() or not output.parent.is_dir():
        raise ValueError("Keep the downloaded client and new output outside this repository; create the private output folder first.")
    config = json.loads(client_path.read_text(encoding="utf-8"))
    installed = config.get("installed", {})
    if installed.get("auth_uri") != "https://accounts.google.com/o/oauth2/auth" or installed.get("token_uri") != "https://oauth2.googleapis.com/token":
        raise ValueError("Use an unmodified Google Desktop OAuth client JSON.")
    flow = InstalledAppFlow.from_client_config(config, [READONLY_SCOPE], autogenerate_code_verifier=True)
    credentials = flow.run_local_server(host="127.0.0.1", port=0, access_type="offline",
        prompt="consent select_account", login_hint=MAILBOX, timeout_seconds=300)
    if not credentials.refresh_token:
        raise ValueError("Google did not issue an offline refresh token. Repeat dedicated read-only consent.")
    settings.supplier_gmail_enabled = True
    settings.supplier_gmail_client_id = installed["client_id"]
    settings.supplier_gmail_client_secret = installed["client_secret"]
    settings.supplier_gmail_refresh_token = credentials.refresh_token
    reader = SupplierGmailReader()
    try:
        reader.authorize()
    finally:
        reader.close()
    values = {"SUPPLIER_GMAIL_ENABLED": "true", "SUPPLIER_GMAIL_CLIENT_ID": installed["client_id"],
        "SUPPLIER_GMAIL_CLIENT_SECRET": installed["client_secret"], "SUPPLIER_GMAIL_REFRESH_TOKEN": credentials.refresh_token}
    if any("\n" in value or "\r" in value for value in values.values()):
        raise ValueError("Invalid credential format.")
    with output.open("x", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")
    output.chmod(0o600)
    print(f"Verified {MAILBOX}, gmail.readonly only. Private credentials written to {output}.")
    print("Enter the four values in Coolify's backend environment. Do not paste them into chat or Git.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Authorization not completed. Check the Desktop client, private paths, info@inde.gr selection and read-only consent; no credentials were printed.", file=sys.stderr)
        sys.exit(1)
