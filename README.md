[![](https://github.com/qwc-services/qwc-permalink-service/workflows/build/badge.svg)](https://github.com/qwc-services/qwc-permalink-service/actions)
[![docker](https://img.shields.io/docker/v/sourcepole/qwc-permalink-service?label=Docker%20image&sort=semver)](https://hub.docker.com/r/sourcepole/qwc-permalink-service)

QWC Permalink Service
=====================

Stores and resolves compact permalinks for the QGIS Web Client.

Permalinks are stored in a database table.

Configuration
-------------

The static config files are stored as JSON files in `$CONFIG_PATH` with subdirectories for each tenant,
e.g. `$CONFIG_PATH/default/*.json`. The default tenant name is `default`.

### JSON config

* [JSON schema](schemas/qwc-permalink-service.json)
* File location: `$CONFIG_PATH/<tenant>/permalinkConfig.json`

Example:
```json
{
  "$schema": "https://raw.githubusercontent.com/qwc-services/qwc-permalink-service/master/schemas/qwc-permalink-service.json",
  "service": "permalink",
  "config": {
    "db_url": "postgresql:///?service=qwc_configdb",
    "permalinks_table": "qwc_config.permalinks",
    "user_bookmark_table": "qwc_config.user_bookmarks",
    "bookmarks_sort_order": "date DESC, description"
  }
}
```

See the [schema definition](schemas/qwc-permalink-service.json) for the full set of supported config variables.

### Environment variables

Config options in the config file can be overridden by equivalent uppercase environment variables.

### Tables

If you don't use the [`qwc-base-db`](https://github.com/qwc-services/qwc-base-db), you have to create the tables first:

    CREATE TABLE permalinks
    (
      key character(10) NOT NULL PRIMARY KEY,
      data text,
      date date,
      expires date
    );

    CREATE TABLE user_bookmarks (
      username character varying NOT NULL PRIMARY KEY,
      data text,
      key varchar(10),
      date date,
      description text
    );

    CREATE TABLE user_visibility_presets (
      username character varying NOT NULL PRIMARY KEY,
      data text,
      key varchar(10),
      date date,
      description text,
    )

Run locally
-----------

Install dependencies and run:

    export CONFIG_PATH=<CONFIG_PATH>
    uv run src/server.py

To use configs from a `qwc-docker` setup, set `CONFIG_PATH=<...>/qwc-docker/volumes/config`.

Set `FLASK_DEBUG=1` for additional debug output.

Set `FLASK_RUN_PORT=<port>` to change the default port (default: `5000`).

Docker usage
------------

The Docker image is published on [Dockerhub](https://hub.docker.com/r/sourcepole/qwc-permalink-service).

See sample [docker-compose.yml](https://github.com/qwc-services/qwc-docker/blob/master/docker-compose-example.yml) of [qwc-docker](https://github.com/qwc-services/qwc-docker).
