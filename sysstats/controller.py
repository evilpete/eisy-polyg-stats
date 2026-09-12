"""The single node this plugin publishes."""

import udi_interface

from . import config as configuration
from . import profile
from .metrics import Collector
from .registry import EDITORS, all_drivers

LOGGER = udi_interface.LOGGER
Custom = udi_interface.Custom


class StatsController(udi_interface.Node):
    """Holds every driver the plugin can ever report.

    The node carries the full driver table while the generated node definition
    decides which of them IoX actually shows, which keeps a re-configure from
    disturbing the drivers that stay.
    """

    id = profile.NODE_ID

    # every possible driver, the node definition selects what is displayed
    drivers = [{'driver': driver, 'value': 0, 'uom': EDITORS[editor]['uom']}
               for driver, _, editor in all_drivers()]

    def __init__(self, polyglot, primary, address, name):
        super().__init__(polyglot, primary, address, name)
        self.poly = polyglot
        self.Parameters = Custom(polyglot, 'customparams')
        self.Notices = Custom(polyglot, 'notices')
        self.config = configuration.Config()
        self.collector = None
        self.reported = set()
        # base precision and uom per driver, refined once the configuration
        # arrives (the temperature editor depends on the chosen unit)
        self.precision = {d: EDITORS[e]['prec'] for d, _, e in all_drivers()}
        self.scale = {d: EDITORS[e].get('int_scale', 1)
                      for d, _, e in all_drivers()}
        self.uom = {d: EDITORS[e]['uom'] for d, _, e in all_drivers()}
        self.configured = False

        polyglot.subscribe(polyglot.CONFIG, self.config_handler)
        polyglot.subscribe(polyglot.CUSTOMPARAMS, self.parameter_handler)
        polyglot.subscribe(polyglot.START, self.start, address)
        polyglot.subscribe(polyglot.POLL, self.poll)
        polyglot.subscribe(polyglot.STOP, self.stop)
        polyglot.addNode(self)

    # ----------------------------------------------------------- life cycle

    def start(self):
        LOGGER.info('Starting %s', self.name)
        self.poly.setCustomParamsDoc()
        if not self.Parameters.keys():
            self.Parameters.load({'display': configuration.defaults_doc()})
        if not self.configured:
            # no Custom Parameters were delivered, come up on the defaults
            self.parameter_handler(dict(self.Parameters))
        self.setDriver('ST', 1)
        self.update()

    def stop(self):
        self.setDriver('ST', 0)
        LOGGER.info('Stopping %s', self.name)

    def config_handler(self, config):
        """Restore the driver table after PG3 hands us a config.

        The interface replaces node.drivers with whatever PG3's database
        holds every time a config arrives, and a node the database has only
        just learned about carries no drivers at all -- which leaves the node
        unable to report anything.  Put our own table back, keeping the values
        and uoms PG3 already knows, and re-add the node so the database learns
        the drivers it is missing.
        """
        changed = self._restore_drivers()
        if changed:
            LOGGER.info('Driver table restored after PG3 config, %d driver(s) '
                        'differed: %s', len(changed), ', '.join(sorted(changed)))
            self.poly.addNode(self)

    def _restore_drivers(self):
        """Re-assert the full driver table.  Returns the driver names that
        differed from it."""
        existing = {d['driver']: d for d in (self.drivers or [])}
        table = []
        for driver, _, editor in all_drivers():
            current = existing.get(driver) or {}
            table.append({
                'driver': driver,
                'value': current.get('value', 0),
                'uom': current.get('uom',
                                   self.uom.get(driver, EDITORS[editor]['uom'])),
            })
        self.drivers = table
        return set(existing) ^ {d['driver'] for d in table}

    def parameter_handler(self, params):
        """Re-read Custom Parameters and rebuild the profile if needed."""
        self.config = configuration.parse(params)
        self.collector = Collector(self.config)
        specs = profile.editor_specs(self.config)
        layout = profile.driver_layout(self.config)
        self.reported = {d for d, _, _ in layout}
        self.precision.update({d: specs[e]['prec'] for d, _, e in layout})
        self.scale.update({d: specs[e].get('int_scale', 1)
                           for d, _, e in layout})
        self.uom.update({d: specs[e]['uom'] for d, _, e in layout})

        self.refresh_notices()
        if profile.write(self.config):
            LOGGER.info('Profile rebuilt for: %s', self.config.signature())
            self.poly.updateProfile()
        self.configured = True
        self.update()

    def poll(self, polltype):
        if polltype == 'shortPoll':
            self.update()
        elif polltype == 'longPoll':
            self.setDriver('ST', 1)

    def query(self, command=None):
        self.update()
        self.reportDrivers()

    # -------------------------------------------------------------- reporting

    def update(self):
        """Sample the host and push the enabled drivers to IoX."""
        if not self.configured or self.collector is None:
            return
        for driver, value in self.collector.collect().items():
            if driver in self.reported:
                self.setDriver(driver, value)
        self.refresh_notices()

    def refresh_notices(self):
        """Show configuration errors and unavailable counters in the UI."""
        notices = {}
        for index, error in enumerate(self.config.errors):
            notices['cfg%d' % index] = error
        if not any(self.config.enabled.values()):
            notices['empty'] = 'No metrics are enabled, check the display ' \
                               'parameter'
        if self.collector:
            for key, message in self.collector.issues.items():
                notices['sys:' + key] = message
        if dict(self.Notices) != notices:
            self.Notices.clear()
            for key, message in notices.items():
                self.Notices[key] = message

    def setDriver(self, driver, value, **kwargs):
        """Send the value the way the configuration says IoX wants it.

        IoX has been seen displaying the digits it is sent with the decimal
        point removed -- 33.0 arrives as 330 -- so unless `decimals` is set
        the value is rounded to a whole number, after the scale that keeps
        load average meaningful.
        """
        prec = self.precision.get(driver, 0)
        if value is None:
            return
        if not any(d['driver'] == driver for d in (self.drivers or [])):
            # a config from PG3 dropped it, see config_handler
            self._restore_drivers()
        try:
            value = float(value)
        except (TypeError, ValueError):
            LOGGER.error('Bad value for %s: %r', driver, value)
            return
        value *= self.scale.get(driver, 1)
        value = round(value, prec) if prec else int(round(value))
        kwargs.setdefault('uom', self.uom.get(driver))
        super().setDriver(driver, value, **kwargs)

    commands = {'QUERY': query}
