#!/usr/bin/env python3
"""
eisy-polyg-stats -- a lightweight Universal Devices EISY / Polyglot v3 plugin
that reports FreeBSD localhost system statistics to IoX.
"""

import sys
import os


import udi_interface

from sysstats import VERSION
from sysstats.controller import StatsController

LOGGER = udi_interface.LOGGER

if __name__ == '__main__':
    os.nice(2)
    polyglot = None
    try:
        polyglot = udi_interface.Interface([])
        polyglot.start(VERSION)
        StatsController(polyglot, 'stats', 'stats', 'System Stats')
        polyglot.ready()
        polyglot.runForever()
    except (KeyboardInterrupt, SystemExit):
        LOGGER.warning('Received interrupt, exiting')
        if polyglot:
            polyglot.stop()
        sys.exit(0)
    except Exception:
        LOGGER.exception('Fatal error, exiting')
        if polyglot:
            polyglot.stop()
        sys.exit(1)
