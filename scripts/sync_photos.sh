#!/bin/bash

#rclone sync --progress --verbose 'google drive':'Picture Frame' ~/'Picture Frame'/
#for file in ~/Digital-Photo-Frame/photos/*.HEIC; do heif-convert $file ${file/%.HEIC/.jpg}; done

# ----  CONFIG ---- 
REMOTE="google drive:Picture Frame"
LOCAL="/home/matt/synced_photos"
# ---- ----

echo "Starting sync from $REMOTE to $LOCAL..."

# run rclone in dry-run mode and capture any paths it would transfer or delete
changes=$(rclone sync "$REMOTE" "$LOCAL" --dry-run -v 2>&1)

if echo "$changes" | grep -q "There was nothing to transfer"; then
  echo "No changes detected; skipping sync and post-processing."
elif echo "$changes" | grep -q "Bad Request"; then
  echo "Error trying to sync with google drive, keeping pictures as-is."
  echo "Error message:"
  echo "$changes"
else
  echo "Changes detected:"
  echo "$changes"

  rclone sync "$REMOTE" "$LOCAL"

  echo "Running post-sync operations"
  # clean up existing pictures in picture frame area
  rm -rf /home/matt/Digital-Photo-Frame/photos/*.jpg

  # convert ios pictures to jpg
  for file in $LOCAL/*.HEIC; do heif-convert $file ${file/%.HEIC/.jpg}; done

  # move jpg files to picture frame location
  mv $LOCAL/*.jpg /home/matt/Digital-Photo-Frame/photos/

  echo "Sync and post-processing complete."
fi
