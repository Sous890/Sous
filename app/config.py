import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.environ["DATABASE_URL"]
SESSION_SECRET: str = os.environ["SESSION_SECRET"]
SECURE_COOKIES: bool = os.environ.get("SECURE_COOKIES", "true").lower() == "true"

ADMIN_USERNAME: str = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_NICKNAME: str = os.environ.get("ADMIN_NICKNAME", "Conductor")
ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "changeme12345")
