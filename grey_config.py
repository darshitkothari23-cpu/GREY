"""
Configuration for the GREY market intelligence engine.

GREY is intentionally configured as an intelligence-only layer. This module
must not import execution, broker, or position-management components.
"""

PACKET_VERSION = "1.0"

GREY_ENABLED = False
GREY_SHADOW_MODE = True
GREY_MODE = "LAB"

GREY_AGGREGATOR_INTERVAL_SECONDS = 30
GREY_PHASE1_EVALUATION_DELAY_MINUTES = 15
GREY_PHASE1_SIGNAL_LOG_PATH = "journals/grey/phase1_signals.jsonl"

GREY_SESSION_TIMINGS = {
    "PRE_OPEN_START": "09:00",
    "MARKET_OPEN": "09:15",
    "DERIVATIVES_CLOSE": "15:30",
    "NSE_EXTENSION_DATE": "2026-08-03",
    "DERIVATIVES_CLOSE_EXTENDED": "15:40",
}

GREY_MODULES_ENABLED = {
    "REGIME": True,
    "OPTIONS": True,
    "KRONOS": True,
    "VIX_REGIME": True,
    "PCR": True,
    "EXPIRY_CYCLE": True,
    "OI_CHANGE": True,
    "CALENDAR": True,
    "VOLATILITY": True,
    "OVERNIGHT": True,
    "PREMIUM": False,
    "VOLUME": False,
    "SECTOR": False,
    "LIQUIDITY": False,
}

GREY_JOURNAL_PATH = "journals/grey/"
GREY_OUTPUT_PATH = "grey_output/grey_context_packet.json"

GREY_TELEGRAM_ENABLED = False
GREY_TELEGRAM_PREFIX = "🔵 GREY:"
GREY_TELEGRAM_BOT_TOKEN = ""
GREY_TELEGRAM_CHAT_ID = ""
GREY_TELEGRAM_LIVE_ENABLED = False
GREY_TELEGRAM_LIVE_FREQUENCY_SECONDS = 300

GREY_KRONOS_MODEL_PATH = "kronos_nse_finetuned"
GREY_KRONOS_REPO_PATH = "Kronos"
GREY_KRONOS_MAX_CONTEXT = 512

GREY_SIGNAL_AGGREGATOR = {
    "module_weights": {
        "KRONOS": 0.90,
        "VIX_REGIME": 1.30,
        "PCR": 0.95,
        "EXPIRY_CYCLE": 1.10,
        "OI_CHANGE": 1.00,
    },
    "session_multipliers": {
        "OPENING_DRIVE": {
            "KRONOS": 0.70,
        },
        "EARLY_TREND": {
            "KRONOS": 1.10,
        },
        "MIDDAY": {
            "KRONOS": 1.20,
        },
        "CLOSING_DRIVE": {
            "KRONOS": 1.00,
        },
        "PRE_EVENT": {
            "KRONOS": 0.50,
        },
    },
}

GREY_CONTEXT_PACKET_DEFAULTS = {
    "packet_version": PACKET_VERSION,
    "mode": GREY_MODE,
    "shadow_mode": GREY_SHADOW_MODE,
    "modules_enabled": GREY_MODULES_ENABLED,
    "session_timings": GREY_SESSION_TIMINGS,
}

__all__ = [
    "PACKET_VERSION",
    "GREY_ENABLED",
    "GREY_SHADOW_MODE",
    "GREY_MODE",
    "GREY_AGGREGATOR_INTERVAL_SECONDS",
    "GREY_PHASE1_EVALUATION_DELAY_MINUTES",
    "GREY_PHASE1_SIGNAL_LOG_PATH",
    "GREY_SESSION_TIMINGS",
    "GREY_MODULES_ENABLED",
    "GREY_JOURNAL_PATH",
    "GREY_OUTPUT_PATH",
    "GREY_TELEGRAM_ENABLED",
    "GREY_TELEGRAM_PREFIX",
    "GREY_TELEGRAM_BOT_TOKEN",
    "GREY_TELEGRAM_CHAT_ID",
    "GREY_TELEGRAM_LIVE_ENABLED",
    "GREY_TELEGRAM_LIVE_FREQUENCY_SECONDS",
    "GREY_KRONOS_MODEL_PATH",
    "GREY_KRONOS_REPO_PATH",
    "GREY_KRONOS_MAX_CONTEXT",
    "GREY_SIGNAL_AGGREGATOR",
    "GREY_CONTEXT_PACKET_DEFAULTS",
]
