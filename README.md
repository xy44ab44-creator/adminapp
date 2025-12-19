# Ap - Telegram User Management Bot

A Python Telegram bot that manages user accounts stored in a GitHub JSON file.  
It runs both a web server (for keep‑alive) and a Telegram bot with interactive command menus.  
Accounts are added, listed, searched, renewed, or deleted — all changes are synced back to a GitHub repository.

## Features

- Telegram bot with interactive buttons and menus
- GitHub JSON file backend for user data
- Add users with generated username/password
- List current users with expiry status
- Search users by Device ID or username
- Renew or delete user accounts
- Keep‑alive web server for hosting environments

## Requirements

- Python 3.8+
- Environment variables:
  - `TELEGRAM_TOKEN`: Telegram Bot API token
  - `GITHUB_TOKEN`: GitHub personal access token (with repo access)
  - `GITHUB_REPO`: owner/repo to update JSON file
  - `GITHUB_PATH`: path to JSON file inside the repo
  - `ADMIN_USER_IDS`: comma‑separated allowed admin Telegram IDs

## Setup

1. Clone the repository:
   ```sh
   git clone https://github.com/Nayil1998/Ap.git
   cd Ap
