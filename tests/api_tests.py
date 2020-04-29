import unittest
from urllib.parse import urlparse, parse_qs, urlencode

from flask import Response, json
from flask.testing import FlaskClient
from flask_jwt_extended import JWTManager, create_access_token

import server


class ApiTestCase(unittest.TestCase):
    """Test case for server API"""

    def setUp(self):
        server.app.testing = True
        self.app = FlaskClient(server.app, Response)
        JWTManager(server.app)

    def tearDown(self):
        pass

    # submit query
    def test_permalink(self):
        testUrl = 'http://www.example.com/?arg=value'
        query = urlencode({'url': testUrl})
        data = {
            "field1": "value1",
            "field2": "value2"
        }
        response = self.app.post('/createpermalink?' + query, data=json.dumps(data),
                                 content_type='application/json')
        self.assertEqual(200, response.status_code, "Status code is not OK")

        response_data = json.loads(response.data)
        self.assertTrue(response_data)
        self.assertIn('permalink', response_data, 'Response has no permalink field')

        orig_parts = urlparse(testUrl)
        resp_parts = urlparse(response_data['permalink'])
        self.assertEqual(orig_parts.scheme, resp_parts.scheme, "Permalink URL scheme mismatches")
        self.assertEqual(orig_parts.netloc, resp_parts.netloc, "Permalink URL netloc mismatches")
        self.assertEqual(orig_parts.path, resp_parts.path, "Permalink URL path mismatches")
        self.assertIn('k', parse_qs(resp_parts.query), "Permalink has no k query parameter")

        query = urlencode({'key': parse_qs(resp_parts.query)['k'][0]})
        response = self.app.get('/resolvepermalink?' + query)
        self.assertEqual(200, response.status_code, "Status code is not OK")

        response_data = json.loads(response.data)
        self.assertTrue(response_data)
        self.assertIn('query', response_data, 'Response has no query field')
        self.assertIn('state', response_data, 'Response has no state field')
        self.assertEqual({'arg': 'value'}, response_data['query'], 'Response query mismatch')
        self.assertEqual(data, response_data['state'], 'Response state mismatch')
