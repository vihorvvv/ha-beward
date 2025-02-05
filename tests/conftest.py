# pylint: disable=protected-access,redefined-outer-name
"""Global fixtures for integration."""

# Fixtures allow you to replace functions with a Mock object. You can perform
# many options via the Mock to reflect a particular behavior from the original
# function that you want to see without going through the function's actual logic.
# Fixtures can either be passed into tests as parameters, or if autouse=True, they
# will automatically be used across all tests.
#
# Fixtures that are defined in conftest.py are available across all tests. You can also
# define fixtures within a particular test file to scope them locally.
#
# pytest_homeassistant_custom_component provides some fixtures that are provided by
# Home Assistant core. You can find those fixture definitions here:
# https://github.com/MatthewFlamm/pytest-homeassistant-custom-component/blob/master/pytest_homeassistant_custom_component/common.py
#
# See here for more info: https://docs.pytest.org/en/latest/fixture.html (note that
# pytest includes fixtures OOB which you can use as defined on this page)
from unittest.mock import patch

import pytest
from beward import Beward, BewardGeneric

from tests.const import MOCK_HOST, MOCK_PASSWORD, MOCK_PORT, MOCK_USERNAME

pytest_plugins = "pytest_homeassistant_custom_component"  # pylint: disable=invalid-name


# This fixture enables loading custom integrations in all tests.
# Remove to enable selective use of this fixture
@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations) -> None:
    """Automatically enable loading custom integrations in all tests."""
    return


# This fixture is used to prevent HomeAssistant from attempting to create and dismiss
# persistent notifications. These calls would fail without this fixture since the
# persistent_notification integration is never loaded during a test.
@pytest.fixture(name="skip_notifications", autouse=True)
def _skip_notifications_fixture() -> None:
    """Skip notification calls."""
    with (
        patch("homeassistant.components.persistent_notification.async_create"),
        patch("homeassistant.components.persistent_notification.async_dismiss"),
    ):
        yield


class MockBewardDevice(BewardGeneric):
    """Beward device mock."""

    def __init__(self) -> None:
        """Initialize class."""
        super().__init__(MOCK_HOST, MOCK_USERNAME, MOCK_PASSWORD, port=MOCK_PORT)

    @property
    def system_info(self):
        """Return mock system info."""
        return {
            "DeviceID": "mock_device",
        }


# This fixture, when used, will result in calls to async_get_data to return None. To
# have the call return a value, we would add the `return_value=<VALUE_TO_RETURN>`
# parameter to the patch call.
@pytest.fixture(name="bypass_get_data")
def _bypass_get_data_fixture() -> None:
    """Skip calls to get data from API."""
    with (
        patch.object(BewardGeneric, "is_online", return_value=True),
        patch.object(BewardGeneric, "listen_alarms"),
        patch.object(
            Beward,
            "factory",
            return_value=MockBewardDevice(),
        ),
    ):
        yield


# In this fixture, we are forcing calls to async_get_data to raise an Exception. This
# is useful for exception handling.
@pytest.fixture(name="error_on_get_data")
def _error_get_data_fixture() -> None:
    """Simulate error when retrieving data from API."""
    with patch("beward.Beward.factory", side_effect=Exception):
        yield
