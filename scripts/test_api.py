#!/usr/bin/env python3
import requests
import json

# Load config
with open('scripts/config.json') as f:
    config = json.load(f)

print("Testing connection to Immich API...")
print(f"URL: {config['immich_server_url']}")
print(f"Album ID: {config['album_id']}")

url = f"{config['immich_server_url']}/api/albums/{config['album_id']}"
headers = {
    'x-api-key': config['api_key'],
    'Content-Type': 'application/json'
}

try:
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Status Code: {response.status_code}")

    if response.status_code == 200:
        album = response.json()
        photos = album.get('assets', [])
        print(f"Success! Found {len(photos)} photos in the 'Picture Frame' album.")
        if photos:
            print("\nSample photo:")
            sample = photos[0]
            print(f"  ID: {sample.get('id', 'N/A')}")
            print(f"  Filename: {sample.get('originalFileName', 'N/A')}")
            print(f"  Created: {sample.get('localDateTime', 'N/A')}")
    else:
        print(f"Error response: {response.text}")
except requests.exceptions.ConnectionError as e:
    print(f"Connection failed: {e}")
except Exception as e:
    print(f"Error: {e}")
