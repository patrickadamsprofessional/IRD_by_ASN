#!/bin/bash

# This script installs the IRD Lookup service by creating a symlink
# in the systemd directory and enabling/starting the service.
# It MUST be run with sudo.

set -e # Exit immediately if a command exits with a non-zero status.

# --- Configuration ---
# Assumes the script is located in the project root directory
PROJECT_DIR=$(dirname "$(realpath "$0")")
SERVICE_FILE_NAME="ird_lookup.service"
SOURCE_PATH="${PROJECT_DIR}/${SERVICE_FILE_NAME}"
LINK_PATH="/etc/systemd/system/${SERVICE_FILE_NAME}"
# --- End Configuration ---

# Check if running as root
if [ "$(id -u)" -ne 0 ]; then
  echo "This script requires root privileges. Please run with: sudo bash $0" >&2
  exit 1
fi

# Check if the source service file exists
if [ ! -f "${SOURCE_PATH}" ]; then
  echo "Error: Service file not found at ${SOURCE_PATH}" >&2
  exit 1
fi

echo "+++ Installing IRD Lookup Service +++"

echo "[1/5] Creating symlink: ${LINK_PATH} -> ${SOURCE_PATH}"
# Remove existing link/file at destination, if any, to avoid ln error
rm -f "${LINK_PATH}"
ln -s "${SOURCE_PATH}" "${LINK_PATH}"
echo "      Symlink created."

echo "[2/5] Reloading systemd daemon..."
systemctl daemon-reload
echo "      Systemd daemon reloaded."

echo "[3/5] Enabling service ${SERVICE_FILE_NAME} to start on boot..."
systemctl enable "${SERVICE_FILE_NAME}"
echo "      Service enabled."

# Stop existing service instance if running, ignore error if not running
echo "[4/5] Stopping existing service instance (if any)..."
systemctl stop "${SERVICE_FILE_NAME}" || true
echo "      Attempted stop."

echo "[5/5] Starting service ${SERVICE_FILE_NAME}..."
systemctl start "${SERVICE_FILE_NAME}"
echo "      Service start command issued."

echo "--- Installation Attempt Complete ---"
echo "Run 'sudo systemctl status ${SERVICE_FILE_NAME}' to check the status." 