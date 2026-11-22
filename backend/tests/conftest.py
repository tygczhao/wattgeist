import os
import tempfile

# Tests never call a real LLM, and persistence goes to a temp directory so the user's ~/.wattgeist is untouched
os.environ["WATTGEIST_DISABLE_AI"] = "1"
os.environ.setdefault("WATTGEIST_DATA_DIR", tempfile.mkdtemp(prefix="wattgeist-test-"))
