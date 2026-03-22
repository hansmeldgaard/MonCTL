"""Factory-boy factories for generating test data."""

from __future__ import annotations

import uuid

import factory


class DeviceFactory(factory.Factory):
    """Generate Device creation request bodies."""

    class Meta:
        model = dict

    name = factory.Sequence(lambda n: f"test-device-{n}")
    address = factory.Sequence(lambda n: f"10.0.0.{n + 1}")
    device_type_id = None
    description = factory.LazyAttribute(lambda o: f"Test device {o.name}")


class AppFactory(factory.Factory):
    """Generate App creation request bodies."""

    class Meta:
        model = dict

    name = factory.Sequence(lambda n: f"test_app_{n}")
    description = factory.LazyAttribute(lambda o: f"Test app {o.name}")
    app_type = "script"
    target_table = "availability_latency"


class CredentialFactory(factory.Factory):
    """Generate Credential creation request bodies."""

    class Meta:
        model = dict

    name = factory.Sequence(lambda n: f"cred-{n}")
    credential_type = "snmpv2"
    values = factory.LazyFunction(lambda: {"community": "public"})


class UserFactory(factory.Factory):
    """Generate User creation request bodies."""

    class Meta:
        model = dict

    username = factory.Sequence(lambda n: f"testuser-{n}")
    password = "testpass123"
    role = "user"
    display_name = factory.LazyAttribute(lambda o: f"Test User {o.username}")
