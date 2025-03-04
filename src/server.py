from flask import Flask, request, jsonify, make_response
from flask_restx import Api, Resource, reqparse
import datetime
import hashlib
import random
import json
import time
from urllib.parse import urlparse, parse_qs
from sqlalchemy.sql import text as sql_text

from qwc_services_core.auth import auth_manager, optional_auth, get_identity, get_username
from qwc_services_core.api import CaseInsensitiveArgument
from qwc_services_core.database import DatabaseEngine
from qwc_services_core.tenant_handler import (
    TenantHandler, TenantPrefixMiddleware, TenantSessionInterface)
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
jwt = auth_manager(app, api)

tenant_handler = TenantHandler(app.logger)
app.wsgi_app = TenantPrefixMiddleware(app.wsgi_app)
app.session_interface = TenantSessionInterface()

config_handler = RuntimeConfig("permalink", app.logger)
db_engine = DatabaseEngine()


# request parser
createpermalink_parser = reqparse.RequestParser(argument_class=CaseInsensitiveArgument)
createpermalink_parser.add_argument('url', required=False)

resolvepermalink_parser = reqparse.RequestParser(argument_class=CaseInsensitiveArgument)
resolvepermalink_parser.add_argument('key', required=True)

userbookmark_parser = reqparse.RequestParser(argument_class=CaseInsensitiveArgument)
userbookmark_parser.add_argument('url', required=False)
userbookmark_parser.add_argument('description')

def db_conn():
    tenant = tenant_handler.tenant()
    config = config_handler.tenant_config(tenant)

    db_url = config.get('db_url', 'postgresql:///?service=qwc_configdb')
    qwc_config_schema = config.get('qwc_config_schema', 'qwc_config')

    permalinks_table = config.get('permalinks_table', qwc_config_schema + '.permalinks')
    user_permalink_table = config.get(
        'user_permalink_table', qwc_config_schema + '.user_permalinks')
    user_bookmark_table = config.get('user_bookmark_table', qwc_config_schema + '.user_bookmarks')
    store_bookmarks_by_userid = config.get('store_bookmarks_by_userid', True)
    if store_bookmarks_by_userid:
        users_table = f'"{qwc_config_schema}"."users"'
    else:
        users_table = None

    db = db_engine.db_engine(db_url)
    return (db, users_table, permalinks_table, user_permalink_table, user_bookmark_table)


@api.route('/createpermalink')
class CreatePermalink(Resource):

    @api.doc('createpermalink')
    @api.param('url', 'The URL for which to generate a permalink', 'query')
    @api.param('payload', 'A json document with the state to store in the permalink', 'body')
    @api.expect(createpermalink_parser)
    @optional_auth
    def post(self):
        args = createpermalink_parser.parse_args()

        tenant = tenant_handler.tenant()
        config = config_handler.tenant_config(tenant)
        self.default_expiry_period = config.get('default_expiry_period', None)

        state = request.json
        if "url" in state:
            url = state["url"]
            del state["url"]
        elif "url" in args:
            url = args['url']
        else:
            api.abort(400, "No URL specified")

        parts = urlparse(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        for key in query:
            query[key] = query[key][0]
        data = {
            "query": query,
            "state": state
        }

        # Insert into databse
        db_engine, users_table, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        datastr = json.dumps(data)
        hexdigest = hashlib.sha224((datastr + str(time.time())).encode('utf-8')).hexdigest()[0:9]
        date = datetime.date.today().strftime(r"%Y-%m-%d")
        expires = None
        if self.default_expiry_period:
            delta = datetime.timedelta(days=self.default_expiry_period)
            expires = (datetime.date.today() + delta).strftime(r"%Y-%m-%d")

        sql = sql_text("""
            INSERT INTO {table} (key, data, date, expires)
            VALUES (:key, :data, :date, :expires)
        """.format(table=permalinks_table))

        attempts = 0
        while attempts < 100:
            try:
                with db_engine.begin() as connection:
                    connection.execute(sql, {"key": hexdigest, "data": datastr, "date": date, "expires": expires})
                break
            except:
                pass
            hexdigest = hashlib.sha224((datastr + str(random.random())).encode('utf-8')).hexdigest()[0:9]
            attempts += 1

        # Delete permalinks past expiry date
        sql = sql_text("""
            DELETE FROM {table}
            WHERE expires < CURRENT_DATE
        """.format(table=permalinks_table))
        with db_engine.begin() as connection:
            connection.execute(sql)

        # Return
        if attempts < 100:
            result = {
                "permalink": parts.scheme + "://" + parts.netloc + parts.path + "?k=" + hexdigest,
                "expires": expires
            }
        else:
            result = {"message": "Failed to generate compact permalink"}
        return jsonify(**result)


@api.route('/resolvepermalink')
class ResolvePermalink(Resource):
    @api.doc('resolvepermalink')
    @api.param('key', 'The permalink key to resolve')
    @api.expect(resolvepermalink_parser)
    @optional_auth
    def get(self):
        args = resolvepermalink_parser.parse_args()
        key = args['key']
        data = {}
        db_engine, users_table, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        sql = sql_text("""
            SELECT data
            FROM {table}
            WHERE key = :key AND (expires IS NULL OR expires >= CURRENT_DATE)
        """.format(table=permalinks_table))
        try:
            with db_engine.connect() as connection:
                data = json.loads(connection.execute(sql, {"key": key}).mappings().first()["data"])
        except:
            pass
        return jsonify(data)


@api.route('/userpermalink')
class UserPermalink(Resource):
    @api.doc('getuserpermalink')
    @optional_auth
    def get(self):
        username = get_username(get_identity())
        if not username:
            return jsonify({})

        db_engine, users_table, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        sql = sql_text("""
            SELECT data
            FROM {table}
            WHERE username = :user
        """.format(table=user_permalink_table))
        try:
            with db_engine.connect() as connection:
                data = json.loads(connection.execute(sql, {"user": username}).mappings().first()["data"])
        except:
            data = {}
        return jsonify(data)

    @api.doc('postuserpermalink')
    @api.param('url', 'The URL for which to generate a permalink', 'query')
    @api.param('payload', 'A json document with the state to store in the permalink', 'body')
    @api.expect(createpermalink_parser)
    @optional_auth
    def post(self):
        username = get_username(get_identity())
        if not username:
            return jsonify({"success": False})

        args = createpermalink_parser.parse_args()
        state = request.json
        if "url" in state:
            url = state["url"]
            del state["url"]
        elif "url" in args:
            url = args['url']
        else:
            api.abort(400, "No URL specified")
        parts = urlparse(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        for key in query:
            query[key] = query[key][0]
        data = {
            "query": query,
            "state": state
        }

        # Insert into databse
        db_engine, users_table, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
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

        with db_engine.begin() as connection:
            connection.execute(sql, {"user": username, "data": datastr, "date": date})

        return jsonify({"success": True})

@bk.route('/')
class UserBookmarksList(Resource):
    @bk.doc('getbookmarks')
    @optional_auth
    def get(self):
        username = get_username(get_identity())
        if not username:
            return jsonify([])

        tenant = tenant_handler.tenant()
        config = config_handler.tenant_config(tenant)
        sort_order = config.get('bookmarks_sort_order', 'date, description')

        db_engine, users_table, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        if users_table:
            sql = sql_text("""
                WITH "user" AS (
                    SELECT id FROM {users_table} WHERE name=:username
                )
                SELECT data, key, description, to_char(date, 'YYYY-MM-DD') as date
                FROM {table}
                WHERE user_id = (SELECT id FROM "user")
                ORDER BY {sort_order}
            """.format(users_table=users_table, table=user_bookmark_table, sort_order=sort_order))
        else:
            sql = sql_text("""
                SELECT data, key, description, to_char(date, 'YYYY-MM-DD') as date
                FROM {table}
                WHERE username = :username ORDER BY {sort_order}
            """.format(table=user_bookmark_table, sort_order=sort_order))
        try:
            data = []
            with db_engine.connect() as connection:
                result = connection.execute(sql, {"username": username}).mappings()
                for row in result:
                    bookmark = {}
                    bookmark['data'] = json.loads(row.data)
                    bookmark['key'] = row.key
                    bookmark['description'] = row.description
                    bookmark['date'] = row.date
                    data.append(bookmark)
        except:
            data = []
        return jsonify(data)

    @bk.doc('addbookmark')
    @bk.param('url', 'The URL for which to generate a bookmark', 'query')
    @bk.param('payload', 'A json document with the state to store in the bookmark', 'body')
    @bk.param('description', 'Description to store in the bookmark', 'query')
    @bk.expect(userbookmark_parser)    
    @optional_auth
    def post(self):
        username = get_username(get_identity())
        if not username:
            return jsonify({"success": False})
        
        args = userbookmark_parser.parse_args()
        state = request.json
        if "url" in state:
            url = state["url"]
            del state["url"]
        elif "url" in args:
            url = args['url']
        else:
            api.abort(400, "No URL specified")
        parts = urlparse(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        for key in query:
            query[key] = query[key][0]
        data = {
            "query": query,
            "state": state
        }

        # Insert into database
        db_engine, users_table, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        datastr = json.dumps(data)
        hexdigest = hashlib.sha224((datastr + str(time.time())).encode('utf-8')).hexdigest()[0:9]
        date = datetime.date.today().strftime(r"%Y-%m-%d")
      
        description = args['description']
        if users_table:
            sql = sql_text("""
                WITH "user" AS (
                    SELECT id FROM {users_table} WHERE name=:username
                )
                INSERT INTO {table} (user_id, username, data, key, date, description)
                VALUES ((SELECT id FROM "user"), :username, :data, :key, :date, :description)
            """.format(users_table=users_table, table=user_bookmark_table))
        else:
            sql = sql_text("""
                INSERT INTO {table} (username, data, key, date, description)
                VALUES (:username, :data, :key, :date, :description)
                ON CONFLICT (username,key) WHERE username = :username
                DO
                UPDATE
                SET data = :data, date = :date, description = :description
            """.format(table=user_bookmark_table))

        attempts = 0
        while attempts < 100:
            try:
                with db_engine.begin() as connection:
                    connection.execute(sql, {"username": username, "data": datastr, "key": hexdigest, "date": date, "description": description})
                    break
            except:
                pass
            hexdigest = hashlib.sha224((datastr + str(random.random())).encode('utf-8')).hexdigest()[0:9]
            attempts += 1

        return jsonify({"success": attempts < 100})

@bk.route('/<key>')
class UserBookmark(Resource):
    @bk.doc('getbookmark')
    @optional_auth
    def get(self, key):
        username = get_username(get_identity())
        if not username:
            return jsonify({"success": False})

        db_engine, users_table, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        if users_table:
            sql = sql_text("""
                WITH "user" AS (
                    SELECT id FROM {users_table} WHERE name=:username
                )
                SELECT data
                FROM {table}
                WHERE user_id = (SELECT id FROM "user") AND key = :key
            """.format(users_table=users_table, table=user_bookmark_table))
        else:
            sql = sql_text("""
                SELECT data
                FROM {table}
                WHERE username = :username and key = :key
            """.format(table=user_bookmark_table))
        try:
            with db_engine.connect() as connection:
                data = json.loads(connection.execute(sql, {"username": username, "key": key}).mappings().first()["data"])
        except Exception as e:
            print(e)
            data = {}
        return jsonify(data)

    @bk.doc('deletebookmark')
    @optional_auth
    def delete(self, key):
        username = get_username(get_identity())
        if not username:
            return jsonify({"success": False})
        
        # Delete into databse
        db_engine, users_table, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        if users_table:
            sql = sql_text("""
                WITH "user" AS (
                    SELECT id FROM {users_table} WHERE name=:username
                )
                DELETE FROM {table}
                WHERE key = :key and user_id = (SELECT id FROM "user")
            """.format(users_table=users_table, table=user_bookmark_table))
        else:
            sql = sql_text("""
                DELETE FROM {table}
                WHERE key = :key and username = :username
            """.format(table=user_bookmark_table))

        with db_engine.begin() as connection:
            connection.execute(sql, {"key": key, "username": username})

        return jsonify({"success": True})

    @bk.doc('setbookmark')
    @bk.param('url', 'The URL for which to generate a bookmark', 'query')
    @bk.param('payload', 'A json document with the state to store in the bookmark', 'body')
    @bk.param('description', 'Description to store in the bookmark', 'query')
    @bk.expect(userbookmark_parser)    
    @optional_auth
    def put(self, key):
        username = get_username(get_identity())
        if not username:
            return jsonify({"success": False})
        
        args = userbookmark_parser.parse_args()
        state = request.json
        if "url" in state:
            url = state["url"]
            del state["url"]
        elif "url" in args:
            url = args['url']
        else:
            api.abort(400, "No URL specified")
        parts = urlparse(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        for k in query:
            query[k] = query[k][0]
        data = {
            "query": query,
            "state": state
        }

        # Update into databse
        db_engine, users_table, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        datastr = json.dumps(data)
        date = datetime.date.today().strftime(r"%Y-%m-%d")
      
        description = args['description']
        if users_table:
            sql = sql_text("""
                WITH "user" AS (
                    SELECT id FROM {users_table} WHERE name=:username
                )
                UPDATE {table}
                SET username = :username, data = :data, date = :date, description = :description
                WHERE user_id = (SELECT id FROM "user") and key = :key
            """.format(users_table=users_table, table=user_bookmark_table))
        else:
            sql = sql_text("""
                UPDATE {table}
                SET data = :data, date = :date, description = :description
                WHERE username = :username and key = :key
            """.format(table=user_bookmark_table))

        with db_engine.begin() as connection:
            connection.execute(sql, {"username": username, "data": datastr, "key": key, "date": date, "description": description})

        return jsonify({"success": True})

""" readyness probe endpoint """
@app.route("/ready", methods=['GET'])
def ready():
    return jsonify({"status": "OK"})


""" liveness probe endpoint """
@app.route("/healthz", methods=['GET'])
def healthz():
    try:
        db_engine, users_table, permalinks_table, user_permalink_table, user_bookmark_table = db_conn()
        with db_engine.connect() as connection:
            connection.execute(sql_text("SELECT 1"))
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
