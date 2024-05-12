import psycopg
from psycopg.rows import dict_row
import os
from src.util.env_util import cfg

class DatabaseConnection:
    def __init__(self, connection_string=None):
        """Initialize with a connection string or use the environment variable."""
        self.connection_string = connection_string or os.environ.get('DB_URL')

    def connect(self):
        """Establish a database connection using the connection string."""
        return psycopg.connect(self.connection_string, row_factory=dict_row)
