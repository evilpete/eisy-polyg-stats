#!/usr/bin/env python3
"""
Run with `python3 tests/test_plugin.py` (or under pytest).  No EISY, no MQTT
and no pytest dependency required.
"""

import logging
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import fake_pg3  # noqa: E402

_MODULE = fake_pg3.install()
print('exercising %s Node\n' % ('the real udi_interface'
      if _MODULE.Node is not fake_pg3.FallbackNode else 'the fallback'))

from sysstats import config, profile  # noqa: E402
from sysstats.controller import StatsController  # noqa: E402
from sysstats.registry import MOUNT_DRIVERS, all_drivers  # noqa: E402

logging.getLogger('udi').setLevel(logging.CRITICAL)


def test_display_parameter():
    """The syntax from the original request resolves as documented."""
    cfg = config.parse({
        'display': '+load_avg,-cpu_temp,+disk_capacity=/ /var /var/isy, '
                   '-system_uptime'})
    assert cfg.is_on('load_avg')
    assert not cfg.is_on('cpu_temp')
    assert not cfg.is_on('system_uptime')
    assert cfg.mounts == ['/', '/var', '/var/isy']
    assert cfg.is_on('cpu_util'), 'unmentioned metrics keep their default'
    assert not cfg.is_on('gpu_temp'), 'and that includes the off-by-default'
    assert cfg.errors == []


def test_per_metric_parameters():
    cfg = config.parse({'net_util': 'wlan0', 'cpu_temp': 'false',
                        'temp_unit': 'F', 'disk_capacity': '/ /var'})
    assert cfg.args['net_util'] == ['wlan0']
    assert not cfg.is_on('cpu_temp')
    assert cfg.temp_unit == 'F'
    assert cfg.mounts == ['/', '/var']


def test_bad_input_is_reported_not_raised():
    cfg = config.parse({'display': '+nonsense', 'temp_unit': 'K',
                        'io_interval': 'soon', 'bogus': '1'})
    assert len(cfg.errors) == 4, cfg.errors
    assert cfg.temp_unit == 'C'


def test_profile_follows_the_configuration():
    tmp = tempfile.mkdtemp()
    try:
        cfg = config.parse({'display': '+cpu_util,-load_avg,-disk_capacity,'
                                       '-disk_iostats,-disk_io_util,-net_util,'
                                       '-net_errors,-mem_usage,-system_uptime',
                            'temp_unit': 'F'})
        assert profile.write(cfg, tmp) is True
        assert profile.write(cfg, tmp) is False, 'rewrite must be idempotent'
        assert open(os.path.join(tmp, 'version.txt')).read().strip() == '1'

        nodedef = open(os.path.join(tmp, 'nodedef', 'nodedefs.xml')).read()
        assert '"GV3"' in nodedef, 'cpu_util is enabled'
        assert '"GV0"' not in nodedef, 'load_avg is not'
        editors = open(os.path.join(tmp, 'editor', 'editors.xml')).read()
        assert 'uom="17"' in editors, 'Fahrenheit editor'

        # a changed configuration rewrites and bumps the cached version
        cfg2 = config.parse({'display': '+load_avg'})
        assert profile.write(cfg2, tmp) is True
        assert open(os.path.join(tmp, 'version.txt')).read().strip() == '2'
    finally:
        shutil.rmtree(tmp)


def test_mount_points_keep_their_driver():
    """A metric must not change driver when the configuration changes."""
    one = profile.driver_layout(config.parse({'disk_capacity': '/ /var'}))
    two = profile.driver_layout(config.parse({'display': '-cpu_temp',
                                              'disk_capacity': '/ /var'}))
    mounts = set(MOUNT_DRIVERS)
    assert [d for d, _, _ in one if d in mounts] == ['GV10', 'GV11']
    assert [d for d, _, _ in two if d in mounts] == ['GV10', 'GV11']
    assert dict(profile.precisions(config.parse({}))) == \
        dict(profile.precisions(config.parse({}))), 'stable across calls'


def _node(poly=None):
    poly = poly or fake_pg3.Interface()
    return poly, StatsController(poly, 'stats', 'stats', 'System Stats')


def test_pg3_config_does_not_strip_the_drivers():
    """Regression: PG3 replaces node.drivers with its database copy on every
    config.  For a node it has just learned about that copy is empty, which
    used to leave every setDriver failing with 'Invalid driver'."""
    poly, node = _node()
    assert len(node.drivers) == len(all_drivers())

    poly.send_config(node, [])                 # the database knows nothing yet
    assert len(node.drivers) == len(all_drivers()), 'drivers were wiped'
    assert poly.addnode_calls >= 1, 'PG3 must be told the full driver set'

    node.setDriver('ST', 1)                    # used to raise / log an error
    assert node.getDriver('ST') == 1


def test_config_matching_the_database_does_not_re_add():
    poly, node = _node()
    poly.send_config(node, [])
    calls = poly.addnode_calls
    poly.send_config(node, poly.db['stats'])
    assert poly.addnode_calls == calls, 'no addNode loop'


def test_partial_config_repairs_itself():
    poly, node = _node()
    poly.send_config(node, [{'driver': 'ST', 'value': 1, 'uom': 2}])
    assert len(node.drivers) == len(all_drivers())
    node.setDriver('GV3', 42.5)
    assert node.getDriver('GV3') == 425, 'percent carries one decimal'


def test_values_are_scaled_to_the_editor_precision():
    poly, node = _node()
    poly.fire(poly.CUSTOMPARAMS, {'display': '+load_avg,+cpu_util,'
                                             '+system_uptime'})
    node.setDriver('GV0', 1.07)      # load average, prec 2
    node.setDriver('GV3', 12.34)     # percent, prec 1
    assert node.getDriver('GV0') == 107
    assert node.getDriver('GV3') == 123


def test_poll_reports_only_the_enabled_drivers():
    poly, node = _node()
    poly.send_config(node, [])
    poly.fire(poly.CUSTOMPARAMS, {'display': '+cpu_util,+mem_usage,-load_avg,'
                                             '-disk_capacity,-disk_iostats,'
                                             '-disk_io_util,-net_util,'
                                             '-net_errors,-cpu_temp,'
                                             '+system_uptime'})
    poly.fire(poly.START)
    time.sleep(0.2)
    poly.fire(poly.POLL, 'shortPoll')

    shown = {d for d, _, _ in profile.driver_layout(node.config)}
    assert 'GV3' in shown and 'GV0' not in shown
    off = [d['driver'] for d in node.drivers
           if d['driver'] not in shown and d['value'] != 0]
    assert off == [], 'disabled metrics must never be reported: %s' % off
    assert node.getDriver('ST') == 1
    poly.fire(poly.STOP)
    assert node.getDriver('ST') == 0


def test_shared_counters_are_sampled_once_per_poll():
    """Regression: net_util and net_errors used to re-sample and clobber each
    other's baseline, which pinned rx == tx and the error rate at zero."""
    from sysstats.metrics import Collector
    collector = Collector(config.parse({'display': '+net_util,+net_errors,'
                                                   '+disk_iostats'}))
    collector.collect()
    baseline = collector._net_io
    collector.collect()
    assert collector._net_io is not baseline, 'baseline must advance per poll'
    assert collector._net_sample is not None


def main():
    tests = [(name, obj) for name, obj in sorted(globals().items())
             if name.startswith('test_') and callable(obj)]
    failed = 0
    for name, test in tests:
        try:
            test()
            print('ok   %s' % name)
        except Exception as error:
            failed += 1
            print('FAIL %s: %s' % (name, error))
    print('\n%d passed, %d failed' % (len(tests) - failed, failed))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
