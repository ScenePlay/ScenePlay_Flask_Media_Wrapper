from flask_sqlalchemy import SQLAlchemy 
from flask_migrate import Migrate
import os

db = SQLAlchemy()
migrate = Migrate()
database = 'ScenePlay.db'
databaseDir = os.path.dirname(os.path.realpath(__file__)) + '/' + database