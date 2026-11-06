import logging

from fastapi.testclient import TestClient

from jobwatch.config import load_config
from jobwatch.web.app import create_app


