"""
enkidu_github_auth.py — Generate a GitHub installation token for the Enkidu bot.

The Enkidu GitHub App authenticates using a private key (RSA JWT) to get a
short-lived installation access token. This token is used as the git credential
when Enkidu makes autonomous commits (alert_engine, signal_logger, etc.).

Usage:
    python enkidu_github_auth.py          # prints the token
    python enkidu_github_auth.py --config # writes git config for this repo

Requirements:
    pip install PyJWT cryptography requests

Environment variables (add to .env):
    ENKIDU_GITHUB_APP_ID=<your app id>
    ENKIDU_GITHUB_INSTALLATION_ID=<your installation id>
    ENKIDU_GITHUB_PRIVATE_KEY_PATH=C:/Users/benpa/.secrets/enkidu-bot.pem
"""

import os
import sys
import time
import json
import argparse
import subprocess
from pathlib import Path

try:
    import jwt
    import requests
    from dotenv import load_dotenv
except ImportError:
    print("Missing dependencies. Run: pip install PyJWT cryptography requests python-dotenv")
    sys.exit(1)

load_dotenv(Path(__file__).parent / ".env")

APP_ID             = os.environ.get("ENKIDU_GITHUB_APP_ID")
INSTALLATION_ID    = os.environ.get("ENKIDU_GITHUB_INSTALLATION_ID")
PRIVATE_KEY_PATH   = os.environ.get("ENKIDU_GITHUB_PRIVATE_KEY_PATH")

# Commit identity — GitHub renders this as "enkidu-4090[bot]"
# Format: <bot_user_id>+<app_slug>[bot]@users.noreply.github.com
# Note: bot_user_id (276127226) is NOT the App ID — it's the user ID GitHub
# assigns to the bot account. Retrieve with: GET /users/enkidu-4090[bot]
BOT_NAME     = "enkidu-4090[bot]"
BOT_USER_ID  = "276127226"
BOT_SLUG     = "enkidu-4090"


def _bot_email() -> str:
    """Return the noreply email GitHub assigns to this app's bot account."""
    return f"{BOT_USER_ID}+{BOT_SLUG}[bot]@users.noreply.github.com"


def _generate_jwt() -> str:
    """Sign a JWT with the app's private key. Valid for 10 minutes."""
    if not APP_ID:
        raise ValueError("ENKIDU_GITHUB_APP_ID not set in .env")
    if not PRIVATE_KEY_PATH or not Path(PRIVATE_KEY_PATH).exists():
        raise FileNotFoundError(
            f"Private key not found at: {PRIVATE_KEY_PATH}\n"
            "Set ENKIDU_GITHUB_PRIVATE_KEY_PATH in .env"
        )
    private_key = Path(PRIVATE_KEY_PATH).read_text()
    now = int(time.time())
    payload = {
        "iat": now - 60,        # issued 60s ago (clock skew tolerance)
        "exp": now + (10 * 60), # expires in 10 minutes
        "iss": str(APP_ID),
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


def get_installation_token() -> str:
    """Exchange the JWT for a short-lived installation access token."""
    if not INSTALLATION_ID:
        raise ValueError("ENKIDU_GITHUB_INSTALLATION_ID not set in .env")

    app_jwt = _generate_jwt()
    resp = requests.post(
        f"https://api.github.com/app/installations/{INSTALLATION_ID}/access_tokens",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def configure_repo_git(repo_path: str = ".") -> None:
    """
    Write git config for the Enkidu bot identity in the given repo.
    Also stores the credential helper so pushes use the bot token.
    """
    token = get_installation_token()
    email = _bot_email()

    cmds = [
        ["git", "-C", repo_path, "config", "user.name",  BOT_NAME],
        ["git", "-C", repo_path, "config", "user.email", email],
        # Store token as credential for github.com
        ["git", "-C", repo_path, "config",
         "credential.https://github.com.helper", ""],
        ["git", "-C", repo_path, "config",
         "url.https://x-access-token:{token}@github.com/.insteadOf",
         "https://github.com/"],
    ]
    # Replace placeholder with actual token
    cmds[-1][-2] = f"url.https://x-access-token:{token}@github.com/.insteadOf"

    for cmd in cmds:
        subprocess.run(cmd, check=True)

    print(f"Git configured for Enkidu bot:")
    print(f"  user.name  = {BOT_NAME}")
    print(f"  user.email = {email}")
    print(f"  token      = {token[:8]}... (valid ~1 hour)")


def commit_as_enkidu(repo_path: str, message: str, files: list[str] = None) -> None:
    """
    Stage the given files (or all changes if None) and commit as Enkidu bot.
    Generates a fresh token automatically.
    """
    token = get_installation_token()
    email = _bot_email()

    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"]     = BOT_NAME
    env["GIT_AUTHOR_EMAIL"]    = email
    env["GIT_COMMITTER_NAME"]  = BOT_NAME
    env["GIT_COMMITTER_EMAIL"] = email

    if files:
        subprocess.run(["git", "-C", repo_path, "add"] + files, check=True, env=env)
    else:
        subprocess.run(["git", "-C", repo_path, "add", "-A"], check=True, env=env)

    subprocess.run(
        ["git", "-C", repo_path, "commit", "-m", message],
        check=True, env=env
    )

    # Push using token auth
    remote_url = subprocess.check_output(
        ["git", "-C", repo_path, "remote", "get-url", "origin"],
        text=True
    ).strip()
    # Inject token into URL: https://github.com/... → https://x-access-token:TOKEN@github.com/...
    auth_url = remote_url.replace("https://", f"https://x-access-token:{token}@")
    subprocess.run(
        ["git", "-C", repo_path, "push", auth_url, "HEAD"],
        check=True, env=env
    )
    print(f"Committed and pushed as {BOT_NAME} <{email}>")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enkidu GitHub App auth helper")
    parser.add_argument("--token",   action="store_true", help="Print an installation token")
    parser.add_argument("--config",  action="store_true", help="Write git config for this repo")
    parser.add_argument("--email",   action="store_true", help="Print the bot noreply email")
    args = parser.parse_args()

    if args.email:
        print(_bot_email())
    elif args.config:
        configure_repo_git(str(Path(__file__).parent))
    else:
        # Default: print token (useful for scripting)
        token = get_installation_token()
        print(token)
