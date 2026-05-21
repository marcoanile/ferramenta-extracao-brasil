#!/usr/bin/env bash
set -e

# Install Tesseract OCR + Portuguese language pack (needed for scanned PDF support)
apt-get update -qq
apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por

pip install -r backend/requirements.txt
