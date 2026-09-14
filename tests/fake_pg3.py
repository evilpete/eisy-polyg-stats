"""
A stand-in for PG3 so the plugin can be exercised without an EISY or MQTT.

The Node class here is the *real* udi_interface.Node when the library is
installed, because the behaviour worth testing lives in it -- notably that
Interface replaces node.drivers with whatever PG3's database holds every time
a config arrives.  When udi_interface is not installed a minimal Node with the
same contract is used instead, so the tests still run anywhere.
"""

import logging
import os
import sys
import types

LOGGER = logging.getLogger('udi')


def _real_node():
    """The real udi_interface Node, loaded straight from its file.

    Importing udi_interface normally drags in paho-mqtt and netifaces, which
    the test environment does not need, so node.py is loaded on its own.
    """
    import importlib.util
    try:
        package = importlib.util.find_spec('udi_interface')
        if not package or not package.submodule_search_locations:
            return None
        path = os.path.join(list(package.submodule_search_locations)[0],
                            'node.py')
        spec = importlib.util.spec_from_file_location('_udi_real_node', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        logging.getLogger('_udi_real_node').setLevel(logging.CRITICAL)
        return module.Node
    except Exception:  # fall back to the stand-in below
        return None


class FallbackNode:
    """Mirrors udi_interface.Node closely enough for these tests."""

    drivers = []

    def __init__(self, poly, primary, address, name):
        self.poly, self.primary, self.address, self.name = \
            poly, primary, address, name
        self.drivers = [dict(d) for d in type(self).drivers]
        self.hint = [0, 0, 0, 0]
        self.private = None

    def updateDrivers(self, drivers):
        self.drivers = [dict(d) for d in drivers]

    def getDriver(self, driver):
        for entry in self.drivers:
            if entry['driver'] == driver:
                return entry['value']
        return None

    def setDriver(self, driver, value, report=True, force=False, uom=None,
                  text=None):
        for entry in self.drivers:
            if entry['driver'] == driver:
                entry['value'] = value
                if uom is not None:
                    entry['uom'] = uom
                return
        raise AssertionError('Invalid driver: %s' % driver)

    def reportDrivers(self):
        pass


class Custom(dict):
    def __init__(self, poly, name):
        super().__init__()

    def load(self, data, save=False):
        self.update(data)

    def clear(self):
        dict.clear(self)


class Interface:
    """Records what the plugin sends and can replay PG3's messages."""

    CONFIG = 'config'
    CUSTOMPARAMS = 'customparams'
    START = 'start'
    POLL = 'poll'
    STOP = 'stop'

    def __init__(self, _=None):
        self.subs = {}
        self.db = {}            # PG3's stored node drivers
        self.addnode_calls = 0
        self.profile_updates = 0
        self.status = []

    # ------------------------------------------------ the plugin calls these

    def subscribe(self, topic, callback, address=None):
        self.subs.setdefault(topic, []).append(callback)

    def db_getNodeDrivers(self, addr=None, init=False):
        return self.db.get(addr, [])

    def addNode(self, node, conn_status=None, rename=False):
        self.addnode_calls += 1
        self.db[node.address] = [dict(d) for d in node.drivers]

    def send(self, message, typ):
        if typ == 'status':
            self.status.append(message)

    def updateProfile(self):
        self.profile_updates += 1

    def setCustomParamsDoc(self, html=None):
        pass

    def ready(self):
        pass

    # ------------------------------------------------------- the test drives

    def fire(self, topic, *args):
        for callback in self.subs.get(topic, []):
            callback(*args)

    def send_config(self, node, drivers):
        """Replay what interface.py does on a config message: the node's
        driver table is replaced by the database copy, then CONFIG fires."""
        node.updateDrivers(drivers)
        self.fire(self.CONFIG, {'nodes': [{'address': node.address,
                                           'drivers': drivers}]})


def install():
    """Put the fake udi_interface in sys.modules.  Call before importing
    anything from sysstats."""
    node = _real_node() or FallbackNode
    module = types.ModuleType('udi_interface')
    module.LOGGER = LOGGER
    module.Node = node
    module.Custom = Custom
    module.Interface = Interface
    sys.modules['udi_interface'] = module
    return module
