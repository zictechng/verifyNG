"""
api/management/commands/run_telegram_bot.py

Local development runner for VerifyNG Telegram Bot using long polling (getUpdates).
Allows developers to test the bot locally on localhost without needing ngrok or a public webhook URL.

Usage:
  python manage.py run_telegram_bot
"""

import time
import requests
from django.core.management.base import BaseCommand
from integrations.messaging.telegram_bot import (
    get_bot_token,
    get_bot_username,
    is_telegram_configured,
    handle_telegram_update,
    get_telegram_api_url,
)


class Command(BaseCommand):
    help = "Run the VerifyNG Telegram Bot locally using long polling (no webhook needed for testing)."

    def handle(self, *args, **options):
        if not is_telegram_configured():
            self.stderr.write(
                self.style.ERROR(
                    "\n[ERROR] TELEGRAM_BOT_TOKEN is not configured!\n"
                    "1. Open Telegram and message @BotFather\n"
                    "2. Type /newbot and follow prompts to get your bot token\n"
                    "3. Add TELEGRAM_BOT_TOKEN=your_token to your .env file\n"
                )
            )
            return

        token = get_bot_token()
        username = get_bot_username()

        # Check bot identity with getMe
        try:
            me_resp = requests.get(get_telegram_api_url("getMe"), timeout=10)
            me_data = me_resp.json()
            if not me_data.get("ok"):
                self.stderr.write(self.style.ERROR(f"Telegram API authentication failed: {me_data}"))
                return
            bot_info = me_data["result"]
            bot_name = bot_info.get("first_name", "VerifyNG Bot")
            actual_username = bot_info.get("username", username)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Could not connect to Telegram API: {exc}"))
            return

        # Delete any active webhook so long polling can receive updates
        try:
            requests.post(get_telegram_api_url("deleteWebhook"), timeout=10)
        except Exception:
            pass

        self.stdout.write(self.style.SUCCESS(f"\n=================================================="))
        self.stdout.write(self.style.SUCCESS(f" [OK] VerifyNG Telegram Bot Online: {bot_name} (@{actual_username})"))
        self.stdout.write(self.style.SUCCESS(f" [OK] Polling active on localhost. Press Ctrl+C to stop."))
        self.stdout.write(self.style.SUCCESS(f"==================================================\n"))
        self.stdout.write("Ready! Open Telegram, search for your bot, and send /start or /check ...\n")

        offset = 0
        while True:
            try:
                url = get_telegram_api_url("getUpdates")
                params = {"offset": offset, "timeout": 20, "allowed_updates": ["message", "inline_query"]}
                resp = requests.get(url, params=params, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get("result", []):
                        update_id = update["update_id"]
                        offset = update_id + 1
                        
                        # Print activity to console
                        msg = update.get("message", {})
                        from_user = msg.get("from", {}).get("first_name", "User")
                        text = msg.get("text", "")
                        if text:
                            self.stdout.write(f"Received from {from_user}: {text}")
                        elif "inline_query" in update:
                            iq_query = update["inline_query"].get("query", "")
                            self.stdout.write(f"Inline query: {iq_query}")

                        # Route through the unified check engine
                        handle_telegram_update(update)
                time.sleep(0.5)
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("\nStopping Telegram bot polling..."))
                break
            except Exception as exc:
                self.stderr.write(f"Polling error: {exc}")
                time.sleep(3)
