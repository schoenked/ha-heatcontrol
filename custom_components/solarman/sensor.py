from __future__ import annotations

import logging

from typing import Any

from homeassistant.components.template.sensor import SensorTemplate
from homeassistant.components.template.sensor import TriggerSensorEntity
from homeassistant.helpers.template import Template

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.components.sensor import RestoreSensor, SensorEntity, SensorDeviceClass
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import create_entity, SolarmanEntity

_LOGGER = logging.getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

def _create_entity(coordinator, description, options):
    if "artificial" in description:
        match description["artificial"]:
            case "interval":
                return SolarmanIntervalSensor(coordinator, description)
    elif (name := description["name"]) and "Battery" in name and (additional := options.get(CONF_ADDITIONAL_OPTIONS, {})) is not None:
        battery_nominal_voltage = additional.get(CONF_BATTERY_NOMINAL_VOLTAGE, DEFAULT_[CONF_BATTERY_NOMINAL_VOLTAGE])
        battery_life_cycle_rating = additional.get(CONF_BATTERY_LIFE_CYCLE_RATING, DEFAULT_[CONF_BATTERY_LIFE_CYCLE_RATING])
        if "registers" in description:
            if name == "Battery":
                return SolarmanBatterySensor(coordinator, description, battery_nominal_voltage, battery_life_cycle_rating)
        else:
            if name == "Battery State":
                return SolarmanBatteryCustomSensor(coordinator, description, battery_nominal_voltage, battery_life_cycle_rating)
            elif battery_nominal_voltage > 0 and battery_life_cycle_rating > 0 and name in ("Battery SOH", "Today Battery Life Cycles", "Total Battery Life Cycles"):
                return SolarmanBatteryCustomSensor(coordinator, description, battery_nominal_voltage, battery_life_cycle_rating)

    if "persistent" in description:
        return SolarmanPersistentSensor(coordinator, description)

    if "restore" in description or "ensure_increasing" in description:
        return SolarmanRestoreSensor(coordinator, description)

    return SolarmanSensor(coordinator, description)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config_entry.options}")

    coordinator, descriptions = get_coordinator(hass, config_entry.entry_id)

    _LOGGER.debug(f"async_setup_entry: async_add_entities")

    async_add_entities(create_entity(lambda x: _create_entity(coordinator, x, config_entry.options), d) for d in descriptions if is_platform(d, _PLATFORM))

    return True

async def async_unload_entry(_: HomeAssistant, config_entry: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config_entry.options}")

    return True

class SolarmanSensorEntity(SolarmanEntity, SensorEntity):
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator, sensor)
        if "state_class" in sensor and (state_class := sensor["state_class"]):
            self._attr_state_class = state_class

class SolarmanIntervalSensor(SolarmanSensorEntity):
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator, sensor)
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_unit_of_measurement = "s"
        self._attr_state_class = "duration"
        self._attr_icon = "mdi:update"

    @property
    def available(self) -> bool:
        return self._attr_native_value > 0

    def update(self):
        self.set_state(self.coordinator.inverter.state.updated_interval.total_seconds())

class SolarmanSensor(SolarmanSensorEntity):
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator, sensor)
        self._sensor_ensure_increasing = "ensure_increasing" in sensor

class SolarmanRestoreSensor(SolarmanSensor, RestoreSensor):
    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        if (last_sensor_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last_sensor_data.native_value
            self._attr_native_unit_of_measurement = last_sensor_data.native_unit_of_measurement

    def set_state(self, state, value = None) -> bool:
        if self._sensor_ensure_increasing and self._attr_native_value and self._attr_native_value > state > 0:
            return False
        return super().set_state(state, value)

class SolarmanPersistentSensor(SolarmanRestoreSensor):
    @property
    def available(self) -> bool:
        return True

class SolarmanBatterySensor(SolarmanSensor):
    def __init__(self, coordinator, sensor, battery_nominal_voltage, battery_life_cycle_rating):
        super().__init__(coordinator, sensor)
        if battery_nominal_voltage > 0 and battery_life_cycle_rating > 0:
            self._attr_extra_state_attributes = self._attr_extra_state_attributes | { "Nominal Voltage": battery_nominal_voltage, "Life Cycle Rating": battery_life_cycle_rating }

class SolarmanBatteryCustomSensor(SolarmanSensor):
    def __init__(self, coordinator, sensor, battery_nominal_voltage, battery_life_cycle_rating):
        super().__init__(coordinator, sensor)
        self._battery_nominal_voltage = battery_nominal_voltage
        self._battery_life_cycle_rating = battery_life_cycle_rating
        self._digits = sensor[DIGITS] if DIGITS in sensor else DEFAULT_[DIGITS]

    def update(self):
        #super().update()
        c = len(self.coordinator.data)
        if c > 1 or (c == 1 and self._attr_key in self.coordinator.data):
            match self._attr_key:
                case "battery_soh_sensor":
                    total_battery_charge = get_tuple(self.coordinator.data.get("total_battery_charge_sensor"))
                    if total_battery_charge == 0:
                        self.set_state(100)
                        return
                    battery_capacity = get_tuple(self.coordinator.data.get("battery_capacity_number"))
                    battery_corrected_capacity = get_tuple(self.coordinator.data.get("battery_corrected_capacity_sensor"))
                    if battery_capacity and battery_corrected_capacity:
                        battery_capacity_5 = battery_capacity / 100 * 5
                        if battery_capacity - battery_capacity_5 <= battery_corrected_capacity <= battery_capacity + battery_capacity_5:
                            battery_capacity = battery_corrected_capacity
                    if total_battery_charge and battery_capacity and self._battery_nominal_voltage and self._battery_life_cycle_rating:
                        self.set_state(get_number(100 - total_battery_charge / get_battery_power_capacity(battery_capacity, self._battery_nominal_voltage) / (self._battery_life_cycle_rating * 0.05), self._digits))
                case "battery_state_sensor":
                    battery_power = get_tuple(self.coordinator.data.get("battery_power_sensor"))
                    if battery_power:
                        self.set_state("discharging" if battery_power > 50 else "charging" if battery_power < -50 else "idle")
                case "today_battery_life_cycles_sensor":
                    today_battery_charge = get_tuple(self.coordinator.data.get("today_battery_charge_sensor"))
                    if today_battery_charge == 0:
                        self.set_state(0)
                        return
                    battery_capacity = get_tuple(self.coordinator.data.get("battery_capacity_number"))
                    battery_corrected_capacity = get_tuple(self.coordinator.data.get("battery_corrected_capacity_sensor"))
                    if battery_capacity and battery_corrected_capacity:
                        battery_capacity_5 = battery_capacity / 100 * 5
                        if battery_capacity - battery_capacity_5 <= battery_corrected_capacity <= battery_capacity + battery_capacity_5:
                            battery_capacity = battery_corrected_capacity
                    if today_battery_charge and battery_capacity and self._battery_nominal_voltage:
                        self.set_state(get_number(get_battery_cycles(today_battery_charge, battery_capacity, self._battery_nominal_voltage), self._digits))
                case "total_battery_life_cycles_sensor":
                    total_battery_charge = get_tuple(self.coordinator.data.get("total_battery_charge_sensor"))
                    if total_battery_charge == 0:
                        self.set_state(0)
                        return
                    battery_capacity = get_tuple(self.coordinator.data.get("battery_capacity_number"))
                    battery_corrected_capacity = get_tuple(self.coordinator.data.get("battery_corrected_capacity_sensor"))
                    if battery_capacity and battery_corrected_capacity:
                        battery_capacity_5 = battery_capacity / 100 * 5
                        if battery_capacity - battery_capacity_5 <= battery_corrected_capacity <= battery_capacity + battery_capacity_5:
                            battery_capacity = battery_corrected_capacity
                    if total_battery_charge and battery_capacity and self._battery_nominal_voltage:
                        self.set_state(get_number(get_battery_cycles(total_battery_charge, battery_capacity, self._battery_nominal_voltage), self._digits))
