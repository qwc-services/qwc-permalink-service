QWC Permalink Service
=====================

Stores and resolves compact permalinks for the Web Client.

Permalinks are stored in the qwc-config database in the `qwc_config.permalinks` table.

Environment variables
---------------------

| Variable               | Default value                         | Description           |
|------------------------|---------------------------------------|-----------------------|
| `CONFIGDB_URL`         | `postgresql:///?service=qwc_configdb` | DB connection URL [1] |
| `PERMALINKS_TABLE`     | `qwc_config.permalinks`               | Permalink table       |
| `USER_PERMALINK_TABLE` | `qwc_config.user_permalinks`          | User permalink table  |

[1] https://docs.sqlalchemy.org/en/13/core/engines.html#postgresql

If you don't use `qwc-config-db` you have to create the tables for storing permalinks first.
Example:

    CREATE TABLE permalinks
    (
      key character(10) NOT NULL PRIMARY KEY,
      data text,
      date date
    );


Usage
-----

Base URL:

    http://localhost:5018/

API documentation:

    http://localhost:5018/api/

Development
-----------

Create a virtual environment:

    virtualenv --python=/usr/bin/python3 .venv

Activate virtual environment:

    source .venv/bin/activate

Install requirements:

    pip install -r requirements.txt

Start local service:

    python server.py
