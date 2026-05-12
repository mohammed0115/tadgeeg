from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from apps.payments.gateways.factory import (
    get_payment_gateway,
    validate_configured_provider,
)
from apps.payments.gateways.moyasar import MoyasarGateway
from apps.payments.gateways.tap import TapGateway
from apps.payments.gateways.telr import TelrGateway


class GatewayFactoryTests(SimpleTestCase):

    @override_settings(PAYMENT_PROVIDER="moyasar")
    def test_returns_moyasar_for_moyasar_setting(self):
        gw = get_payment_gateway()
        self.assertIsInstance(gw, MoyasarGateway)
        self.assertEqual(gw.PROVIDER, "moyasar")

    @override_settings(PAYMENT_PROVIDER="tap")
    def test_returns_tap_for_tap_setting(self):
        gw = get_payment_gateway()
        self.assertIsInstance(gw, TapGateway)
        self.assertEqual(gw.PROVIDER, "tap")

    @override_settings(PAYMENT_PROVIDER="telr")
    def test_returns_telr_for_telr_setting(self):
        gw = get_payment_gateway()
        self.assertIsInstance(gw, TelrGateway)
        self.assertEqual(gw.PROVIDER, "telr")

    @override_settings(PAYMENT_PROVIDER="stripe")
    def test_unknown_provider_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            get_payment_gateway()
        with self.assertRaises(ImproperlyConfigured):
            validate_configured_provider()

    @override_settings(PAYMENT_PROVIDER="")
    def test_blank_provider_raises_on_get_but_not_validate(self):
        # validate is lenient (allows disabling payments) ...
        validate_configured_provider()
        # ... but actually trying to get a gateway must fail loudly.
        with self.assertRaises(ImproperlyConfigured):
            get_payment_gateway()

    @override_settings(PAYMENT_PROVIDER="moyasar")
    def test_explicit_argument_overrides_setting(self):
        gw = get_payment_gateway("tap")
        self.assertIsInstance(gw, TapGateway)
