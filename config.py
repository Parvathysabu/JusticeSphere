#pip install pymysql
import os
import pymysql

class Database(object):

    def __init__(self, config=None, username=None, password=None, host=None, port=None, db_name=None):
        if db_name is None:
            db_name = os.getenv('MYSQL_DATABASE') or 'db_crime'
        if username is None:
            username = os.getenv('MYSQL_USERNAME') or 'root'
        if password is None:
            password = os.getenv('MYSQL_PASSWORD') or ''

        if host is None:
            host = os.getenv('MYSQL_HOST') or 'localhost'
        if port is None:
            port = os.getenv('MYSQL_PORT') or '3306'

        self.params_dict = {
            "host": host,
            "db": db_name,
            "user": username,
            "password": password,
            "port": int(port),
            "connect_timeout": 5
        }

    def connect(self):
        """ Connect to the MySQL database server """
        conn = None
        try:
            # connect to the MySQL server
            conn = pymysql.connect(**self.params_dict)
        except (Exception, pymysql.Error) as error:
            raise error
        return conn

    def connect_server(self):
        """Connect to MySQL server without specifying a database (for CREATE DATABASE / USE)."""
        params = dict(self.params_dict)
        params.pop('db', None)
        try:
            return pymysql.connect(**params)
        except (Exception, pymysql.Error) as error:
            raise error

    def single_insert(self, insert_req, params=None):
        """ Execute a single INSERT request """
        conn = None
        cursor = None
        try:
            conn = self.connect()
            cursor = conn.cursor()
            if params is not None:
                cursor.execute(insert_req, params)
            else:
                cursor.execute(insert_req)
            conn.commit()
        except (Exception, pymysql.Error) as error:
            if conn is not None:
                conn.rollback()
            raise error
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

    def execute(self, req_query, params=None):
        """ Execute a single request """
        """ for Update/Delete request """
        conn = None
        cursor = None
        try:
            conn = self.connect()
            cursor = conn.cursor()
            if params is not None:
                cursor.execute(req_query, params)
            else:
                cursor.execute(req_query)
            conn.commit()
        except (Exception, pymysql.Error) as error:
            if conn is not None:
                conn.rollback()
            raise error
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

    def executeAndReturnId(self, req_query, params=None):
        """ Execute a single request and return id"""
        """ for insert request """
        conn = None
        cursor = None
        try:
            conn = self.connect()
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            if params is not None:
                cursor.execute(req_query, params)
            else:
                cursor.execute(req_query)
            dt = cursor.lastrowid
            conn.commit()
            return dt
        except (Exception, pymysql.Error) as error:
            if conn is not None:
                conn.rollback()
            raise error
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()
                
    def fetchone(self, get_req, params=None):
        conn=None
        cur=None
        try:
            conn = self.connect()
            cur = conn.cursor(pymysql.cursors.DictCursor)
            if params is not None:
                cur.execute(get_req, params)
            else:
                cur.execute(get_req)
            data = cur.fetchone()
            return data
        except (Exception, pymysql.Error) as error:
            raise error
        finally:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()

    def fetchall(self, get_req, params=None):
        conn = None
        cur = None
        try:
            conn = self.connect()
            cur = conn.cursor(pymysql.cursors.DictCursor)
            if params is not None:
                cur.execute(get_req, params)
            else:
                cur.execute(get_req)
            data = cur.fetchall()
            return data
        except (Exception, pymysql.Error) as error:
            raise error
        finally:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()

    def execute_script(self, sql_script_text):
        """Execute a multi-statement SQL script. Statements must be separated by semicolons."""
        conn = None
        cur = None
        try:
            # Use server-level connection to allow CREATE DATABASE/USE to succeed even if DB doesn't exist yet
            conn = self.connect_server()
            cur = conn.cursor()
            # Split on semicolons while ignoring empty statements
            statements = [s.strip() for s in sql_script_text.split(';') if s.strip()]
            for stmt in statements:
                cur.execute(stmt)
            conn.commit()
        except (Exception, pymysql.Error) as error:
            if conn is not None:
                conn.rollback()
            raise error
        finally:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()