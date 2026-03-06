"""Multi-channel notification system for Local-System.

Delivers notifications (text, images, events) to multiple destinations:
- Redis event bus (inter-service, real-time)
- Telegram bot (push to phone)
- In-app WebSocket (UI at :3001)
- File copy to DESK shared folder

Usage:
    notifier = Notifier()
    await notifier.init()

    # Text notification
    await notifier.notify("Pipeline complete", "Generated 6 images for test-person")

    # Image notification
    await notifier.notify_image(
        "/mnt/vault/data/gen-output/test-person/auto_00_flux_00001_.png",
        caption="Auto-generated portrait"
    )
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from local_system.config import get_settings

logger = logging.getLogger("local_system.notifications")

# Telegram config — set these in .env
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# DESK shared folder for pushed content (SMB/NFS)
DESK_SHARE_PATH = os.environ.get(
    "DESK_SHARE_PATH", "/mnt/vault/data/desk-notifications"
)

# Discord webhook for optional posting
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# ntfy — self-hosted push notifications (no account needed)
NTFY_URL = os.environ.get("NTFY_URL", "http://192.168.1.203:8880")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "athanor")


class NotificationChannel:
    """Base class for notification channels."""

    name: str = "base"

    async def send_text(self, title: str, body: str) -> bool:
        raise NotImplementedError

    async def send_image(
        self, image_path: str, caption: str = ""
    ) -> bool:
        raise NotImplementedError

    async def close(self) -> None:
        pass


class TelegramChannel(NotificationChannel):
    """Push notifications via Telegram Bot API.

    Setup:
    1. Message @BotFather on Telegram → /newbot → get token
    2. Message your bot, then GET https://api.telegram.org/bot{token}/getUpdates
    3. Find your chat_id in the response
    4. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
    """

    name = "telegram"

    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._client = httpx.AsyncClient(timeout=30.0)

    async def send_text(self, title: str, body: str) -> bool:
        if not self._token or not self._chat_id:
            return False
        try:
            resp = await self._client.post(
                f"{self._base_url}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": f"*{title}*\n{body}",
                    "parse_mode": "Markdown",
                },
            )
            return resp.status_code == 200
        except Exception as e:
            logger.warning("Telegram text failed: %s", e)
            return False

    async def send_image(
        self, image_path: str, caption: str = ""
    ) -> bool:
        if not self._token or not self._chat_id:
            return False
        try:
            path = Path(image_path)
            if not path.exists():
                logger.warning("Image not found: %s", image_path)
                return False

            with open(path, "rb") as f:
                resp = await self._client.post(
                    f"{self._base_url}/sendPhoto",
                    data={
                        "chat_id": self._chat_id,
                        "caption": caption[:1024],
                    },
                    files={"photo": (path.name, f, "image/png")},
                )
            return resp.status_code == 200
        except Exception as e:
            logger.warning("Telegram image failed: %s", e)
            return False

    async def close(self) -> None:
        await self._client.aclose()


class DiscordChannel(NotificationChannel):
    """Post via Discord webhook — zero setup, just paste webhook URL."""

    name = "discord"

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url
        self._client = httpx.AsyncClient(timeout=30.0)

    async def send_text(self, title: str, body: str) -> bool:
        if not self._webhook_url:
            return False
        try:
            resp = await self._client.post(
                self._webhook_url,
                json={"content": f"**{title}**\n{body}"},
            )
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.warning("Discord text failed: %s", e)
            return False

    async def send_image(
        self, image_path: str, caption: str = ""
    ) -> bool:
        if not self._webhook_url:
            return False
        try:
            path = Path(image_path)
            if not path.exists():
                return False

            with open(path, "rb") as f:
                resp = await self._client.post(
                    self._webhook_url,
                    data={"content": caption[:2000]},
                    files={"file": (path.name, f, "image/png")},
                )
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.warning("Discord image failed: %s", e)
            return False

    async def close(self) -> None:
        await self._client.aclose()


class NtfyChannel(NotificationChannel):
    """Push notifications via ntfy — self-hosted, no account needed.

    Setup:
    1. Deploy ntfy container on VAULT: docker run -p 8880:80 binwiederhier/ntfy serve
    2. Install ntfy app on phone (Android/iOS)
    3. Subscribe to topic (default: "athanor") at http://192.168.1.203:8880/athanor
    4. Images delivered inline with click-to-view in the notification

    Gateway gallery link is included so user can browse all generated content.
    """

    name = "ntfy"

    def __init__(self, server_url: str, topic: str, gateway_url: str = "") -> None:
        self._server_url = server_url.rstrip("/")
        self._topic = topic
        self._gateway_url = gateway_url or "http://192.168.1.189:8700"
        self._client = httpx.AsyncClient(timeout=30.0)

    async def send_text(self, title: str, body: str) -> bool:
        try:
            # Use JSON publish format to support UTF-8 (emojis in titles)
            resp = await self._client.post(
                self._server_url,
                json={
                    "topic": self._topic,
                    "title": title,
                    "message": body,
                    "tags": ["art", "robot"],
                    "click": f"{self._gateway_url}/gallery",
                    "priority": 3,
                },
            )
            return resp.status_code == 200
        except Exception as e:
            logger.warning("ntfy text failed: %s", e)
            return False

    async def send_image(
        self, image_path: str, caption: str = ""
    ) -> bool:
        try:
            path = Path(image_path)
            if not path.exists():
                logger.warning("ntfy: image not found: %s", image_path)
                return False

            # ntfy supports image attachments via PUT with file
            # Headers must be ASCII-safe, so strip non-ASCII from title
            safe_title = (caption or path.stem).encode("ascii", errors="ignore").decode("ascii") or path.stem
            with open(path, "rb") as f:
                resp = await self._client.put(
                    f"{self._server_url}/{self._topic}",
                    content=f.read(),
                    headers={
                        "Title": safe_title,
                        "Filename": path.name,
                        "Priority": "default",
                        "Tags": "framed_picture",
                        "Click": f"{self._gateway_url}/gallery",
                    },
                )
            return resp.status_code == 200
        except Exception as e:
            logger.warning("ntfy image failed: %s", e)
            return False

    async def close(self) -> None:
        await self._client.aclose()


class EventBusChannel(NotificationChannel):
    """Publish to Redis event bus for in-app real-time updates."""

    name = "event_bus"

    def __init__(self) -> None:
        self._bus = None

    async def init(self) -> None:
        from local_system.events import EventBus

        self._bus = EventBus(service_name="notifications")
        await self._bus.init()

    async def send_text(self, title: str, body: str) -> bool:
        if not self._bus or not self._bus.ready:
            return False
        await self._bus.publish(
            "notification.text",
            "notification",
            {"title": title, "body": body},
        )
        return True

    async def send_image(
        self, image_path: str, caption: str = ""
    ) -> bool:
        if not self._bus or not self._bus.ready:
            return False
        await self._bus.publish(
            "notification.image",
            "image_generated",
            {"path": image_path, "caption": caption},
        )
        return True

    async def close(self) -> None:
        if self._bus:
            await self._bus.close()


class FileShareChannel(NotificationChannel):
    """Copy files to a shared folder accessible by DESK/phone.

    Uses the VAULT NFS share which is mounted on all nodes.
    DESK can access via SMB: \\\\192.168.1.203\\data\\desk-notifications
    """

    name = "file_share"

    def __init__(self, share_path: str) -> None:
        self._share_path = Path(share_path)

    async def send_text(self, title: str, body: str) -> bool:
        # Write text notifications to a log file
        try:
            self._share_path.mkdir(parents=True, exist_ok=True)
            log_file = self._share_path / "notifications.log"
            with open(log_file, "a") as f:
                f.write(f"[{title}] {body}\n")
            return True
        except Exception as e:
            logger.warning("File share text failed: %s", e)
            return False

    async def send_image(
        self, image_path: str, caption: str = ""
    ) -> bool:
        import shutil

        try:
            src = Path(image_path)
            if not src.exists():
                return False

            dest_dir = self._share_path / "images"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src.name
            shutil.copy2(str(src), str(dest))
            logger.info("Copied %s → %s", src.name, dest)
            return True
        except Exception as e:
            logger.warning("File share image failed: %s", e)
            return False


class Notifier:
    """Unified notification dispatcher — sends to all configured channels."""

    def __init__(self) -> None:
        self._channels: list[NotificationChannel] = []

    async def init(self) -> None:
        """Initialize all configured notification channels."""

        # Always add event bus (for in-app real-time)
        bus_ch = EventBusChannel()
        try:
            await bus_ch.init()
            self._channels.append(bus_ch)
            logger.info("Notification channel: event_bus ✓")
        except Exception as e:
            logger.warning("Event bus channel init failed: %s", e)

        # Telegram (if configured)
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            self._channels.append(
                TelegramChannel(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
            )
            logger.info("Notification channel: telegram ✓")

        # Discord (if configured)
        if DISCORD_WEBHOOK_URL:
            self._channels.append(DiscordChannel(DISCORD_WEBHOOK_URL))
            logger.info("Notification channel: discord ✓")

        # ntfy — self-hosted push notifications (always try if URL is set)
        if NTFY_URL and NTFY_TOPIC:
            self._channels.append(
                NtfyChannel(NTFY_URL, NTFY_TOPIC)
            )
            logger.info("Notification channel: ntfy ✓ (topic=%s)", NTFY_TOPIC)

        # File share (if path exists)
        share_path = Path(DESK_SHARE_PATH)
        try:
            share_path.mkdir(parents=True, exist_ok=True)
            self._channels.append(FileShareChannel(str(share_path)))
            logger.info("Notification channel: file_share ✓")
        except Exception:
            logger.info("File share path not available, skipping")

    async def notify(self, title: str, body: str) -> dict[str, bool]:
        """Send text notification to all channels."""
        results = {}
        for ch in self._channels:
            try:
                results[ch.name] = await ch.send_text(title, body)
            except Exception as e:
                logger.warning("Channel %s failed: %s", ch.name, e)
                results[ch.name] = False
        return results

    async def notify_image(
        self,
        image_path: str,
        caption: str = "",
        *,
        text_channels_only: bool = False,
    ) -> dict[str, bool]:
        """Send image notification to all channels.

        Args:
            image_path: Absolute path to image file.
            caption: Optional caption/description.
            text_channels_only: If True, only send caption as text (no image).
        """
        results = {}
        for ch in self._channels:
            try:
                if text_channels_only:
                    results[ch.name] = await ch.send_text(
                        "🖼️ Image Generated", caption
                    )
                else:
                    results[ch.name] = await ch.send_image(
                        image_path, caption
                    )
            except Exception as e:
                logger.warning("Channel %s image failed: %s", ch.name, e)
                results[ch.name] = False
        return results

    async def notify_batch(
        self,
        title: str,
        image_paths: list[str],
        caption: str = "",
    ) -> dict[str, int]:
        """Send batch of images with a summary notification.

        Sends text summary first, then individual images.
        Returns count of successful sends per channel.
        """
        counts: dict[str, int] = {}

        # Summary text
        summary = f"{title}\n{len(image_paths)} images generated"
        if caption:
            summary += f"\n{caption}"
        await self.notify(title, summary)

        # Individual images
        for path in image_paths:
            results = await self.notify_image(path, caption=Path(path).stem)
            for ch_name, success in results.items():
                if success:
                    counts[ch_name] = counts.get(ch_name, 0) + 1

        return counts

    async def close(self) -> None:
        """Cleanup all channels."""
        for ch in self._channels:
            try:
                await ch.close()
            except Exception:
                pass
