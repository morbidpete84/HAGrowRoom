"""WiZ Light integration."""
from datetime import timedelta
import logging

from pywizlight import PilotBuilder, wizlight
from pywizlight.bulblibrary import BulbType
from pywizlight.exceptions import (
    WizLightConnectionError,
    WizLightNotKnownBulb,
    WizLightTimeOutError,
)
import voluptuous as vol

# Import the device class from the component
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    PLATFORM_SCHEMA,
    SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR,
    SUPPORT_COLOR_TEMP,
    SUPPORT_EFFECT,
    LightEntity,
)
from homeassistant.const import CONF_HOST, CONF_NAME


from .rgbcw import rgb2rgbcw, rgbcw2hs, hs2rgbcw

import homeassistant.helpers.config_validation as cv
from homeassistant.util import slugify
import homeassistant.util.color as color_utils

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SUPPORT_FEATURES_RGB = (
    SUPPORT_BRIGHTNESS | SUPPORT_COLOR | SUPPORT_COLOR_TEMP | SUPPORT_EFFECT
)
SUPPORT_FEATURES_DIM = SUPPORT_BRIGHTNESS
SUPPORT_FEATURES_WHITE = SUPPORT_BRIGHTNESS | SUPPORT_COLOR_TEMP

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {vol.Required(CONF_HOST): cv.string, vol.Required(CONF_NAME): cv.string}
)

# set poll interval to 30 sec because of changes from external to the bulb
SCAN_INTERVAL = timedelta(seconds=15)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the WiZ Light platform from legacy config."""
    # Assign configuration variables.
    # The configuration check takes care they are present.
    ip_address = config[CONF_HOST]
    try:
        bulb = wizlight(ip_address)
        # Add devices
        async_add_entities([WizBulb(bulb, config[CONF_NAME])], update_before_add=True)
        return True
    except WizLightConnectionError:
        _LOGGER.error("Can't add bulb with ip %s.", ip_address)
        return False


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the WiZ Light platform from config_flow."""
    # Assign configuration variables.
    bulb = hass.data[DOMAIN][entry.unique_id]
    wizbulb = WizBulb(bulb, entry.data.get(CONF_NAME))
    # Add devices with defined name
    async_add_entities([wizbulb], update_before_add=True)

    # Register services
    async def async_update(call=None):
        """Trigger update."""
        _LOGGER.debug("[wizlight %s] update requested", entry.data.get(CONF_HOST))
        await wizbulb.async_update()
        await wizbulb.async_update_ha_state()

    service_name = slugify(f"{entry.data.get(CONF_NAME)} updateService")
    hass.services.async_register(DOMAIN, service_name, async_update)
    return True


class WizBulb(LightEntity):
    """Representation of WiZ Light bulb."""

    def __init__(self, light: wizlight, name):
        """Initialize an WiZLight."""
        self._light: wizlight = light
        self._state = None
        self._brightness = None
        self._name = name
        self._rgb_color = None
        self._temperature = None
        self._hscolor = None
        self._available = None
        self._effect = None
        self._scenes: list[str] = []
        self._bulbtype: BulbType = None
        self._mac = None

    @property
    def brightness(self):
        """Return the brightness of the light."""
        return self._brightness

    @property
    def rgb_color(self):
        """Return the color property."""
        return self._rgb_color

    @property
    def hs_color(self):
        """Return the hs color value."""
        return self._hscolor

    @property
    def name(self):
        """Return the ip as name of the device if any."""
        return self._name

    @property
    def unique_id(self):
        """Return light unique_id."""
        return self._mac

    @property
    def is_on(self):
        """Return true if light is on."""
        return self._state

    async def async_turn_on(self, **kwargs):
        """Instruct the light to turn on."""
        brightness = None

        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs.get(ATTR_BRIGHTNESS)

        if ATTR_RGB_COLOR in kwargs:
            pilot = rgb2rgbcw(kwargs.get(ATTR_RGB_COLOR), brightness)
        if ATTR_HS_COLOR in kwargs:
            pilot = hs2rgbcw(kwargs.get(ATTR_HS_COLOR), brightness)
        else:
            colortemp = None
            if ATTR_COLOR_TEMP in kwargs:
                kelvin = color_utils.color_temperature_mired_to_kelvin(
                    kwargs[ATTR_COLOR_TEMP]
                )
                colortemp = kelvin
                _LOGGER.debug(
                    "[wizlight %s] kelvin changed and send to bulb: %s",
                    self._light.ip,
                    colortemp,
                )

            sceneid = None
            if ATTR_EFFECT in kwargs:
                sceneid = self._light.get_id_from_scene_name(kwargs[ATTR_EFFECT])

            if sceneid == 1000:  # rhythm
                pilot = PilotBuilder()
            else:
                pilot = PilotBuilder(
                    brightness=brightness, colortemp=colortemp, scene=sceneid
                )
                _LOGGER.debug(
                    "[wizlight %s] Pilot will be send with brightness=%s, colortemp=%s, scene=%s",
                    self._light.ip,
                    brightness,
                    colortemp,
                    sceneid,
                )
        await self._light.turn_on(
            pilot,
        )

    async def async_turn_off(self, **kwargs):
        """Instruct the light to turn off."""
        await self._light.turn_off()

    @property
    def color_temp(self):
        """Return the CT color value in mireds."""
        return self._temperature

    @property
    def min_mireds(self):
        """Return the coldest color_temp that this light supports."""
        if self._bulbtype is None:
            return color_utils.color_temperature_kelvin_to_mired(6500)

        try:
            return color_utils.color_temperature_kelvin_to_mired(
                self._bulbtype.kelvin_range.max
            )

        except WizLightNotKnownBulb:
            _LOGGER.info("Kelvin is not present in the library. Fallback to 6500")
            return color_utils.color_temperature_kelvin_to_mired(6500)

    @property
    def max_mireds(self):
        """Return the warmest color_temp that this light supports."""
        if self._bulbtype is None:
            return color_utils.color_temperature_kelvin_to_mired(2200)

        try:
            return color_utils.color_temperature_kelvin_to_mired(
                self._bulbtype.kelvin_range.min
            )
        except WizLightNotKnownBulb:
            _LOGGER.info("Kelvin is not present in the library. Fallback to 2200")
            return color_utils.color_temperature_kelvin_to_mired(2200)

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        if self._bulbtype:
            return self.featuremap()
        # fallback
        return SUPPORT_FEATURES_RGB

    @property
    def effect(self):
        """Return the current effect."""
        return self._effect

    @property
    def effect_list(self):
        """Return the list of supported effects.

        URL: https://docs.pro.wizconnected.com/#light-modes
        """
        return self._scenes

    @property
    def available(self):
        """Return if light is available."""
        return self._available

    async def async_update(self):
        """Fetch new state data for this light."""
        await self.update_state()

        if self._state is not None and self._state is not False:
            self.update_brightness()
            self.update_temperature()
            self.update_color()
            self.update_effect()
            await self.update_scene_list()

    @property
    def device_info(self):
        """Get device specific attributes."""
        _LOGGER.debug(
            "[wizlight %s] Call device info: MAC: %s - Name: %s - Type: %s",
            self._light.ip,
            self._mac,
            self._name,
            self._bulbtype.name,
        )
        return {
            "identifiers": {(DOMAIN, self._mac)},
            "name": self._name,
            "manufacturer": "WiZ Light Platform",
            "model": self._bulbtype.name,
        }

    def update_state_available(self):
        """Update the state if bulb is available."""
        self._state = self._light.status
        self._available = True

    def update_state_unavailable(self):
        """Update the state if bulb is unavailable."""
        self._state = False
        self._available = False

    async def update_state(self):
        """Update the state."""
        try:
            await self._light.updateState()
            if self._light.state is None:
                self.update_state_unavailable()
            else:
                self.update_state_available()
                # Update the rest of the missing info if available
                await self.get_bulb_type()
                await self.get_mac()
        except TimeoutError as ex:
            _LOGGER.debug(ex)
            self.update_state_unavailable()
        except WizLightTimeOutError as ex:
            _LOGGER.debug(ex)
            self.update_state_unavailable()
        _LOGGER.debug(
            "[wizlight %s] updated state: %s and available: %s",
            self._light.ip,
            self._state,
            self._available,
        )

    def update_brightness(self):
        """Update the brightness."""
        if self._light.state.get_brightness() is None:
            return
        try:
            brightness = self._light.state.get_brightness()
            if 0 <= int(brightness) <= 255:
                self._brightness = int(brightness)
            else:
                _LOGGER.error(
                    "Received invalid brightness : %s. Expected: 0-255", brightness
                )
                self._brightness = None
        # pylint: disable=broad-except
        except Exception as ex:
            _LOGGER.error(ex)
            self._state = None

    def update_temperature(self):
        """Update the temperature."""
        colortemp = self._light.state.get_colortemp()
        if colortemp is None or colortemp == 0:
            self._temperature = None
            return
        try:
            _LOGGER.debug(
                "[wizlight %s] kelvin from the bulb: %s", self._light.ip, colortemp
            )
            temperature = color_utils.color_temperature_kelvin_to_mired(colortemp)
            self._temperature = temperature

        # pylint: disable=broad-except
        except Exception:
            _LOGGER.error("Cannot evaluate temperature", exc_info=True)
            self._temperature = None

    def update_color(self):
        """Update the hs color."""
        colortemp = self._light.state.get_colortemp()
        if colortemp is not None and colortemp != 0:
            self._hscolor = None
            return
        if self._light.state.get_rgb() is None:
            return
        try:
            rgb = self._light.state.get_rgb()
            if rgb[0] is None:
                # this is the case if the temperature was changed - no information was return form the lamp.
                # do nothing until the RGB color was changed
                return

            cw = self._light.state.get_warm_white()
            if cw is None:
                return

            self._hscolor = rgbcw2hs(rgb, cw)

        # pylint: disable=broad-except
        except Exception:
            _LOGGER.error("Cannot evaluate color", exc_info=True)
            self._hscolor = None

    def update_effect(self):
        """Update the bulb scene."""
        self._effect = self._light.state.get_scene()

    async def get_bulb_type(self):
        """Get the bulb type."""
        if self._bulbtype is not None:
            return self._bulbtype

        try:
            self._bulbtype = await self._light.get_bulbtype()
            _LOGGER.info(
                "[wizlight %s] Initiate the WiZ bulb as %s",
                self._light.ip,
                self._bulbtype.name,
            )
        except WizLightTimeOutError:
            _LOGGER.debug(
                "[wizlight %s] Bulbtype update failed - Timeout", self._light.ip
            )

    async def update_scene_list(self):
        """Update the scene list."""
        self._scenes = await self._light.getSupportedScenes()

    async def get_mac(self):
        """Get the mac from the bulb."""
        try:
            self._mac = await self._light.getMac()
        except WizLightTimeOutError:
            _LOGGER.debug("[wizlight %s] Mac update failed - Timeout", self._light.ip)

    def featuremap(self):
        """Map the features from WizLight Class."""
        features = 0
        try:
            # Map features for better reading
            if self._bulbtype.features.brightness:
                features = features | SUPPORT_BRIGHTNESS
            if self._bulbtype.features.color:
                features = features | SUPPORT_COLOR
            if self._bulbtype.features.effect:
                features = features | SUPPORT_EFFECT
            if self._bulbtype.features.color_tmp:
                features = features | SUPPORT_COLOR_TEMP
            return features
        except WizLightNotKnownBulb:
            _LOGGER.info("Bulb is not present in the library. Fallback to full feature")
            return SUPPORT_FEATURES_RGB
