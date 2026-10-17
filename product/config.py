"""Settings, from the environment, with local-development defaults. No credentials live in the code or the repository."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def env(name, default=None):
    return os.environ.get(name, default)


DATABASE_URL = env("NHB_PRODUCT_DATABASE_URL", "postgresql:///nhb_product")
FILES_ROOT = env("NHB_PRODUCT_FILES", os.path.join(ROOT, "data", "product", "files"))
ENGINE_ROOT = env("NHB_PRODUCT_ENGINE", os.path.join(ROOT, "data", "product", "engine"))
PACKAGES_ROOT = env("NHB_PRODUCT_PACKAGES", os.path.join(ROOT, "data", "product", "packages"))
WEB_DIST = env("NHB_PRODUCT_WEB", os.path.join(ROOT, "web", "out"))
PORT = int(env("NHB_PRODUCT_PORT", "8780"))

# Identity. Locally (owner, 2026-10-07: no login page) every request from this Mac acts as the firm's owner. The
# X-Dev-User header, which picks another user, is honored only when NHB_PRODUCT_DEV_AUTH=1 (the tests). Managed sign-in
# with MFA replaces both before anyone outside this Mac gets access (docs/74, B-11).
LOCAL_OWNER_EMAIL = env("NHB_PRODUCT_OWNER_EMAIL", "owner@example.com")
DEV_AUTH = env("NHB_PRODUCT_DEV_AUTH") == "1"
