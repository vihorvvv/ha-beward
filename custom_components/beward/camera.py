"""
Support for viewing the camera feed from a Beward devices.

For more details about this component, please refer to
https://github.com/Limych/ha-beward
"""

#  Copyright (c) 2019-2025, Andrey "Limych" Khrolenok <andrey@khrolenok.ru>
#  Creative Commons BY-NC-SA 4.0 International Public License
#  (see LICENSE.md or https://creativecommons.org/licenses/by-nc-sa/4.0/)
from __future__ import annotations

import datetime
import logging
from asyncio import run_coroutine_threadsafe
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity import Entity
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.typing import ConfigType

    from . import BewardController

import aiohttp
import async_timeout
import beward
from aiohttp import web
from haffmpeg.camera import CameraMjpeg
from homeassistant.components.camera import Camera as CameraEntity
from homeassistant.components.camera import CameraEntityFeature
from homeassistant.components.ffmpeg import DATA_FFMPEG, FFmpegManager
from homeassistant.components.local_file.camera import LocalFile
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.helpers.aiohttp_client import (
    async_aiohttp_proxy_stream,
    async_get_clientsession,
)
from homeassistant.util import dt as dt_util

from .const import (
    CAMERA_LIVE,
    CAMERA_NAME_LIVE,
    CAMERAS,
    CAT_CAMERA,
    CAT_DOORBELL,
    CONF_CAMERAS,
    CONF_FFMPEG_ARGUMENTS,
    DOMAIN,
    DOMAIN_YAML,
)
from .entity import BewardEntity

_LOGGER: Final = logging.getLogger(__name__)

_UPDATE_INTERVAL_LIVE: Final = datetime.timedelta(seconds=1)
_SESSION_TIMEOUT: Final = 10  # seconds


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up a cameras for a Beward device."""
    entities = []

    if entry.source == SOURCE_IMPORT:
        config = hass.data[DOMAIN_YAML]
        for index, device_config in enumerate(config):
            controller = hass.data[DOMAIN][entry.entry_id][index]
            entities.extend(await _async_setup_entities(controller, device_config))

    else:
        config = entry.data.copy()
        config.update(entry.options)
        controller = hass.data[DOMAIN][entry.entry_id][0]
        entities.extend(await _async_setup_entities(controller, config))

    if entities:
        async_add_entities(entities, update_before_add=True)
    return True


async def _async_setup_entities(
    controller: BewardController, config: ConfigType
) -> list[Entity]:
    """Set up entities for device."""
    category = None
    if isinstance(controller.device, beward.BewardDoorbell):
        category = CAT_DOORBELL
    elif isinstance(controller.device, beward.BewardCamera):
        category = CAT_CAMERA

    entities = []
    for camera_type in config.get(CONF_CAMERAS, list(CAMERAS)):
        if category in CAMERAS[camera_type][1]:
            if camera_type == CAMERA_LIVE:
                await controller.hass.async_add_executor_job(
                    controller.device.obtain_uris
                )
                entities.append(BewardLiveCamera(controller, config))

            else:
                entities.append(BewardFileCamera(controller, camera_type))

    return entities


class BewardLiveCamera(BewardEntity, CameraEntity):
    """The camera on a Beward device."""

    def __init__(self, controller: BewardController, config: ConfigType) -> None:
        """Initialize the camera on a Beward device."""
        super().__init__(controller)

        self._url = controller.device.live_image_url
        self._stream_url = controller.device.rtsp_live_video_url
        self._last_image = None
        self._last_update = datetime.datetime.min

        self._ffmpeg_input = "-rtsp_transport tcp -i " + self._stream_url
        self._ffmpeg_arguments = config.get(CONF_FFMPEG_ARGUMENTS)

        self._attr_unique_id = f"{self._controller.unique_id}-live"
        self._attr_name = CAMERA_NAME_LIVE.format(controller.name)

    async def stream_source(self) -> str | None:
        """Return the stream source."""
        return self._stream_url

    @property
    def supported_features(self) -> int | None:
        """Return supported features."""
        if self._stream_url:
            return CameraEntityFeature.STREAM
        return 0

    def camera_image(
        self,
        width: int | None = None,  # noqa: ARG002
        height: int | None = None,  # noqa: ARG002
    ) -> bytes | None:
        """Return camera image."""
        return run_coroutine_threadsafe(
            self.async_camera_image(), self.hass.loop
        ).result()

    async def async_camera_image(
        self,
        width: int | None = None,  # noqa: ARG002
        height: int | None = None,  # noqa: ARG002
    ) -> bytes | None:
        """Pull a still image from the camera."""
        now = dt_util.now()

        if self._last_image and now - self._last_update < _UPDATE_INTERVAL_LIVE:
            return self._last_image

        try:
            websession = async_get_clientsession(self.hass)
            with async_timeout.timeout(_SESSION_TIMEOUT):
                response = await websession.get(self._url)

        except TimeoutError:
            _LOGGER.exception("Camera image timed out")
            return self._last_image

        except aiohttp.ClientError:
            _LOGGER.exception("Error getting camera image")
            return self._last_image

        else:
            self._last_image = await response.read()
            self._last_update = now
            return self._last_image

    async def handle_async_mjpeg_stream(
        self, request: web.Request
    ) -> web.StreamResponse | None:
        """Generate an HTTP MJPEG stream from the camera."""
        if not self._stream_url:
            return None

        ffmpeg_manager: FFmpegManager = self.hass.data[DATA_FFMPEG]

        # pylint: disable=no-value-for-parameter
        stream = CameraMjpeg(ffmpeg_manager.binary)

        await stream.open_camera(self._ffmpeg_input, extra_cmd=self._ffmpeg_arguments)

        try:
            stream_reader = await stream.get_reader()
            return await async_aiohttp_proxy_stream(
                self.hass,
                request,
                stream_reader,
                ffmpeg_manager.ffmpeg_stream_content_type,
            )
        finally:
            await stream.close()


class BewardFileCamera(LocalFile):
    """Beward camera for static images."""

    def __init__(self, controller: BewardController, camera_type: str) -> None:
        """Initialize."""
        super().__init__(
            CAMERAS[camera_type][0].format(controller.name),
            controller.history_image_path(CAMERAS[camera_type][2]),
            f"{controller.unique_id}-file-{camera_type}",
        )

        self._controller = controller

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return the device info."""
        return self._controller.device_info
