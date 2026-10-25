"""Agent configuration: locations, models and limits in one place."""

from deletion_audit.contract import REPO_ROOT

PACKAGE_DIR = REPO_ROOT / "code" / "deletion_audit"
PROMPTS_DIR = PACKAGE_DIR / "prompts"
CACHE_DIR = PACKAGE_DIR / "cache"
USAGE_DIR = REPO_ROOT / "code" / "usage"

INTENT_MODEL = "claude-haiku-5-5"
INTENT_BATCH_SIZE = 25
INTENT_CACHE_FILE = CACHE_DIR / "intent_cache.json"
USAGE_LOG_FILE = USAGE_DIR / "usage_log.jsonl"
LAST_RUN_USAGE_FILE = USAGE_DIR / "last_run_usage.json"
