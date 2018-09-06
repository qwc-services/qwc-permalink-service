from flask import Flask, request, jsonify
from flask_restplus import Api, Resource, reqparse
from flask_jwt_extended import jwt_optional
import datetime
import hashlib
import random
import json
from urllib.parse import urlparse, parse_qs
from sqlalchemy.sql import text as sql_text

from qwc_services_core.api import CaseInsensitiveArgument
from qwc_services_core.database import DatabaseEngine
from qwc_services_core.jwt import jwt_manager


# Flask application
app = Flask(__name__)
api = Api(app, version='1.0', title='Permalink API',
          description='API for QWC Permalink service',
          default_label='Permalink operations', doc='/api/')

# disable verbose 404 error message
app.config['ERROR_404_HELP'] = False

# Setup the Flask-JWT-Extended extension
jwt = jwt_manager(app)

db_engine = DatabaseEngine()
configdb = db_engine.config_db()
table = "qwc_config.permalinks"

# request parser
createpermalink_parser = reqparse.RequestParser(argument_class=CaseInsensitiveArgument)
createpermalink_parser.add_argument('url', required=True)

resolvepermalink_parser = reqparse.RequestParser(argument_class=CaseInsensitiveArgument)
resolvepermalink_parser.add_argument('key', required=True)


@api.route('/createpermalink')
class CreatePermalink(Resource):

    @api.doc('createpermalink')
    @api.param('url', 'The URL for which to generate a permalink', 'query')
    @api.param('payload', 'A json document with the state to store in the permalink', 'body')
    @api.expect(createpermalink_parser)
    @jwt_optional
    def post(self):
        args = createpermalink_parser.parse_args()
        url = args['url']
        parts = urlparse(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        for key in query:
            query[key] = query[key][0]
        data = {
            "query": query,
            "state": request.json
        }

        # Insert into databse
        configconn = configdb.connect()
        datastr = json.dumps(data)
        hexdigest = hashlib.sha224(datastr.encode('utf-8')).hexdigest()[0:9]
        date = datetime.date.today().strftime(r"%Y-%m-%d")
        sql = sql_text("""
            INSERT INTO {table} (key, data, date)
            VALUES (:key, :data, :date)
        """.format(table=table))

        attempts = 0
        while attempts < 100:
            try:
                configconn.execute(sql, key=hexdigest, data=datastr, date=date)
                break
            except:
                pass
            hexdigest = hashlib.sha224((datastr + str(random.random())).encode('utf-8')).hexdigest()[0:9]
            attempts += 1
        configconn.close()

        # Return
        if attempts < 100:
            result = {
                "permalink": parts.scheme + "://" + parts.netloc + parts.path + "?k=" + hexdigest
            }
        else:
            result = {"message": "Failed to generate compact permalink"}
        return jsonify(**result)

@api.route('/resolvepermalink')
class ResolvePermalink(Resource):
    @api.doc('resolvepermalink')
    @api.param('key', 'The permalink key to resolve')
    @api.expect(resolvepermalink_parser)
    @jwt_optional
    def get(self):
        args = resolvepermalink_parser.parse_args()
        key = args['key']
        data = {}
        configconn = configdb.connect()
        sql = sql_text("""
            SELECT data
            FROM {table}
            WHERE key = :key
        """.format(table=table))
        try:
            data = json.loads(configconn.execute(sql, key=key).first().data)
        except:
            pass
        return jsonify(data)


if __name__ == "__main__":
    print("Starting Permalink service...")
    app.run(debug=True, port=5018)
