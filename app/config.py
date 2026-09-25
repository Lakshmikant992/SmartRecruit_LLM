import os
from dotenv import load_dotenv # type: ignore

try:
    import redis
except ImportError:  # pragma: no cover - Redis is optional for local SQLite runs.
    redis = None

load_dotenv()

database_url = os.environ.get('DATABASE_URL', 'sqlite:///site.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql+psycopg://', 1)
elif database_url.startswith('postgresql://') and '+psycopg' not in database_url:
    database_url = database_url.replace('postgresql://', 'postgresql+psycopg://', 1)


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'local-development-only-change-me')
    SQLALCHEMY_DATABASE_URI = database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_TYPE = os.environ.get('SESSION_TYPE', 'filesystem')
    SESSION_USE_SIGNER = True
    SESSION_PERMANENT = False
    SESSION_REDIS = redis.from_url(os.environ['REDIS_URL']) if redis and os.environ.get('REDIS_URL') else None
    UPLOAD_FOLDER_CV = os.path.join('app', 'static', 'uploads', 'cv')
    UPLOAD_FOLDER_PHOTOS = os.path.join('app', 'static', 'uploads', 'photos')
    API_TOKEN = os.environ.get('API_TOKEN', '')
    API_URL = os.environ.get(
        'API_URL',
        'https://api-inference.huggingface.co/models/meta-llama/Meta-Llama-3-8B-Instruct',
    )
    MONGO_URI = os.environ.get('MONGO_URI', '')
    MONGO_DB_NAME = os.environ.get('MONGO_DB_NAME', 'applications')
    CORS_ORIGINS = [origin.strip() for origin in os.environ.get('CORS_ORIGINS', '').split(',') if origin.strip()]
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))
