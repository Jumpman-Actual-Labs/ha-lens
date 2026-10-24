"""Lens: read-only LLM API that lists every Home Assistant entity."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .api import LensAPI
from .const import API_ID, API_NAME


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register the Lens LLM API."""
    entry.async_on_unload(
        llm.async_register_api(hass, LensAPI(hass=hass, id=API_ID, name=API_NAME))
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload; the API is unregistered by async_on_unload."""
    return True
