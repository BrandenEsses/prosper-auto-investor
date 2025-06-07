from base64 import b64decode

PROSPER_CLIENT_ID = b64decode("").decode('UTF-8')
PROSPER_CLIENT_SECRET = b64decode("").decode('UTF-8')
PROSPER_USERNAME = b64decode("").decode('UTF-8')
PROSPER_PASSWORD = b64decode("").decode('UTF-8')
MYSQL_PASSWORD = b64decode("").decode('UTF-8')
DB_USER = ''
DB_PASS = b64decode("").decode('UTF-8')
DB_HOST = ''
DB_NAME = ''
SQLALCHEMY_DATABASE_URI = f'mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}'
SQLALCHEMY_TRACK_MODIFICATIONS = False
SECRET_KEY = b64decode("").decode('UTF-8')