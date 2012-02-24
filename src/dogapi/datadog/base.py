import httplib
import os
import logging
import re
import socket
import ssl
import time
import urllib2
from contextlib import contextmanager
from pprint import pformat
from urllib import urlencode

try:
    import simplejson as json
except ImportError:
    import json

http_log = logging.getLogger('dogapi.http')
log = logging.getLogger('dogapi')

class ClientError(Exception): pass
class HttpTimeout(Exception): pass
class HttpBackoff(Exception): pass
timeout_exceptions = (socket.timeout, ssl.SSLError)

class BaseDatadog(object):
    def __init__(self, api_key=None, application_key=None, api_version='v1', api_host=None, timeout=2, max_timeouts=3, backoff_period=300, swallow=True, use_ec2_instance_id=False):
        self.api_host = api_host or os.environ.get('DATADOG_HOST', 'https://app.datadoghq.com')

        # http transport params
        self.backoff_period = backoff_period
        self.max_timeouts = max_timeouts
        self.backoff_timestamp = None
        self.timeout_counter = 0

        self.api_key = api_key
        self.api_version = api_version
        self.application_key = application_key
        self.timeout = timeout
        self.swallow = swallow
        self._default_host = socket.gethostname()
        self._use_ec2_instance_id = None
        self.use_ec2_instance_id = use_ec2_instance_id
    
    def request(self, method, path, body=None, **params):
        if self.api_key:
            params['api_key'] = self.api_key
        if self.application_key:
            params['application_key'] = self.application_key
        path = "/api/%s/%s" % (self.api_version, path.lstrip('/'))
        try:
            if not self._should_submit():
                raise HttpBackoff("Too many timeouts. Won't try again for {1} seconds.".format(*self._backoff_status()))
            
            match = re.match('^(https?)://(.*)', self.api_host)
            http_conn_cls = httplib.HTTPSConnection

            if match:
                host = match.group(2)
                if match.group(1) == 'http':
                    http_conn_cls = httplib.HTTPConnection

            conn = http_conn_cls(host)
            url = "/%s?%s" % (path.lstrip('/'), urlencode(params))
            
            headers = {}
            if isinstance(body, dict):
                body = json.dumps(body)
                headers['Content-Type'] = 'application/json'
                    
            try:
                start_time = time.time()
                try:
                    conn.request(method, url, body, headers)
                except timeout_exceptions:
                    self.report_timeout()
                    raise HttpTimeout('%s %s timed out after %d seconds.' % (method, url, self.timeout))
                
                response = conn.getresponse()
                duration = round((time.time() - start_time) * 1000., 4) 
                log.info("%s %s %s (%sms)" % (response.status, method, url, duration))
                response_str = response.read()
                if response_str:
                    try:
                        response_obj = json.loads(response_str)
                    except ValueError:
                        raise ValueError('Invalid JSON response: {0}'.format(response_str))
                    
                    if response_obj and 'errors' in response_obj:
                        raise ClientError(response_obj['errors'])
                else:
                    response_obj = {}
                return response_obj
            finally:
                conn.close()
        except (HttpTimeout, HttpBackoff), e:
            if self.swallow:
                log.error(str(e))
            else:
                raise            

    def use_ec2_instance_id():
        def fget(self):
            return self._use_ec2_instance_id
        
        def fset(self, value):
            self._use_ec2_instance_id = value

            if value:
                try:
                    # Remember the previous default timeout
                    old_timeout = socket.getdefaulttimeout()

                    # Try to query the EC2 internal metadata service, but fail fast
                    socket.setdefaulttimeout(0.25)

                    try:
                        host = urllib2.urlopen(urllib2.Request('http://169.254.169.254/latest/meta-data/instance-id')).read()
                    finally:
                        # Reset the previous default timeout
                        socket.setdefaulttimeout(old_timeout)
                except Exception:
                    host = socket.gethostname()

                self._default_host = host
            else:
                self._default_host = socket.gethostname()
        
        def fdel(self):
            del self._use_ec2_instance_id
        
        return locals()
    use_ec2_instance_id = property(**use_ec2_instance_id())

    def report_timeout(self):
        """ Report to the manager that a timeout has occurred.
        """
        self.timeout_counter += 1


    # Private functions

    def _should_submit(self):
        """ Returns True if we're in a state where we should make a request
        (backoff expired, no backoff in effect), false otherwise.
        """
        now = time.time()
        should_submit = False

        # If we're not backing off, but the timeout counter exceeds the max
        # number of timeouts, then enter the backoff state, recording the time
        # we started backing off
        if not self.backoff_timestamp and self.timeout_counter >= self.max_timeouts:
            log.info("Max number of dogapi timeouts exceeded, backing off for {0} seconds".format(self.backoff_period))
            self.backoff_timestamp = now
            should_submit = False

        # If we are backing off but the we've waiting sufficiently long enough
        # (backoff_retry_age), exit the backoff state and reset the timeout
        # counter so that we try submitting metrics again
        elif self.backoff_timestamp:
            backed_off_time, backoff_time_left = self._backoff_status()
            if backoff_time_left < 0:
                log.info("Exiting backoff state after {0} seconds, will try to submit metrics again".format(backed_off_time))
                self.backoff_timestamp = None
                self.timeout_counter = 0
                should_submit = True
            else:
                log.info("In backoff state, won't submit metrics for another {0} seconds".format(backoff_time_left))
                should_submit = False
        else:
            should_submit = True

        return should_submit

    def _backoff_status(self):
        now = time.time()
        backed_off_time = now - self.backoff_timestamp
        backoff_time_left = self.backoff_period - backed_off_time
        return round(backed_off_time, 2), round(backoff_time_left, 2)

