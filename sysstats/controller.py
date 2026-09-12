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
        self.precision = {}
        self.uom = {}
        self.configured = False

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

    def parameter_handler(self, params):
        """Re-read Custom Parameters and rebuild the profile if needed."""
        self.config = configuration.parse(params)
        self.collector = Collector(self.config)
        specs = profile.editor_specs(self.config)
        layout = profile.driver_layout(self.config)
        self.precision = {d: specs[e]['prec'] for d, _, e in layout}
        self.uom = {d: specs[e]['uom'] for d, _, e in layout}

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
        """Scale to the driver's precision, IoX shifts the decimal back."""
        prec = self.precision.get(driver, 0)
        if value is None:
            return
        try:
            scaled = int(round(float(value) * (10 ** prec)))
        except (TypeError, ValueError):
            LOGGER.error('Bad value for %s: %r', driver, value)
            return
        kwargs.setdefault('uom', self.uom.get(driver))
        super().setDriver(driver, scaled, **kwargs)

    commands = {'QUERY': query}
