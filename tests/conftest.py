"""Pytest configuration and common test fixtures."""

import os
import pytest

# Ensure test environment variables are loaded
os.environ["ENVIRONMENT"] = "development"
os.environ["ENCRYPTION_KEY"] = "DNNBZtNBVFFL9TkilQ0wXUmLnphKIzAVNXyR7k0r1fI="
os.environ["JWT_SECRET_KEY"] = "testjwtsecretkeyformockingandtestingpurposesonly"
os.environ["EMAIL_DELIVERY_METHOD"] = "console"
