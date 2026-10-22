#!/usr/bin/env python
"""Roda os testes do pacote: python runtests.py [rótulos]"""

import os
import sys

import django
from django.conf import settings
from django.test.utils import get_runner

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
    django.setup()
    runner = get_runner(settings)(verbosity=2)
    sys.exit(bool(runner.run_tests(sys.argv[1:] or ["tests"])))
