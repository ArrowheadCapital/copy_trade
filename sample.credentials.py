import os
from dotenv import load_dotenv

load_dotenv()

# Source trade files. Keep the {formatted_date} placeholder.
pathNSE = "C:/AutoOnlineBackup/NSE/FO/{formatted_date}AUTOTRD.txt"
pathBSE = "C:/AutoOnlineBackup/BSE/FO/{formatted_date}AUTOTRD.txt"


# Copy settings.
multiplier = 1
copy_source_id = "SOURCE_ID"
source_strategy_names = ["SOURCE_STRATEGY"]
broker = "GREEK"  # GREEK or STRATX

# GreekSoft settings.
urll = "GREEK_API_HOST:PORT"
username = "GREEK_USERNAME"
pw = "GREEK_PASSWORD"
authurl = "http://greekapi.greeksoft.in:3001"

# Optional shared GreekSoft authentication. Leave undefined for the existing login flow.
# greek_session_token_file = r"TAILSCALE_SHARED_PATH\shared_session_token.json"
# greek_gcid = "FIXED_GCID"

# For placing orders:
'''
iprocli:0 for retailer
iprocli:1 for dealer through retailer
iprocli:2 for dealer

account number is mandatory for dealer thorugh retailer orders only, else account number should be "".
'''

iprocli = "0"
AccountNumber = ""

# StratX settings.
optionInstrumentPath = os.getenv("OPTION_INSTRUMENT_CSV")
id = "STRATX_USER_ID"
secret_key = "STRATX_SECRET_KEY"
stratX_url = "STRATX_API_HOST"
strategy_name = "STRATX_STRATEGY_NAME"


# Shared GreekSoft/StratX net limits. Zero is the safe sample default.
NIFTY_CE_POS_NET = 0
NIFTY_CE_NEG_NET = 0
NIFTY_PE_POS_NET = 0
NIFTY_PE_NEG_NET = 0
SENSEX_CE_POS_NET = 0
SENSEX_CE_NEG_NET = 0
SENSEX_PE_POS_NET = 0
SENSEX_PE_NEG_NET = 0

# StratX client whose traded orders are used for net synchronization.
STRATX_NET_CLIENT_ID = "STRATX_NET_CLIENT_ID"
