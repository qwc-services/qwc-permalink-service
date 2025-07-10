[![](https://github.com/qwc-services/qwc-permalink-service/workflows/build/badge.svg)](https://github.com/qwc-services/qwc-permalink-service/actions)
[![docker](https://img.shields.io/docker/v/sourcepole/qwc-permalink-service?label=Docker%20image&sort=semver)](https://hub.docker.com/r/sourcepole/qwc-permalink-service)

QWC Permalink Service
=====================

Stores and resolves compact permalinks for the Web Client.

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
    "user_permalink_table": "qwc_config.user_permalinks"
  }
}
```

### Environment variables

Config options in the config file can be overridden by equivalent uppercase environment variables.

| Variable               | Default value                         | Description           |
|------------------------|---------------------------------------|-----------------------|
| `DB_URL`               | `postgresql:///?service=qwc_configdb` | DB connection URL [1] |
| `PERMALINKS_TABLE`     | `qwc_config.permalinks`               | Permalink table       |
| `USER_PERMALINK_TABLE` | `qwc_config.user_permalinks`          | User permalink table  |

[1] https://docs.sqlalchemy.org/en/13/core/engines.html#postgresql

If you don't use `qwc-config-db` you have to create the tables for storing permalinks first.
Example:

    CREATE TABLE permalinks
    (
      key character(10) NOT NULL PRIMARY KEY,
      data text,
      date date,
      expires date
    );


Usage
-----

Base URL:

    http://localhost:5018/

API documentation:

    http://localhost:5018/api/


Docker usage
------------

See sample [docker-compose.yml](https://github.com/qwc-services/qwc-docker/blob/master/docker-compose-example.yml) of [qwc-docker](https://github.com/qwc-services/qwc-docker).


Development
-----------

Set the `CONFIG_PATH` environment variable to the path containing the service config and permission files when starting this service (default: `config`).

    export CONFIG_PATH=../qwc-docker/volumes/config

Configure environment:

    echo FLASK_ENV=development >.flaskenv

Install dependencies and run service:

    uv run src/server.py
