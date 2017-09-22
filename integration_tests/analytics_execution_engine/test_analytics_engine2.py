'''Test the store handler by flushing it, then writing and reading from it.

CAUTION: The database with the last possible index (typically 15) in the store is used. If it ever
contains any data, that gets wiped out!
'''

from __future__ import absolute_import

from os.path import expanduser
from pathlib import Path
from configparser import ConfigParser
import pytest

import datacube.analytics.job_result
from datacube.analytics.utils.store_handler import *
from datacube.analytics.analytics_engine2 import AnalyticsEngineV2

# Skip all tests if redis cannot be imported
redis = pytest.importorskip('redis')


DEFAULT_CONFIG_FILES = [expanduser('~/.datacube.conf'),
                        expanduser('~/.datacube_integration.conf'),
                        str(Path(__file__).parent.parent.joinpath('agdcintegration.conf')),
                        str(Path(__file__).parent.joinpath('./.datacube.conf')),
                        str(Path(__file__).parent.joinpath('./.datacube_integration.conf'))]
'''Config files from which to pull redis config. The `redis` section in any such file gets merged if
present, later files overwriting earlier ones if the same fields are set again.'''

DEFAULT_REDIS_CONFIG = {
    'host': '127.0.0.1',
    'port': 6379,
    'db': 0,
    'password': None
}
'''Default redis config. It gets merged with/overwritten by the config files.'''


@pytest.fixture(scope='module')
def redis_config():
    '''Retrieve and test the redis configuration.

    Configuration is retrieved from `DEFAULT_CONFIG_FILES` or `DEFAULT_REDIS_CONFIG`, and then ping
    the server to check whether it's alive. If so, the config is returned. Otherwise, None is
    returned and all tests in this file are skipped.
    '''
    # Source config
    redis_config = DEFAULT_REDIS_CONFIG
    config = ConfigParser()
    config.read(DEFAULT_CONFIG_FILES)
    if 'redis' in config:
        redis_config.update(config['redis'])
    # Test server
    try:
        store = redis.StrictRedis(**redis_config)
        if store.ping():
            # Select the DB with last index in the current store
            redis_config['db'] = int(store.config_get('databases')['databases']) - 1
            print('\nUsing redis config: {}'.format(redis_config))
            return redis_config
    except redis.exceptions.ConnectionError as conn_error:
        pass
    # Skill all tests
    pytest.skip('No running redis server found at {}'.format(redis_config))
    return None


@pytest.fixture(scope='module')
def store_handler(redis_config):
    '''Connect to the store and flushes the last DB.

    CAUTION: The database with the last possible index (typically 15) in the store is used. If it
    contains any data, that gets wiped out!

    That DB gets wiped again at the end of the tests.
    '''
    store_handler = StoreHandler(**redis_config)
    yield store_handler
    store_handler._store.flushdb()


@pytest.fixture(scope='module')
def user_data():
    users = {}
    for user_no in range(2):
        jobs = []
        for job_no in range(6):
            def function(user_no=user_no, job_no=job_no):
                return 'User {:03d}, job {:03d}'.format(user_no, job_no)
            jobs.append({
                'job_type': FUNCTION_TYPES[job_no % 3],
                'function': function,
                'data': 'Data for {:03d}-{:03d}'.format(user_no, job_no),
                'results': [{
                    'result_type': RESULT_TYPES[result_no % 3],
                    'descriptor': 'Descriptor for {:03d}-{:03d}-{:03d}'.format(user_no, job_no, result_no)
                } for result_no in range(3)]
                })
        users['user{:03d}'.format(user_no)] = jobs
    return users


def test_submit_job(store_handler, redis_config):
    '''Test the submission of a job.'''
    store_handler._store.flushdb()

    def function():
        return 'Simple function'
    data = {'data': 'Simple data'}
    engine = AnalyticsEngineV2(redis_config)
    jros = engine.submit_python_function(function, data)
    # Assuming elements are created in deterministic order
    assert jros[0].job.id == 1
    assert jros[0].results.datasets['blue'].to_dict()['id'] == 1
    assert jros[0].results.datasets['blue'].to_dict()['base_name'] == 'jro_test_blue'

    # Leave time to fake workers to complete their tasks
    from time import sleep
    sleep(0.4)
    store_handler._store.flushdb()