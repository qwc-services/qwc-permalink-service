from flask import Flask, request, jsonify, make_response
from flask_restx import Api, Resource, reqparse
import datetime
import hashlib
import os
import random
import json
import time
from urllib.parse import urlparse, parse_qs
from sqlalchemy.sql import text as sql_text

from qwc_services_core.auth import auth_manager, optional_auth, get_identity, get_username
from qwc_services_core.api import CaseInsensitiveArgument
from qwc_services_core.database import DatabaseEngine
from qwc_services_core.permissions_reader import PermissionsReader
from qwc_services_core.tenant_handler import (
    TenantHandler, TenantPrefixMiddleware, TenantSessionInterface)
from qwc_services_core.runtime_config import RuntimeConfig


# Flask application
app = Flask(__name__)
api = Api(app, version='1.0', title='Permalink API',
          description='API for QWC Permalink service',
          default_label='Permalink operations', doc='/api/')

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
createpermalink_parser.add_argument('permitted_group', required=False)

resolvepermalink_parser = reqparse.RequestParser(argument_class=CaseInsensitiveArgument)
resolvepermalink_parser.add_argument('key', required=True)

userbookmark_parser = reqparse.RequestParser(argument_class=CaseInsensitiveArgument)
userbookmark_parser.add_argument('url', required=False)
userbookmark_parser.add_argument('description')

def db_conn(config):
    tenant = tenant_handler.tenant()
    config = config_handler.tenant_config(tenant)

    db_url = config.get('db_url', 'postgresql:///?service=qwc_configdb')
    qwc_config_schema = config.get('qwc_config_schema', 'qwc_config')
    db = db_engine.db_engine(db_url)

    store_bookmarks_by_userid = config.get('store_bookmarks_by_userid', True)
    if store_bookmarks_by_userid:
        users_table = f'"{qwc_config_schema}"."users"'
    else:
        users_table = None

    return db, qwc_config_schema, users_table

ALLOW_PUBLIC_BOOKMARKS = os.environ.get("ALLOW_PUBLIC_BOOKMARKS", "False").lower() == "true"

@api.route('/createpermalink')
class CreatePermalink(Resource):

    @api.doc('createpermalink')
    @api.param('url', 'The URL for which to generate a permalink', 'query')
    @api.param('permitted_group', 'Optional, group to which to restrict the permalink', 'query')
    @api.param('payload', 'A json document with the state to store in the permalink', 'body')
    @api.expect(createpermalink_parser)
    @optional_auth
    def post(self):
        args = createpermalink_parser.parse_args()
        tenant = tenant_handler.tenant()
        config = config_handler.tenant_config(tenant)
        db, qwc_config_schema, users_table = db_conn(config)
        permalinks_table = config.get('permalinks_table', qwc_config_schema + '.permalinks')
        default_expiry_period = config.get('default_expiry_period', None)

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
        permitted_group = args.get('permitted_group', None)

        # Insert into database
        datastr = json.dumps(data)
        hexdigest = hashlib.sha224((datastr + str(time.time())).encode('utf-8')).hexdigest()[0:9]
        date = datetime.date.today().strftime(r"%Y-%m-%d")
        expires = None
        if default_expiry_period:
            delta = datetime.timedelta(days=default_expiry_period)
            expires = (datetime.date.today() + delta).strftime(r"%Y-%m-%d")

        sql = sql_text("""
            INSERT INTO {table} (key, data, date, expires, permitted_group)
            VALUES (:key, :data, :date, :expires, :permitted_group)
        """.format(table=permalinks_table))

        attempts = 0
        while attempts < 100:
            try:
                with db.begin() as connection:
                    connection.execute(sql, {"key": hexdigest, "data": datastr, "date": date, "expires": expires, "permitted_group": permitted_group})
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
        with db.begin() as connection:
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
        tenant = tenant_handler.tenant()
        config = config_handler.tenant_config(tenant)
        db, qwc_config_schema, users_table = db_conn(config)
        permalinks_table = config.get('permalinks_table', qwc_config_schema + '.permalinks')

        key = args['key']
        data = {}
        permitted_group = None

        sql = sql_text("""
            SELECT data, permitted_group
            FROM {table}
            WHERE key = :key AND (expires IS NULL OR expires >= CURRENT_DATE)
        """.format(table=permalinks_table))
        try:
            with db.connect() as connection:
                result = connection.execute(sql, {"key": key}).mappings().first()
                data = json.loads(result["data"])
                permitted_group = result["permitted_group"]
        except:
            pass
        if permitted_group:
            app.logger.debug("Permalink %s is restricted to group %s" % (key, permitted_group))
            username = get_username(get_identity())
            tenant = tenant_handler.tenant()
            reader = PermissionsReader(tenant, app.logger)
            groups = reader.permissions['user_groups'].get(username, [])
            if permitted_group not in groups:
                app.logger.debug("User %s is not in group %s, returning empty response" % (username, permitted_group))
                return jsonify({})
        return jsonify(data)


@api.route('/userpermalink')
class UserPermalink(Resource):
    @api.doc('getuserpermalink')
    @optional_auth
    def get(self):
        username = get_username(get_identity())
        if not username:
            return jsonify({})

        tenant = tenant_handler.tenant()
        config = config_handler.tenant_config(tenant)
        db, qwc_config_schema, users_table = db_conn(config)
        user_permalink_table = config.get('user_permalink_table', qwc_config_schema + '.user_permalinks')

        sql = sql_text("""
            SELECT data
            FROM {table}
            WHERE username = :user
        """.format(table=user_permalink_table))
        try:
            with db.connect() as connection:
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

        tenant = tenant_handler.tenant()
        config = config_handler.tenant_config(tenant)
        db, qwc_config_schema, users_table = db_conn(config)
        user_permalink_table = config.get('user_permalink_table', qwc_config_schema + '.user_permalinks')

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

        with db.begin() as connection:
            connection.execute(sql, {"user": username, "data": datastr, "date": date})

        return jsonify({"success": True})

@api.route("/bookmarks/")
@api.route("/visibility_presets/")
class UserBookmarksList(Resource):
    @api.doc('getbookmarks')
    @optional_auth
    def get(self):
        username = get_username(get_identity())
        if not username:
            if ALLOW_PUBLIC_BOOKMARKS:
                username = "public"
            else:
                return jsonify([])

        endpoint = request.path.split("/")[1]

        tenant = tenant_handler.tenant()
        config = config_handler.tenant_config(tenant)
        db, qwc_config_schema, users_table = db_conn(config)
        if endpoint == "bookmarks":
            user_bookmark_table = config.get('user_bookmark_table', qwc_config_schema + '.user_bookmarks')
        else:
            user_bookmark_table = config.get('user_visibility_presets_table', qwc_config_schema + '.user_visibility_presets')
        sort_order = config.get('bookmarks_sort_order', 'date, description')

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
            with db.connect() as connection:
                result = connection.execute(sql, {"username": username}).mappings()
                for row in result:
                    bookmark = {}
                    bookmark['key'] = row.key
                    bookmark['description'] = row.description
                    bookmark['date'] = row.date
                    data.append(bookmark)
        except:
            data = []
        return jsonify(data)

    @api.doc('addbookmark')
    @api.param('url', 'The URL for which to generate a bookmark', 'query')
    @api.param('payload', 'A json document with the state to store in the bookmark', 'body')
    @api.param('description', 'Description to store in the bookmark', 'query')
    @api.expect(userbookmark_parser)
    @optional_auth
    def post(self):
        username = get_username(get_identity())
        if not username:
            if ALLOW_PUBLIC_BOOKMARKS:
                username = "public"
            else:
                app.logger.debug("Rejecting attempt to store bookmark as public user")
                return jsonify({"success": False})

        endpoint = request.path.split("/")[1]

        tenant = tenant_handler.tenant()
        config = config_handler.tenant_config(tenant)
        db, qwc_config_schema, users_table = db_conn(config)
        if endpoint == "bookmarks":
            user_bookmark_table = config.get('user_bookmark_table', qwc_config_schema + '.user_bookmarks')
        else:
            user_bookmark_table = config.get('user_visibility_presets_table', qwc_config_schema + '.user_visibility_presets')
        
        args = userbookmark_parser.parse_args()
        if endpoint == "bookmarks":
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
        else:
            data = request.json

        # Insert into database
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
                with db.begin() as connection:
                    connection.execute(sql, {"username": username, "data": datastr, "key": hexdigest, "date": date, "description": description})
                    break
            except:
                pass
            hexdigest = hashlib.sha224((datastr + str(random.random())).encode('utf-8')).hexdigest()[0:9]
            attempts += 1

        if attempts >= 100:
            app.logger.debug("More than 100 failed attempts to store bookmark")
        success = attempts < 100
        return jsonify({"success": success, "key": hexdigest if success else None})

@api.route("/bookmarks/<key>")
@api.route("/visibility_presets/<key>")
class UserBookmark(Resource):
    @api.doc('getbookmark')
    @optional_auth
    def get(self, key):
        username = get_username(get_identity())
        if not username:
            if ALLOW_PUBLIC_BOOKMARKS:
                username = "public"
            else:
                return jsonify({"success": False})

        endpoint = request.path.split("/")[1]

        tenant = tenant_handler.tenant()
        config = config_handler.tenant_config(tenant)
        db, qwc_config_schema, users_table = db_conn(config)
        if endpoint == "bookmarks":
            user_bookmark_table = config.get('user_bookmark_table', qwc_config_schema + '.user_bookmarks')
        else:
            user_bookmark_table = config.get('user_visibility_presets_table', qwc_config_schema + '.user_visibility_presets')

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
            with db.connect() as connection:
                data = json.loads(connection.execute(sql, {"username": username, "key": key}).mappings().first()["data"])
        except Exception as e:
            print(e)
            data = {}
        return jsonify(data)

    @api.doc('deletebookmark')
    @optional_auth
    def delete(self, key):
        username = get_username(get_identity())
        if not username:
            if ALLOW_PUBLIC_BOOKMARKS:
                username = "public"
            else:
                return jsonify({"success": False})
        
        endpoint = request.path.split("/")[1]

        tenant = tenant_handler.tenant()
        config = config_handler.tenant_config(tenant)
        db, qwc_config_schema, users_table = db_conn(config)
        if endpoint == "bookmarks":
            user_bookmark_table = config.get('user_bookmark_table', qwc_config_schema + '.user_bookmarks')
        else:
            user_bookmark_table = config.get('user_visibility_presets_table', qwc_config_schema + '.user_visibility_presets')

        # Delete into databse
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

        with db.begin() as connection:
            connection.execute(sql, {"key": key, "username": username})

        return jsonify({"success": True})

    @api.doc('setbookmark')
    @api.param('url', 'The URL for which to generate a bookmark', 'query')
    @api.param('payload', 'A json document with the state to store in the bookmark', 'body')
    @api.param('description', 'Description to store in the bookmark', 'query')
    @api.expect(userbookmark_parser)
    @optional_auth
    def put(self, key):
        username = get_username(get_identity())
        if not username:
            if ALLOW_PUBLIC_BOOKMARKS:
                username = "public"
            else:
                return jsonify({"success": False})

        endpoint = request.path.split("/")[1]
        
        tenant = tenant_handler.tenant()
        config = config_handler.tenant_config(tenant)
        db, qwc_config_schema, users_table = db_conn(config)
        if endpoint == "bookmarks":
            user_bookmark_table = config.get('user_bookmark_table', qwc_config_schema + '.user_bookmarks')
        else:
            user_bookmark_table = config.get('user_visibility_presets_table', qwc_config_schema + '.user_visibility_presets')

        args = userbookmark_parser.parse_args()
        if endpoint == "bookmarks":
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
        else:
            data = request.json

        # Update into databse
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

        with db.begin() as connection:
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
        db, qwc_config_schema, users_table = db_conn(config)
        with db.connect() as connection:
            connection.execute(sql_text("SELECT 1"))
    except Exception as e:
        return make_response(jsonify(
            {"status": "FAIL", "cause": str(e)}), 500)

    return jsonify({"status": "OK"})


if __name__ == "__main__":
    print("Starting Permalink service...")
    from flask_cors import CORS
    CORS(app)
    app.run(debug=True, port=5018)
