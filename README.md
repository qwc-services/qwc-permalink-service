QWC Permalink Service
=====================

Stores and resolves compact permalinks for the Web Client.

Permalinks are stored in the qwc-config database in the `qwc_config.permalinks` table.

Usage
-----

Base URL:

    http://localhost:5018/

API documentation:

    http://localhost:5018/api/

Development
-----------

Create a virtual environment:

    virtualenv --python=/usr/bin/python3 --system-site-packages .venv

Without system packages:

    virtualenv --python=/usr/bin/python3 .venv

Activate virtual environment:

    source .venv/bin/activate

Install requirements:

    pip install -r requirements.txt

Start local service:

    python server.py
