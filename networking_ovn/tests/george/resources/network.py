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

import os
import json

import fixtures
from neutron.agent.linux import utils as n_utils
from oslo_utils import uuidutils

CNI_NETWORK_DIR = '/etc/cni/net.d'

class Network(fixtures.Fixture):
    def __init__(self, name, subnet, gateway=None, priority=50):
        self.name = name
        self.subnet = subnet
        self.gateway = gateway
        self.priority = priority
        self.uuid = uuidutils.generate_uuid()
        self.br_name = "br-%s" % self.uuid[:11]
        self.filepath = os.path.join(CNI_NETWORK_DIR, '%s-%s-%s.conflist' % (
            priority, name, self.uuid))

    def _make_config(self):
        subnet = {'subnet': self.subnet}
        if self.gateway:
            subnet['gateway'] = self.gateway

        config = {
            "cniVersion": "0.4.0",
            "name": self.uuid,
            "plugins": [
                {"type": "bridge",
                    "bridge": self.br_name,
                 "isGateway": bool(self.gateway),
                 "ipMasq": True,
                 "ipam": {
                     "type": "host-local",
                     "routes": [
                         {"dst": "0.0.0.0/0"}
                     ],
                     "ranges": [[subnet]]
                 }
                },
                {"type": "portmap",
                 "capabilities": {
                    "portMappings": True}
                },
                {"type": "firewall",
                 "backend": "iptables"
                }
            ]
        }
        return config

    def _setUp(self):
        config = self._make_config()
        self.addCleanup(self._cleanup)
        self._write_config(config)

    def _write_config(self, config):
        with open(self.filepath, 'w') as configfile:
            json.dump(config, configfile, indent=2)

    def _cleanup(self):
        os.remove(self.filepath)
        n_utils.execute(['ip', 'l', 's', 'down', self.br_name],
            run_as_root=True, check_exit_code=False)
        n_utils.execute(['brctl', 'delbr', self.br_name],
            run_as_root=True, check_exit_code=False)
