# Set up Copy Trade on a Windows PC

Follow these steps for each new PC or destination account. Run the commands below in Windows Command Prompt (`cmd`).

## 1. Install the required software

Install Python, Git, and Tailscale. Enable **Add Python to PATH** during Python installation. Sign in to Tailscale with the team's Tailscale account so the PC can reach the market-data machines and account servers.

Open a new Command Prompt and check:

```bat
python --version
python -m pip --version
git --version
```

## 2. Clone the repository and select the branch

The branches used for current setups are `shared-token` and `sync-greeksoft`. The `sync-greeksoft` branch includes the additional GreekSoft position-sync feature. Use `sync-greeksoft` for this setup:

```bat
git clone https://github.com/ArrowheadCapital/copy_trade.git
cd copy_trade
git switch sync-greeksoft
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
```

Sign in to GitHub if prompted for access to the repository.

## 3. Create the local configuration files

Create `.env` and `credentials.py` in the repository root using the sample files:

```bat
copy sample.env .env
copy sample.credentials.py credentials.py
```

These commands are for a fresh clone; keep any existing account configuration when updating an installation. Edit the copied files as described below.

### GreekSoft `.env`

For the basic GreekSoft setup, the only required `.env` variable is:

```dotenv
COPY_ALLOWED_DELAY_SECONDS=120
```

Use the exact name `COPY_ALLOWED_DELAY_SECONDS` for both brokers. Set it to the permitted source-trade age in seconds.

### StratX `.env`

```dotenv
OPTION_INSTRUMENT_CSV='\\100.103.231.7\d\Codes\Live_data_depth\greeksoft_middleware_client\instruments_data\options_instruments.csv'
COPY_ALLOWED_DELAY_SECONDS=120
```

The instrument CSV is on **DESKTOP-CLI5HO6**, in the Live Data Depth project's instrument-data folder.

## 4. Set the source trade-file paths and CTCL export

In `credentials.py`, point both paths to the **source account's** AutoOnlineBackup folder. For example, if the source account is `TS623` and its backup is stored locally:

```python
pathNSE = 'C:/TS623/AutoOnlineBackup/NSE/FO/{formatted_date}AUTOTRD.txt'
pathBSE = 'C:/TS623/AutoOnlineBackup/BSE/FO/{formatted_date}AUTOTRD.txt'
```

Replace `TS623` and the folder location to match the actual source installation. If the source is on another PC, use its accessible Windows network-share path instead. Keep `{formatted_date}` unchanged; the application replaces it with the current date in `MMDD` format.

In the source account's CTCL terminal:

1. Open the settings available through **Alt+C** and **Alt+F7**.
2. Make sure the AutoOnlineBackup paths in both settings match the source folders configured above.
3. Tick **With Header** and **With Strategy Column Name**.
4. Verify today's NSE/BSE export files appear in the configured folders and can be read from the Copy Trade PC.

## 5. Set freeze quantities and copy settings

Freeze quantities are stored in `shared_config.py`, the shared configuration file committed and pushed with the repository. Redis sources are kept in the same file. Review these freeze fields there:

```text
niftyFreeze
bnfFreeze
sensexFreeze
bankex
midcpnifty
finnifty
```

The broker and Redis modules read these settings directly from `shared_config.py`. Do not add them or import them in `credentials.py`. For an existing installation, remove the old freeze assignments and `redis_sources` list from `credentials.py`.

Restart Copy Trade after updating `shared_config.py`.

Then configure the multiplier, source account ID, source strategy filter, and destination broker in `credentials.py`. For example:

```python
multiplier = 1
copy_source_id = "TS623"
source_strategy_names = ["SOURCE_STRATEGY_NAME"]
broker = "GREEK"  # Use "STRATX" for StratX.
```

Replace the multiplier and strategy name with the intended values. `copy_source_id` must match the source ID in the exported trade rows, and `source_strategy_names` must contain the source strategies to copy. For StratX, also set the separate destination `strategy_name` in step 7.

## 6. Configure the GreekSoft destination

For GreekSoft, set `broker = "GREEK"`, set the required `greek_broker` in `credentials.py`, and choose `urll` according to the destination. `greek_broker` is case-insensitive: `SHAREINDIA` allows 30 order attempts per rolling 1.2 seconds, `MOTILAL` allows 5, and any other non-empty name allows 9. A missing or blank value stops startup. Restart Copy Trade after changing it; `urll` still selects the destination server:

| Destination | `urll`                |
| ----------- | ----------------------- |
| ShareIndia  | `14.143.11.114:3344`  |
| Motilal     | `142.79.250.226:3344` |

For example, for ShareIndia:

```python
greek_broker = "SHAREINDIA"
urll = "14.143.11.114:3344"
username = "DESTINATION_GREEK_USERNAME"
pw = "DESTINATION_GREEK_PASSWORD"
authurl = "http://greekapi.greeksoft.in:3001"
greek_session_token_file = r"\\ACCOUNT_SERVER\SHARE\PATH\shared_session_token.json"
```

Set `username` and `pw` for the destination account. Replace the token-file placeholder with the actual shared session-token path on the server hosting that account. Use the token file belonging to the correct destination account.

Also set the existing `iprocli` and `AccountNumber` fields for the account type: `"0"` for retailer, `"1"` for dealer through retailer, or `"2"` for dealer. `AccountNumber` is required for dealer-through-retailer orders; for retailer orders use `""`.

## 7. Configure the StratX destination

For StratX, set `broker = "STRATX"` and fill these fields in `credentials.py`:

```python
optionInstrumentPath = os.getenv("OPTION_INSTRUMENT_CSV")
id = "STRATX_USER_ID"
secret_key = "STRATX_SECRET_KEY"
stratX_url = "STRATX_API_HOST"
strategy_name = "DESTINATION_STRATEGY_NAME"
STRATX_NET_CLIENT_ID = "Y05601"
```

Use the destination's actual StratX credentials, API host, and strategy name. Supply the API hostname without `https://`; the code adds it. Keep the sample file's `import os`, `load_dotenv` import, and `load_dotenv()` call so the instrument path is read from `.env`.

`STRATX_NET_CLIENT_ID` identifies the client used for net synchronization. Use `Y05601` for this setup; change it if the deployment uses a different reference client.

## 8. Set net quantity limits for either broker

Set all eight fields in `credentials.py` for both GreekSoft and StratX. The setup values for a **1 crore account** are:

```python
NIFTY_CE_POS_NET = 1000
NIFTY_CE_NEG_NET = 3770
NIFTY_PE_POS_NET = 1000
NIFTY_PE_NEG_NET = 3770
SENSEX_CE_POS_NET = 340
SENSEX_CE_NEG_NET = 1300
SENSEX_PE_POS_NET = 340
SENSEX_PE_NEG_NET = 1300
```

Multiply every base value by the account size in crores. The same limit applies separately to CE and PE:

| Limit           | Calculation                        | Example: 50 crore account |
| --------------- | ---------------------------------- | ------------------------: |
| NIFTY positive  | `1000 × account size in crores` |                     50000 |
| NIFTY negative  | `3770 × account size in crores` |                    188500 |
| SENSEX positive | `340 × account size in crores`  |                     17000 |
| SENSEX negative | `1300 × account size in crores` |                     65000 |

Values are quantities, not lot counts. Enter both `POS_NET` and `NEG_NET` as non-negative magnitudes. For example, the 1 crore NIFTY limits allow net quantities from `-3770` to `+1000` in each CE/PE bucket. Zero leaves no allowance on that side.

## 9. Review Redis sources for either broker

The Git-tracked `shared_config.py` contains the following sources:

```python
redis_sources = [
    {"name": "DESKTOP-CLI5HO6", "host": "100.103.231.7", "port": 6379, "db": 1},
    {"name": "Data-KAI", "host": "100.68.131.14", "port": 6379, "db": 1},
]
```

The list supplies the primary and fallback pricing sources. Tailscale connectivity and access to Redis port `6379` must work from the new PC.

## 10. Save Windows credentials for all required network paths

1. Open **File Explorer → Network**.
2. In the address bar at the top, enter the required PC's Tailscale IP with two leading backslashes, for example `\\100.103.231.7`, and press **Enter**.
3. When prompted, enter the username and that PC's Windows password.
4. Tick **Remember my credentials**, then click **OK**.
5. Repeat for **DESKTOP-CLI5HO6**, **Data-KAI**, and **Linux servers path (path to token file)**, using each PC's Tailscale IP.

## 11. Review and launch

Before starting, confirm the selected branch, broker, destination account, source paths, CTCL export settings, multiplier, strategy filters, freeze quantities, all eight net limits, Redis sources, and required share access.

Launch from the repository root or double-click `run.cmd`:

```bat
run.cmd
```

Review the account and limits displayed in the GUI, then click **Start Algo** when ready to copy trades. Check the GUI/logs for source-header, authentication, instrument-file, and Redis errors.

On `sync-greeksoft`, GreekSoft also has **Sync Positions**, which compares source positions with the destination and can submit correction orders. **Sync Net** refreshes net-risk quantities. See the [README&#39;s GreekSoft orderbook, retry, and position-sync documentation](../README.md#greeksoft-orderbook-retry) for the detailed behavior and limitations before using position sync.

## 12. Add the Trade Multiplier profile (GreekSoft only)

After completing the GreekSoft Copy Trade setup, add the new source-to-destination profile to the **Trade Multiplier Streamlit** app. This app is used to see mismatches between the source and destination accounts. This step applies only to GreekSoft.

1. Use the Tailscale IP of **desktop-dft6h9p**: `100.84.50.79`.
2. Open **File Explorer → Network**, enter `\\100.84.50.79\d\MiniAdmin` in the address bar, and press **Enter**. If prompted, sign in with that PC's Windows username and password and tick **Remember my credentials**.
3. Open `profiles.yaml` in that folder.
4. Add a profile for the source and destination just configured, alongside the existing profiles. Match their indentation and keep the existing entries. For example:

```yaml
  - name: Source Destination
    source_client: H123
    multiplier_file: '\\100.69.42.15\copy_trade_TS123\credentials.py'
    source_nse_directory: '\\100.69.42.15\d\H123\AutoOnlineBackup\NSE\FO'
    source_bse_directory: '\\100.69.42.15\d\H123\AutoOnlineBackup\BSE\FO'
    destination_nse_directory: '\\100.69.42.15\d\TS123\AutoOnlineBackup\NSE\FO'
    destination_bse_directory: '\\100.69.42.15\d\TS123\AutoOnlineBackup\BSE\FO'
```

Replace `Source Destination` with a descriptive profile name and `H123` with the actual source client ID. Set `multiplier_file` to the new Copy Trade installation's `credentials.py`. Set the four directory paths to the actual source and destination NSE/BSE export folders, using each PC's Tailscale IP and shared folder. The example uses `100.69.42.15` for both accounts and `TS123` as the destination; change these to match the setup. Keep the YAML paths single-quoted so the backslashes are preserved.

Save `profiles.yaml`, then check the new profile in Trade Multiplier Streamlit for source/destination mismatches.
