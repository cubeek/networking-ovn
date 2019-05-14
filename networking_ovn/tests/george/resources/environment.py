#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import json
import os
import threading

import fixtures
import netaddr
from neutron.agent.linux import ip_lib
from neutron.agent.linux import utils as n_utils
from neutron.tests.common import config_fixtures
from neutron_lib import exceptions
from oslo_log import log as logging
from oslo_utils import uuidutils

from networking_ovn.tests.george import base

LOG = logging.getLogger(__name__)


class ConfigFixture(config_fixtures.ConfigFileFixture):
    pass


class Container(fixtures.Fixture):
    def __init__(self, host, image, networks, debug=False):
        self.host = host
        self.image = image
        self.name = "{:s}-{:s}".format(image, uuidutils.generate_uuid())
        self.networks = networks or []
        self.debug = debug

    def _setUp(self):
        self.addCleanup(self.cleanup)
        self.start()

    def start(self):
        cmd = ['podman', 'run', '-d', '--name', self.name, '--mount',
               'type=bind,src=%s,target=/mnt/host' % self.host.host_dir,
               '--privileged=true']

        if self.debug:
            cmd.insert(1, '--log-level=debug')

        if self.networks:
            cmd.extend(['--network', ','.join([
                net.uuid for net in self.networks])])

        cmd.extend(['localhost/{:s}'.format(self.image)])

        try:
            n_utils.execute(
                cmd,
                run_as_root=True)
        except exceptions.ProcessExecutionError as pe:
            LOG.debug("Failed to start container %s: %s", self.name, pe)
            n_utils.execute(
                ['podman', 'rm', '-f', self.name],
                run_as_root=True, check_exit_code=False)
            raise

    def execute(self, cmd):
        cmd = ['podman', 'exec', self.name] + cmd
        return n_utils.execute(
            cmd,
            run_as_root=True)

    @property
    def inspect(self):
        if not hasattr(self, '_inspect'):
            cmd = ['podman', 'inspect', self.name]
            self._inspect = json.loads(
                n_utils.execute(
                    cmd,
                    run_as_root=True))[0]
        return self._inspect

    @property
    def network_settings(self):
        return self.inspect["NetworkSettings"]

    @property
    def hostname(self):
        return self.inspect["Config"]["Hostname"]

    @property
    def ip_wrapper(self):
        if not hasattr(self, '_ip_wrapper'):
            net_ns = self.network_settings["SandboxKey"].split('/')[-1]
            self._ip_wrapper = ip_lib.IPWrapper(net_ns)

        return self._ip_wrapper

    @staticmethod
    def clean_func(name):
        try:
            n_utils.execute(['podman', 'stop', '-t', '5', name],
                            run_as_root=True, check_exit_code=False)
            n_utils.execute(['podman', 'rm', '-f', name], run_as_root=True,
                            check_exit_code=False)
        except Exception as e:
            print(e)

    def cleanup(self):
        thread = threading.Thread(target=self.clean_func, args=(self.name,))
        thread.start()
        base.BaseGeorgeTestCase.threads.append(thread)

class Host(fixtures.Fixture):
    IMAGE_NAME = None
    BR_INT = 'br-int'

    def __init__(self, networks):
        self.container = Container(self, self.IMAGE_NAME, networks)

    def _setUp(self):
        self.uuid = uuidutils.generate_uuid()
        self.working_dir = self.useFixture(fixtures.TempDir()).path
        self.addCleanup(self.collect_logs)
        os.mkdir(self.host_dir)
        self.pre_configure()
        self.start()
        self.post_configure()

    def start(self):
        self.useFixture(self.container)

    @property
    def host_dir(self):
        return os.path.join(self.working_dir, 'host')

    @property
    def hostname(self):
        return self.container.hostname

    def pre_configure(self):
        raise NotImplementedError

    def post_configure(self):
        raise NotImplementedError

    @property
    def control_ip(self):
        return self._get_device_ip(device_index=0)

    @property
    def tunnel_ip(self):
        return self._get_device_ip(device_index=1)

    def _get_device_ip(self, device_index):
        network = netaddr.IPNetwork(
            self.container.ip_wrapper.get_devices(
                )[device_index].addr.list()[0]['cidr'])
        return str(network.ip)

    def collect_logs(self):
        pass

    def is_ready(self):
        pass


class NeutronServerOvn(Host):
    IMAGE_NAME = 'neutron-server-ovn'

    def __init__(self, database_url, networks):
        super(NeutronServerOvn, self).__init__(networks)
        self.database_url = str(database_url)

    def pre_configure(self):
        config_dict = {
            'DEFAULT': {
                'host': self.container.name,
                'api_paste_config': '/usr/local/etc/neutron/api-paste.ini',
                'core_plugin': 'ml2',
                'service_plugins':
                    'networking_ovn.l3.l3_ovn.OVNL3RouterPlugin,trunk',
                'auth_strategy': 'noauth',
                'debug': 'True',
                'api_workers': '40',
                'rpc_workers': '0',
                # TODO(jlibosva): Configure rabbit connection when DHCP agent
                #                 is present.
                'transport_url': 'fake:/',
            },
            'database': {
                'connection': self.database_url,
            },
            'ml2': {
                'mechanism_drivers': 'ovn,logger',
                'type_drivers': 'local,flat,vlan,geneve',
                'tenant_network_types': 'geneve',
                'extension_drivers': 'port_security,dns',
            },
            'oslo_concurrency': {
                'lock_path': '$state_path/lock',
            },
            'ml2_type_geneve': {
                'max_header_size': '38',
                'vni_ranges': '1:65536',
            },
            'ovn': {
                'ovn_nb_connection': 'tcp:127.0.0.1:6641',
                'ovn_sb_connection': 'tcp:127.0.0.1:6642',
                'neutron_sync_mode': 'log',
                'ovn_l3_scheduler': 'leastloaded',
            },
            'securitygroup': {
                'enable_security_group': 'true',
            },
        }
        self.useFixture(
            ConfigFixture('neutron.conf', config_dict, self.host_dir))

    def post_configure(self):
        cmd = [
            'ovs-vsctl', 'set', 'open', '.',
            'external-ids:ovn-bridge=%s' % self.BR_INT,
            '--', 'set', 'open', '.',
            'external-ids:ovn-remote=unix:'
            '/usr/var/run/openvswitch/ovnsb_db.sock',
            '--', 'set', 'open', '.',
            'external-ids:ovn-encap-ip=%(local_ip)s' % {
                'local_ip': self.tunnel_ip},
            '--', 'set', 'open', '.', 'external-ids:ovn-encap-type=geneve']
        self.container.execute(cmd)


class NeutronCompute(Host):
    IMAGE_NAME = 'neutron-ovn-controller'

    def __init__(self, networks, controller_ip):
        super(NeutronCompute, self).__init__(networks)
        self.controller_ip = controller_ip

    def pre_configure(self):
        pass

    def post_configure(self):
        def get_cmd(port):
            return [
                'ovs-vsctl', 'set', 'open', '.',
                'external-ids:ovn-bridge=%s' % self.BR_INT,
                '--', 'set', 'open', '.',
                'external-ids:ovn-remote=''tcp:%(controller_ip)s:%(port)d' % {
                    'controller_ip': self.controller_ip,
                    'port': port
                }, '--', 'set', 'open', '.',
                'external-ids:ovn-encap-ip=%(local_ip)s' % {
                    'local_ip': self.tunnel_ip},
                '--', 'set', 'open', '.', 'external-ids:ovn-encap-type=geneve',
            ]
        for port in (6642, 6648, 6642):
            cmd = get_cmd(port)
            self.container.execute(cmd)

    def vif_plug(self, namespace, port):
#        vm_port_name = 'vm-%s' % port['id'][:11]
        iface_name = 'tap-%s' % port['id'][:11]
#        self.container.execute(
#            ['ip', 'l', 'add', iface_name, 'type', 'veth', 'peer',
#             'name', vm_port_name]o)
        # NOTE(jlibosva): ovs-vsctl considers colons to be a separator. When
        #                 putting a mac address, we need to escape all colons
        mac_address = port['mac_address'].replace(':', '\:')
        self.container.execute(
            ['ovs-vsctl', 'add-port', 'br-int', iface_name, '--',
             'set', 'Interface', iface_name, 'type=internal', '--',
             'set', 'Interface', iface_name,
             'external_ids:iface-id=%s' % port['id'], '--',
             'set', 'Interface', iface_name, 'mac=%s' % mac_address])
        self.container.execute(
            ['ip', 'l', 's', iface_name, 'netns', namespace])
