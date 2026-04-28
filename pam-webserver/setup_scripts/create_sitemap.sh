#!/bin/bash

# Run the gen_uuid.sh script and capture its output into SITEMAP_UUID
SITEMAP_UUID=$(./gen_uuid.sh)
if [ $? -ne 0 ]; then
    echo "Error: gen_uuid.sh failed to execute." >&2
    exit 1
fi

# Check if SITEMAP_UUID is not empty
if [ -z "$SITEMAP_UUID" ]; then
    echo "Error: gen_uuid.sh did not produce a valid output." >&2
    exit 1
fi

echo "Generated Sitemap UUID: $SITEMAP_UUID"

# Files to process
ORIGINAL_FILE="sitemap_file"
CONTRACT_FILE="sitemap_file.contract"
CONF_FILE="../start.conf"

# New file names
NEW_FILE="${SITEMAP_UUID}"
NEW_CONTRACT_FILE="${SITEMAP_UUID}.contract"

# Process sitemap_file
if [ -f "$ORIGINAL_FILE" ]; then
    sed -e "s/SITEMAP_UUID/${SITEMAP_UUID}/g" \
        -e "s/YYYY-mm-dd/$(date +'%Y-%m-%d')/g" \
        "$ORIGINAL_FILE" > "$NEW_FILE"
    echo "Updated file written to: $NEW_FILE"
else
    echo "Warning: File '$ORIGINAL_FILE' not found. Skipping."
fi

# Process contract file
if [ -f "$CONTRACT_FILE" ]; then
    sed "s/SITEMAP_UUID/${SITEMAP_UUID}/g" "$CONTRACT_FILE" > "$NEW_CONTRACT_FILE"
    echo "Updated file written to: $NEW_CONTRACT_FILE"
else
    echo "Warning: File '$CONTRACT_FILE' not found. Skipping."
fi

# Process start.conf — ИСПРАВЛЕНО: используем sed -i с бэкапом
if [ -f "$CONF_FILE" ]; then
    sed -i.orig "s/__SITEMAPUUID__/${SITEMAP_UUID}/g" "$CONF_FILE"
    echo "Updated file written to: $CONF_FILE"
    echo "Backup saved to: $CONF_FILE.orig"
else
    echo "Warning: File '$CONF_FILE' not found. Skipping."
fi

echo "All done!"
echo "Now you can move generated files to storage/ and change SITEMAP_UUID in start.conf"
