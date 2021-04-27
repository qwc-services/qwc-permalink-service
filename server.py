from flask import Flask, request, jsonify, make_response
from flask_restx import Api, Resource, reqparse
from flask_jwt_extended import jwt_optional, get_jwt_identity
import datetime
import hashlib
import random
import json
import os
from urllib.parse import urlparse, parse_qs
from sqlalchemy.sql import text as sql_text

from qwc_services_core.api import CaseInsensitiveArgument
from qwc_services_core.database import DatabaseEngine
from qwc_services_core.jwt import jwt_manager
from qwc_services_core.tenant_handler import TenantHandler
from qwc_services_core.runtime_config import RuntimeConfig


# Flask application
app = Flask(__name__)
api = Api(app, version='1.0', title='Permalink API',
          description='API for QWC Permalink service',
          default_label='Permalink operations', doc='/api/')

bk = api.namespace('bookmarks', description='Bookmarks operations')

# disable verbose 404 error message
app.config['ERROR_404_HELP'] = False

# Setup the Flask-JWT-Extended extension
jwt = jwt_manager(app, api)

tenant_handler = TenantHandler(app.logger)
config_handler = RuntimeConfig("permalink", app.logger)
db_engine = DatabaseEngine()


# request parser
createpermalink_parser = reqparse.RequestParser(argument_class=CaseInsensitiveArgument)
createpermalink_parser.add_argument('url', required=True)

resolvepermalink_parser = reqparse.RequestParser(argument_class=CaseInsensitiveArgument)
resolvepermalink_parser.add_argument('key', required=True)

userbookmark_parser = reqparse.RequestParser(argument_class=CaseInsensitiveArgument)
userbookmark_parser.add_argument('url', required=True)
userbookmark_parser.add_argument('description')

def db_conn():
    tenant = tenant_handler.tenant()
    config = config_handler.tenant_config(tenant)

    db_url = config.get('db_url', 'postgresql:///?service=qwc_configdb')
    permalinks_table = config.get('permalinks_table', 'qwc_config.permalinks')
    user_permalink_table = config.get(
        'user_permalink_table', 'qwc_config.user_permalinks')
    user_bookmark_table = config.get('user_bookmark_table', 'qwc_config.user_bookmarks')

    db = db_engine.db_engine(db_url)
    conn = db.connect()
    return (conn, permalinks_table, user_permalink_table, user_bookmark_table)


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
        configconn, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        datastr = json.dumps(data)
        hexdigest = hashlib.sha224(datastr.encode('utf-8')).hexdigest()[0:9]
        date = datetime.date.today().strftime(r"%Y-%m-%d")
        sql = sql_text("""
            INSERT INTO {table} (key, data, date)
            VALUES (:key, :data, :date)
        """.format(table=permalinks_table))

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
        configconn, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        sql = sql_text("""
            SELECT data
            FROM {table}
            WHERE key = :key
        """.format(table=permalinks_table))
        try:
            data = json.loads(configconn.execute(sql, key=key).first().data)
        except:
            pass
        return jsonify(data)


@api.route('/userpermalink')
class UserPermalink(Resource):
    @api.doc('getuserpermalink')
    @jwt_optional
    def get(self):
        username = get_jwt_identity()
        if not username:
            return jsonify({})

        configconn, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        sql = sql_text("""
            SELECT data
            FROM {table}
            WHERE username = :user
        """.format(table=user_permalink_table))
        try:
            data = json.loads(configconn.execute(sql, user=username).first().data)
        except:
            data = {}
        return jsonify(data)

    @api.doc('postuserpermalink')
    @api.param('url', 'The URL for which to generate a permalink', 'query')
    @api.param('payload', 'A json document with the state to store in the permalink', 'body')
    @api.expect(createpermalink_parser)
    @jwt_optional
    def post(self):
        username = get_jwt_identity()
        if not username:
            return jsonify({"success": False})

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
        conn, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        datastr = json.dumps(data)
        date = datetime.date.today().strftime(r"%Y-%m-%d")
        sql = sql_text("""
            INSERT INTO {table} (username, data, date)
            VALUES (:user, :data, :date)
            ON CONFLICT (username)
            DO
            UPDATE
            SET data = :data, date = :date
        """.format(table=user_permalink_table))

        conn.execute(sql, user=username, data=datastr, date=date)
        conn.close()

        return jsonify({"success": True})

@bk.route('/')
class UserBookmarksList(Resource):
    @bk.doc('getbookmarks')
    @jwt_optional
    def get(self):
        username = get_jwt_identity()
        if not username:
            return jsonify([])

        conn, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        sql = sql_text("""
            SELECT data, key, description
            FROM {table}
            WHERE username = :user
        """.format(table=user_bookmark_table))
        try:
            data = []
            result = conn.execute(sql, user=username)
            for row in result:
                bookmark = {}
                bookmark['data'] = json.loads(row.data)
                bookmark['key'] = row.key
                bookmark['description'] = row.description
                data.append(bookmark)
        except:
            data = []
        return jsonify(data)

    @bk.doc('addbookmark')
    @bk.param('url', 'The URL for which to generate a bookmark', 'query')
    @bk.param('payload', 'A json document with the state to store in the bookmark', 'body')
    @bk.param('description', 'Description to store in the bookmark', 'query')
    @bk.expect(userbookmark_parser)    
    @jwt_optional
    def post(self):
        username = get_jwt_identity()
        if not username:
            return jsonify({"success": False})
        
        args = userbookmark_parser.parse_args()
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
        conn, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        datastr = json.dumps(data)
        hexdigest = hashlib.sha224(datastr.encode('utf-8')).hexdigest()[0:9]
        date = datetime.date.today().strftime(r"%Y-%m-%d")
      
        description = args['description']
        sql = sql_text("""
            INSERT INTO {table} (username, data, key, date, description)
            VALUES (:user, :data, :key, :date, :description)
            ON CONFLICT (username,key) WHERE username = :user
            DO
            UPDATE
            SET data = :data, date = :date, description = :description
        """.format(table=user_bookmark_table))

        attempts = 0
        while attempts < 100:
            try:
                conn.execute(sql, user=username, data=datastr, key=hexdigest, date=date, description=description)
                break
            except:
                pass
            hexdigest = hashlib.sha224((datastr + str(random.random())).encode('utf-8')).hexdigest()[0:9]
            attempts += 1
        
        conn.close()

        return jsonify({"success": True})

@bk.route('/<key>')
class UserBookmark(Resource):
    @bk.doc('getbookmark')
    @jwt_optional
    def get(self, key):
        username = get_jwt_identity()
        if not username:
            return jsonify({"success": False})

        conn, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        sql = sql_text("""
            SELECT data
            FROM {table}
            WHERE username = :user and key = :key
        """.format(table=user_bookmark_table))
        try:
            data = json.loads(conn.execute(sql, user=username, key=key).first().data)              
        except:
            data = {}
        return jsonify(data)

    @bk.doc('deletebookmark')
    @jwt_optional
    def delete(self, key):
        username = get_jwt_identity()
        if not username:
            return jsonify({"success": False})
        
        # Delete into databse
        conn, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        sql = sql_text("""
            DELETE FROM {table}
            WHERE key = :key and username = :username
        """.format(table=user_bookmark_table))

        conn.execute(sql, key=key, username=username)
        conn.close()

        return jsonify({"success": True})

    @bk.doc('setbookmark')
    @bk.param('url', 'The URL for which to generate a bookmark', 'query')
    @bk.param('payload', 'A json document with the state to store in the bookmark', 'body')
    @bk.param('description', 'Description to store in the bookmark', 'query')
    @bk.expect(userbookmark_parser)    
    @jwt_optional
    def put(self, key):
        username = get_jwt_identity()
        if not username:
            return jsonify({"success": False})
        
        args = userbookmark_parser.parse_args()
        url = args['url']
        parts = urlparse(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        for k in query:
            query[k] = query[k][0]
        data = {
            "query": query,
            "state": request.json
        }

        # Update into databse
        conn, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        datastr = json.dumps(data)
        date = datetime.date.today().strftime(r"%Y-%m-%d")
      
        description = args['description']
        sql = sql_text("""
            UPDATE {table}
            SET data = :data, date = :date, description = :description
            WHERE username = :user and key = :key
        """.format(table=user_bookmark_table))

        conn.execute(sql, user=username, data=datastr, key=key, date=date, description=description)
        conn.close()

        return jsonify({"success": True})

""" readyness probe endpoint """
@app.route("/ready", methods=['GET'])
def ready():
    return jsonify({"status": "OK"})


""" liveness probe endpoint """
@app.route("/healthz", methods=['GET'])
def healthz():
    try:
        db_conn()
    except Exception as e:
        return make_response(jsonify(
            {"status": "FAIL", "cause":
                str(e)}), 500)

    return jsonify({"status": "OK"})


if __name__ == "__main__":
    print("Starting Permalink service...")
    from flask_cors import CORS
    CORS(app)
    app.run(debug=True, port=5018)
