import os
import json
import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

ABSOLUTE_PATH = os.path.dirname(__file__)
LOCAL_CONFIG = os.path.join(ABSOLUTE_PATH, "config.json")
# Define the required scopes
SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']

def sync_photos():
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.json"): 
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "client_secret.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    print("Successful auth, trying to open local folder")

    with open(LOCAL_CONFIG) as f:
            local_config = json.load(f)
    local_folder = local_config['local_folder']

    try:
        service = build("photoslibrary", "v1", credentials=creds, static_discovery=False)
        search_results = service.mediaItems().search(body={"albumId":local_config['album_id'], 'pageSize':100}).execute()
        if search_results:
            photos = {result['filename']: result['baseUrl'] for result in search_results.get('mediaItems')}
        
        # Check if no photos are returned from Google Photos
        if not photos:
            print("No photos returned from Google Photos. Local folder remains unchanged.")
            return  # Skip updating the local folder if no photos are found
        else:
            print(f"Found {len(photos)} photos.")

        photos_path = os.path.join(os.path.dirname(__file__), local_folder)
        # Download new photos
        for filename, url in photos.items():
            local_path = os.path.join(photos_path, filename)
            if not os.path.exists(local_path):
                response = requests.get(f"{url}=w1280-h720")
                if response.status_code == 200:
                    with open(local_path, 'wb') as file:
                        file.write(response.content)

        # Delete photos not in the album
        for filename in os.listdir(photos_path):
            if filename not in photos:
                os.remove(os.path.join(photos_path, filename))
    except Exception as e:
        print(e)

if __name__ == '__main__':
    sync_photos()
