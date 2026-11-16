# Copy Trade Setup and Update Checklist

Use this checklist after a new setup or a feature update. See [SETUP.md](SETUP.md) for installation steps.

## 1. Source and destination CTCL terminals

Check both terminals separately.

- In **Alt+C** and **Alt+F7**, confirm the backup paths belong to the account logged into that terminal. The folder name should contain that account's ID.
- Confirm **Online Backup** and **Generic Backup** are ticked.
- Confirm **With Strategy Column Name** and **With Header** are ticked.
- Confirm the source and destination terminals use their own account folders.

## 2. Copy Trade configuration

Check these values in `credentials.py`:

- `pathNSE` and `pathBSE` match the source CTCL's AutoOnlineBackup paths. Keep `{formatted_date}` in both paths.
- `multiplier` is correct for this setup.
- `copy_source_id` contains the source account ID.
- `source_strategy_names` includes `GREEKSOFT` and any other source strategy names that should be copied.
- `broker` is correct: `GREEK` or `STRATX`.

For GreekSoft:

- `urll` matches the destination account's broker: ShareIndia uses `14.143.11.114:3344`; Motilal uses `142.79.250.226:3344`.
- `username` is the destination account ID.
- The password and account-type settings are correct, and `greek_session_token_file` points to the correct destination account's token file.

For StratX:

- `id`, `strategy_name`, `secret_key`, and `stratX_url` are correct for the destination setup.
- `STRATX_NET_CLIENT_ID` is `Y05601` for this setup.

For either broker:

- Review freeze quantities and `redis_sources` in **`shared_config.py`.**

## 3. Net quantity limits

Use the following setup values for a **1 crore account**. Apply each limit to both CE and PE.

| Limit           | 1 crore account | 50 crore account |
| --------------- | --------------: | ---------------: |
| NIFTY positive  |            1000 |            50000 |
| NIFTY negative  |            3770 |           188500 |
| SENSEX positive |             340 |            17000 |
| SENSEX negative |            1300 |            65000 |

For another account size, multiply the 1 crore values by the account size in crores. For example, a 50 crore account uses each base value multiplied by `50`. These are net quantities, not lot counts. Enter negative-side limits as positive numbers.

- Set `NIFTY_CE_POS_NET` and `NIFTY_PE_POS_NET` to `1000 × account size in crores`.
- Set `NIFTY_CE_NEG_NET` and `NIFTY_PE_NEG_NET` to `3770 × account size in crores`.
- Set `SENSEX_CE_POS_NET` and `SENSEX_PE_POS_NET` to `340 × account size in crores`.
- Set `SENSEX_CE_NEG_NET` and `SENSEX_PE_NEG_NET` to `1300 × account size in crores`.

## 4. Environment and network access

- `.env` contains `COPY_ALLOWED_DELAY_SECONDS` with the intended value for either broker.
- For StratX, `.env` also contains `OPTION_INSTRUMENT_CSV`, and that CSV is accessible from the Copy Trade PC.
- Tailscale is connected, and the required Redis sources and network shares are reachable.
- On the PC running Copy Trade, confirm you can open the source trade files. For GreekSoft, copy the path from `greek_session_token_file` in `credentials.py`, paste it into File Explorer's top address bar, and press **Enter**. If asked, enter the server's username and password and tick **Remember my credentials**. Confirm the token file opens; do not change its contents.

### Save credentials for the required PCs

From the Windows user who will run Copy Trade:

1. Open **File Explorer → Network**.
2. In the address bar at the top, enter the required PC's Tailscale IP with two leading backslashes, for example `\\100.103.231.7`, and press **Enter**.
3. In the login dialog, enter that remote PC's Windows username and password.
4. Tick **Remember my credentials** and click **OK**.
5. Repeat for all PCs whose shared files are needed by this setup, especially:

| PC | Enter in the File Explorer address bar |
| --- | --- |
| Desktop-CLI | `\\100.103.231.7` |
| Main server | `\\100.92.173.15` |
| Backup server | `\\100.68.131.14` |

After connecting, open the required shared folders and confirm the source trade files, instrument CSV, or GreekSoft token file can be read, as applicable.

## 5. GreekSoft checks in Postman

For a GreekSoft destination such as `TS123`, use that destination account's credentials and the correct broker server.

- Check the session-token API and confirm a token is generated.
- Check `getFlagValues` and confirm no error is there.
- Check `getLoginInfo` and confirm login succeeds for the destination account.
- If token generation, flag values, or login fails, contact GreekSoft with the account ID and error response. Resolve this before starting the copy trade.

## 6. Check the Copy Trade window and start

- Launch Copy Trade using `run.cmd`.
- Check the heading. The left side is the source account ID. For GreekSoft, the right side is the destination account ID; for StratX, it is the destination strategy name.
- Open or hover over the information/eye button and verify the source ID, multiplier, and all net quantity limits.
- Click **Start Algo** and wait for:

```text
File watcher started - zero-sleep signal detection active
```

- Check the logs for startup errors. Investigate session-token, login, source-header, instrument-file, and Redis errors before treating the setup as ready.
- If a header mismatch appears, first confirm **With Strategy Column Name** and **With Header** are ticked in the source CTCL, then restart Copy Trade. If the header issue still appears after restarting, it needs further investigation.
- If an occasional GreekSoft orderbook request times out and later requests resume normally, that alone does not mean the Copy Trade setup is wrong. Repeated timeouts, order-placement timeouts, or a stopped thread need checking.

The file-watcher message confirms that file monitoring started. The trade check below confirms copying works.

## 7. Verify one source trade

- Ask the trader to place **one lot** in the source account.
- Confirm the trade appears in the correct source AUTOTRD file.
- Confirm Copy Trade detects it and the destination receives and executes the expected order, allowing for the configured multiplier and net limits.
- Verify the account, contract, side, and quantity.
- Once the trade is verified, mark the setup or update check complete.
