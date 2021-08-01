"""Define helpers to process data from an Ecowitt device."""
from functools import partial
import inspect
from typing import Any, Callable, Dict, Optional

from ecowitt2mqtt.const import (
    DATA_POINT_DEWPOINT,
    DATA_POINT_FEELSLIKE,
    DATA_POINT_GLOB_BAROM,
    DATA_POINT_GLOB_BATT,
    DATA_POINT_GLOB_RAIN,
    DATA_POINT_GLOB_TEMP,
    DATA_POINT_GLOB_WIND,
    DATA_POINT_HEATINDEX,
    DATA_POINT_HUMIDITY,
    DATA_POINT_TEMPF,
    DATA_POINT_WINDCHILL,
    DATA_POINT_WINDSPEEDMPH,
    UNIT_SYSTEM_IMPERIAL,
)
from ecowitt2mqtt.device import get_device_from_raw_payload
from ecowitt2mqtt.util.battery import calculate_binary_battery
from ecowitt2mqtt.util.meteo import (
    calculate_dew_point,
    calculate_feels_like,
    calculate_heat_index,
    calculate_pressure,
    calculate_rain_volume,
    calculate_temperature,
    calculate_wind_chill,
    calculate_wind_speed,
)

DEFAULT_KEYS_TO_IGNORE = ["PASSKEY", "dateutc", "freq", "model", "stationtype"]
DEFAULT_UNIQUE_ID = "default"

CALCULATOR_FUNCTION_MAP: Dict[str, Callable] = {
    DATA_POINT_DEWPOINT: calculate_dew_point,
    DATA_POINT_FEELSLIKE: calculate_feels_like,
    DATA_POINT_GLOB_BAROM: calculate_pressure,
    DATA_POINT_GLOB_BATT: calculate_binary_battery,
    DATA_POINT_GLOB_RAIN: calculate_rain_volume,
    DATA_POINT_GLOB_TEMP: calculate_temperature,
    DATA_POINT_GLOB_WIND: calculate_wind_speed,
    DATA_POINT_HEATINDEX: calculate_heat_index,
    DATA_POINT_WINDCHILL: calculate_wind_chill,
}

# NOTE: these are lists because the order of the data points matters!
DEW_POINT_KEYS = [DATA_POINT_TEMPF, DATA_POINT_HUMIDITY]
FEELS_LIKE_KEYS = [DATA_POINT_TEMPF, DATA_POINT_HUMIDITY, DATA_POINT_WINDSPEEDMPH]
HEAT_INDEX_KEYS = [DATA_POINT_TEMPF, DATA_POINT_HUMIDITY]
WIND_CHILL_KEYS = [DATA_POINT_TEMPF, DATA_POINT_WINDSPEEDMPH]


def de_unit_key(key: str) -> str:
    """Remove the unit from a key."""
    if key.endswith("f"):
        return key[:-1]
    if key.endswith("in"):
        return key[:-2]
    if key.endswith("mph"):
        return key[:-3]
    return key


def get_data_type(key: str) -> Optional[str]:
    """Get the data "type" (if it exists) for a specific data key."""
    if key in CALCULATOR_FUNCTION_MAP:
        return key

    matches = [k for k in CALCULATOR_FUNCTION_MAP if k in key]
    if matches:
        return matches[0]

    return None


class DataProcessor:  # pylint: disable=too-few-public-methods
    """Define an object that holds processed payload data from the device."""

    def __init__(
        self,
        payload: Dict[str, Any],
        *,
        input_unit_system: str = UNIT_SYSTEM_IMPERIAL,
        output_unit_system: str = UNIT_SYSTEM_IMPERIAL
    ) -> None:
        """Initialize."""
        self._calculator_funcs: Dict[str, Callable] = {}
        self._input_unit_system = input_unit_system
        self._output_unit_system = output_unit_system
        self._payload = payload
        self.device = get_device_from_raw_payload(payload)
        self.unique_id = payload.get("PASSKEY", DEFAULT_UNIQUE_ID)

    def _get_calculator_func(self, key: str) -> Optional[Callable]:
        """Get the proper calculator function for a data point."""
        data_type = get_data_type(key)

        if not data_type:
            return None

        if data_type in self._calculator_funcs:
            return self._calculator_funcs[data_type]

        func = CALCULATOR_FUNCTION_MAP[data_type]

        kwargs = {}
        func_params = inspect.signature(func).parameters
        if "input_unit_system" in func_params:
            kwargs["input_unit_system"] = self._input_unit_system
        if "output_unit_system" in func_params:
            kwargs["output_unit_system"] = self._output_unit_system

        self._calculator_funcs[data_type] = partial(func, **kwargs)
        return self._calculator_funcs[data_type]

    def generate_data(self) -> Dict[str, Any]:
        """Generate a parsed data payload."""
        translated_data: Dict[str, Any] = {}
        for target_key, value in self._payload.items():
            if target_key in DEFAULT_KEYS_TO_IGNORE:
                continue

            try:
                value = float(value)
            except ValueError:
                pass

            calculator = self._get_calculator_func(target_key)
            if calculator:
                output = calculator(value)
                target_key = de_unit_key(target_key)
                translated_data[target_key] = output
            else:
                translated_data[target_key] = value

        calculated_data: Dict[str, Any] = {}
        for target_key, input_keys in [
            (DATA_POINT_DEWPOINT, DEW_POINT_KEYS),
            (DATA_POINT_FEELSLIKE, FEELS_LIKE_KEYS),
            (DATA_POINT_HEATINDEX, HEAT_INDEX_KEYS),
            (DATA_POINT_WINDCHILL, WIND_CHILL_KEYS),
        ]:
            if not all(k in translated_data for k in input_keys):
                continue

            calculator = self._get_calculator_func(target_key)
            if calculator:
                output = calculator(*[self._payload[k] for k in input_keys])
                calculated_data[target_key] = output

        return {**translated_data, **calculated_data}
