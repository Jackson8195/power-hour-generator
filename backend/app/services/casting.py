"""Casting service for discovering and streaming to TV devices.

Supports Chromecast via pychromecast and basic DLNA discovery.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class CastingService:
    """Discover and cast to network media devices."""

    def __init__(self):
        self._chromecasts = []
        self._active_cast = None

    async def discover_devices(self, timeout: int = 5) -> list[dict]:
        """Discover Chromecast and DLNA devices on the local network."""
        devices = []

        # Discover Chromecasts
        try:
            devices.extend(await self._discover_chromecasts(timeout))
        except ImportError:
            logger.warning("pychromecast not installed, skipping Chromecast discovery")
        except Exception as e:
            logger.error(f"Chromecast discovery error: {e}")

        return devices

    async def _discover_chromecasts(self, timeout: int) -> list[dict]:
        """Discover Chromecast devices using pychromecast."""
        import pychromecast

        def _discover():
            services, browser = pychromecast.discovery.discover_chromecasts(
                timeout=timeout
            )
            browser.stop_discovery()
            chromecasts, browser = pychromecast.get_listed_chromecasts(
                friendly_names=[s.friendly_name for s in services]
            )
            browser.stop_discovery()
            return chromecasts

        chromecasts = await asyncio.to_thread(_discover)
        self._chromecasts = chromecasts

        return [
            {
                "id": f"chromecast:{cc.uuid}",
                "name": cc.cast_info.friendly_name,
                "type": "chromecast",
                "model": cc.cast_info.model_name,
            }
            for cc in chromecasts
        ]

    async def cast_video(self, device_id: str, video_url: str, title: str = "Power Hour") -> dict:
        """Cast a video to the specified device."""
        if device_id.startswith("chromecast:"):
            return await self._cast_to_chromecast(device_id, video_url, title)
        else:
            raise ValueError(f"Unknown device type: {device_id}")

    async def _cast_to_chromecast(self, device_id: str, video_url: str, title: str) -> dict:
        """Cast to a Chromecast device."""
        import pychromecast

        uuid = device_id.replace("chromecast:", "")
        cc = next((c for c in self._chromecasts if str(c.uuid) == uuid), None)

        if not cc:
            raise ValueError(f"Chromecast not found: {uuid}")

        def _cast():
            cc.wait()
            mc = cc.media_controller
            mc.play_media(video_url, "video/mp4", title=title)
            mc.block_until_active()
            return {"status": "playing", "device": cc.cast_info.friendly_name}

        return await asyncio.to_thread(_cast)

    async def stop_casting(self) -> dict:
        """Stop the active cast session."""
        if self._active_cast:
            def _stop():
                self._active_cast.quit_app()
            await asyncio.to_thread(_stop)
            self._active_cast = None
        return {"status": "stopped"}


# Singleton instance
casting_service = CastingService()
