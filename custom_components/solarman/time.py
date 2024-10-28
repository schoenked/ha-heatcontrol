from __future__ import annotations

import logging

from datetime import datetime, time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import create_entity, SolarmanWritableEntity

_LOGGER = logging.getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config.options}")
    coordinator = hass.data[DOMAIN][config.entry_id]

    descriptions = coordinator.inverter.get_entity_descriptions()

    _LOGGER.debug(f"async_setup: async_add_entities")

    async_add_entities(create_entity(lambda x: SolarmanTimeEntity(coordinator, x), d) for d in descriptions if is_platform(d, _PLATFORM))

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")

    return True

class SolarmanTimeEntity(SolarmanWritableEntity, TimeEntity):
    def __init__(self, coordinator, sensor):
        SolarmanWritableEntity.__init__(self, coordinator, _PLATFORM, sensor)

        self._multiple_registers = self.registers_length > 1 and self.registers[1] == self.registers[0] + 1

    @property
    def native_value(self) -> time | None:
        """Return the state of the setting entity."""
        try:
            if self._attr_native_value:
                if isinstance(self._attr_native_value, list) and len(self._attr_native_value) > 1:
                    return datetime.strptime(f"{self._attr_native_value[0]}:{self._attr_native_value[1]}", TIME_FORMAT).time()
                return datetime.strptime(self._attr_native_value, TIME_FORMAT).time()
        except Exception as e:
            _LOGGER.debug(f"SolarmanTimeEntity.native_value: {format_exception(e)}")
        return None

    async def async_set_value(self, value: time) -> None:
        """Change the time."""
        await self.write(get_t_as_list_int(value, self._multiple_registers), value.strftime(TIME_FORMAT))
