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

from concurrent import futures
import os
import time

from neutron.common import utils as n_common_utils
from neutron.tests import base as tests_base
from neutron.tests.fullstack.resources import client
from neutron.tests.unit import testlib_api
from neutronclient.common import exceptions as nc_exc
from neutronclient.v2_0 import client as n_client
from oslo_config import cfg

from networking_ovn.tests import base
from networking_ovn.tests.george.resources import environment
from networking_ovn.tests.george.resources import network

DEFAULT_LOG_DIR = os.path.join(
    os.environ.get('OS_LOG_PATH', '/tmp'), 'george-logs')


def setup_privsep():
    privsep_executable_path = os.path.join(
        os.getenv('OS_VENV'), 'bin', 'privsep-helper')
    cfg.CONF.set_override(
        'helper_command',
        'sudo -E %s' % privsep_executable_path, 'privsep')


class EnvironmentException(Exception):
    pass


class BaseGeorgeTestCase(testlib_api.MySQLTestCaseMixin,
                         testlib_api.SqlTestCase,
                         base.TestCase):
    BUILD_WITH_MIGRATIONS = True
    COMPUTES_NUM = None
    threads = []

    def setUp(self):
        self._t_start = time.time()
        super(BaseGeorgeTestCase, self).setUp()
        self._t_db = time.time()
        def print_time():
            if hasattr(self, '_t_ping'):
                teardown = time.time()
                print("It took %.3f seconds to tear down the whole env" %
                      (teardown - self._t_ping))

        print("It took %.3f seconds to create DB" %
              (self._t_db - self._t_start))
        self.addCleanup(print_time)
        self.addCleanup(self._wait_for_env_teardown)
        if not self.COMPUTES_NUM:
            raise RuntimeError("COMPUTES_NUM is not set")

        self.setup_logging()
        setup_privsep()
        self._t_setup = time.time()
        print("It took %.3f seconds to setup logging and privsep" %
              (self._t_setup - self._t_db))
        self._create_environment()

    def _wait_for_env_teardown(self):
        for thread in self.threads:
            thread.join()

    def _create_environment(self):
        networks = [
            self.useFixture(network.Network('ctlplane', '192.168.0.0/24',
                                            gateway='192.168.0.1')),
            self.useFixture(network.Network('tunnelnet', '192.168.1.0/24'))]

        database_url = str(self.engine.url).replace('localhost', '192.168.0.1')
        self.server = environment.NeutronServerOvn(database_url, networks)
        self.useFixture(self.server)

        self.computes = [
            environment.NeutronCompute(networks, self.server.control_ip)
            for i in range(self.COMPUTES_NUM)]

        with futures.ThreadPoolExecutor(
                max_workers=self.COMPUTES_NUM) as executor:
            for compute in self.computes:
                executor.submit(self.useFixture, compute)

        self._t_containers_built = time.time()
        print("It took %.3f seconds to start all the containers" %
              (self._t_containers_built - self._t_setup))

        url = "http://%s:9696" % self.server.control_ip
        self.safe_client = self.useFixture(
            client.ClientFixture(
                n_client.Client(auth_strategy="noauth", endpoint_url=url,
                                timeout=30)))

        self.wait_until_env_is_up()
        self._t_env_up = time.time()
        print("It took %.3f seconds for environment to come up" %
              (self._t_env_up - self._t_containers_built))

    def wait_until_env_is_up(self):
        n_common_utils.wait_until_true(
            self._env_is_ready,
            timeout=60,
            sleep=5,
            exception=EnvironmentException(
                "The environment didn't come up."))

    def _env_is_ready(self):
        try:
            running_agents = len(
                self.safe_client.client.list_agents()['agents'])
            agents_count = len(self.computes)
            return running_agents == agents_count
        except nc_exc.NeutronClientException:
            return False

    def setup_logging(self):
        test_log_dir = os.path.join(DEFAULT_LOG_DIR, self.id())
        tests_base.setup_test_logging(
            cfg.CONF, test_log_dir, "testrun.txt")
