import atexit
import datetime
import json
import os
import threading
import time

import pandas as pd
from async_logger import printt


class StratXReconciliation:
    def __init__(self, broker, nse_path, bse_path, copy_source_id, client_id, multiplier, strategy_name, order_url, is_market_open, interval_seconds=30, required_confirmations=3, cooldown_seconds=120, report_only=True, state_file="stratx_recon_state.json"):
        self.broker = broker
        self.nse_path = nse_path
        self.bse_path = bse_path
        self.copy_source_id = str(copy_source_id).strip().upper()
        self.client_id = str(client_id).strip().upper()
        self.multiplier = float(multiplier or 1)
        self.strategy_name = str(strategy_name).strip()
        self.order_url = str(order_url).strip()
        self.is_market_open = is_market_open
        self.interval_seconds = max(float(interval_seconds), 3.0)
        self.required_confirmations = max(int(required_confirmations), 2)
        self.cooldown_seconds = max(float(cooldown_seconds), 30)
        self.report_only = bool(report_only)
        self.state_file = state_file

        self.confirmations = {}
        self.pending = {}
        self.cooldowns = {}
        self.source_cache = {}
        self.state_lock = threading.Lock()
        self.state_save_lock = threading.Lock()
        self.state_dirty = False
        self.started = False

        self.broker.reconciliation_manager = self

    def today_key(self):
        return datetime.datetime.now().strftime("%Y%m%d")

    def load_state(self):
        state = None
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r") as state_file:
                    state = json.load(state_file)
        except Exception as e:
            printt(f"STRATX_RECON_STATE_LOAD_FAILED | error={e}")

        pending = {}
        cooldowns = {}
        if isinstance(state, dict) and state.get("date") == self.today_key():
            if isinstance(state.get("pending"), dict):
                pending = state["pending"]
            if isinstance(state.get("cooldowns"), dict):
                cooldowns = state["cooldowns"]

        now = time.time()
        cleaned_pending = {}
        for contract_key, meta in pending.items():
            if not isinstance(meta, dict):
                printt(f"STRATX_RECON_STATE_PENDING_SKIPPED | contract={contract_key} | reason=invalid_state")
                continue
            root_order_id = str(meta.get("root_order_id", "")).strip()
            if root_order_id:
                cleaned_pending[str(contract_key)] = dict(meta)

        cleaned_cooldowns = {}
        for contract_key, cooldown_until in cooldowns.items():
            try:
                cooldown_until = float(cooldown_until)
                if cooldown_until > now:
                    cleaned_cooldowns[str(contract_key)] = cooldown_until
            except Exception as e:
                printt(f"STRATX_RECON_STATE_COOLDOWN_SKIPPED | contract={contract_key} | error={e}")

        with self.state_lock:
            self.pending = cleaned_pending
            self.cooldowns = cleaned_cooldowns
            self.confirmations = {}
            self.state_dirty = not isinstance(state, dict) or state.get("date") != self.today_key()

        printt(f"STRATX_RECON_STATE_LOADED | pending={len(cleaned_pending)} | cooldowns={len(cleaned_cooldowns)} | confirmations_reset=1")

    def state_snapshot_locked(self):
        return {
            "date": self.today_key(),
            "pending": {key: dict(value) for key, value in self.pending.items()},
            "cooldowns": dict(self.cooldowns),
        }

    def save_state_now(self):
        with self.state_save_lock:
            try:
                with self.state_lock:
                    snapshot = self.state_snapshot_locked()
                    self.state_dirty = False

                temp_path = f"{self.state_file}.tmp"
                with open(temp_path, "w") as state_file:
                    json.dump(snapshot, state_file, indent=2)
                os.replace(temp_path, self.state_file)
            except Exception as e:
                with self.state_lock:
                    self.state_dirty = True
                printt(f"STRATX_RECON_STATE_SAVE_FAILED | error={e}")

    def state_saver_loop(self):
        while True:
            try:
                time.sleep(1)
                with self.state_lock:
                    should_save = self.state_dirty
                if should_save:
                    self.save_state_now()
            except Exception as e:
                printt(f"STRATX_RECON_STATE_SAVER_ERROR | error={e}")
                time.sleep(1)

    def start(self):
        if self.started:
            return
        self.started = True
        self.load_state()
        threading.Thread(target=self.state_saver_loop, daemon=True).start()
        threading.Thread(target=self.reconciliation_loop, daemon=True).start()
        atexit.register(self.save_state_now)
        printt(f"STRATX_RECON_STARTED | interval={self.interval_seconds:g}s | confirmations={self.required_confirmations} | cooldown={self.cooldown_seconds:g}s | report_only={self.report_only}")

    def contract_key(self, exchange, symbol, expiry, strike, right):
        normalized_strike = float(strike)
        strike_text = str(int(normalized_strike)) if normalized_strike.is_integer() else str(normalized_strike)
        return "|".join((str(exchange).strip().upper(), str(symbol).strip().upper(), str(expiry).strip(), strike_text, str(right).strip().upper()))

    def parse_contract_key(self, contract_key):
        exchange, symbol, expiry, strike, right = str(contract_key).split("|", 4)
        return exchange, symbol, expiry, float(strike), right

    def file_signature(self, path):
        stat = os.stat(path)
        return stat.st_mtime_ns, stat.st_size

    def read_source(self, path, separator, max_retries=3):
        if not path or not os.path.exists(path):
            self.source_cache.pop(path, None)
            return None, False, None
        try:
            if os.path.getsize(path) == 0:
                self.source_cache.pop(path, None)
                return None, False, None
        except FileNotFoundError:
            self.source_cache.pop(path, None)
            return None, False, None

        try:
            signature = self.file_signature(path)
            cached = self.source_cache.get(path)
            if cached and cached.get("signature") == signature:
                return cached.get("positions"), True, signature
        except Exception as e:
            printt(f"STRATX_RECON_SOURCE_READ_FAILED | path={path} | error={e}")
            return None, False, None

        for attempt in range(max_retries):
            try:
                signature = self.file_signature(path)
                frame = pd.read_csv(path, header=None, engine="python", sep=separator, on_bad_lines="skip")
                if frame.empty:
                    return None, False, None

                cache_signature = signature if self.file_signature(path) == signature else None
                if cache_signature is None:
                    printt(f"STRATX_RECON_SOURCE_CHANGED | path={path} | action=use_snapshot_without_cache")
                return frame, True, cache_signature
            except pd.errors.EmptyDataError:
                self.source_cache.pop(path, None)
                return None, False, None
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))
                else:
                    printt(f"STRATX_RECON_SOURCE_READ_FAILED | path={path} | error={e}")
        return None, False, None

    def transform_contract(self, symbol, expiry, strike, right, quantity):
        strategy_key = self.strategy_name.upper()
        final_strike = float(strike)
        final_quantity = int(float(quantity) * self.multiplier)

        if strategy_key == "VOLATILITY CORE":
            final_quantity *= 2
        elif strategy_key == "IMPULSE CORE":
            final_strike = self.broker.get_otm_strike(symbol, right, final_strike, offset=self.broker.impulse_offset)

        if final_strike is None or final_quantity <= 0:
            return None, 0
        return float(final_strike), final_quantity

    def build_nse_positions(self, frame):
        positions = {}
        for row in frame.itertuples(index=False, name=None):
            try:
                if len(row) <= 27:
                    continue
                if self.copy_source_id and str(row[27]).strip().upper() != self.copy_source_id:
                    continue
                if str(row[2]).strip().upper() != "OPTIDX":
                    continue
                if str(row[3]).strip().upper() != "NIFTY":
                    continue

                right = str(row[6]).strip().upper()
                if right not in ("CE", "PE"):
                    continue
                expiry = self.broker.to_yyyymmdd(row[4])
                strike, quantity = self.transform_contract("NIFTY", expiry, row[5], right, row[14])
                if not expiry or strike is None or quantity <= 0:
                    continue

                side = "BUY" if int(float(row[13])) == 1 else "SELL"
                signed_quantity = quantity if side == "BUY" else -quantity
                key = self.contract_key("NSEFO", "NIFTY", expiry, strike, right)
                positions[key] = positions.get(key, 0) + signed_quantity
            except Exception as e:
                printt(f"STRATX_RECON_NSE_ROW_SKIPPED | error={e}")
        return positions

    def build_bse_positions(self, frame):
        positions = {}
        for row in frame.itertuples(index=False, name=None):
            try:
                if len(row) <= 17:
                    continue
                if self.copy_source_id and str(row[-1]).strip().upper() != self.copy_source_id:
                    continue
                if "OPT" not in str(row[17]).strip().upper():
                    continue
                if not str(row[5]).strip().upper().startswith("SENSEX"):
                    continue

                symbol, strike, expiry, right, _, _ = self.broker.get_bse_contract_details(row[4])
                symbol = str(symbol).strip().upper()
                right = str(right).strip().upper()
                if symbol != "SENSEX" or right not in ("CE", "PE"):
                    continue

                strike, quantity = self.transform_contract(symbol, expiry, strike, right, row[7])
                if strike is None or quantity <= 0:
                    continue

                side = str(row[6]).strip().upper()
                signed_quantity = quantity if side == "B" else -quantity
                key = self.contract_key("BSEFO", "SENSEX", expiry, strike, right)
                positions[key] = positions.get(key, 0) + signed_quantity
            except Exception as e:
                printt(f"STRATX_RECON_BSE_ROW_SKIPPED | error={e}")
        return positions

    def desired_positions(self):
        desired = {}
        valid_exchanges = set()

        nse_source, nse_ok, nse_signature = self.read_source(self.nse_path, ",")
        if nse_ok:
            if isinstance(nse_source, pd.DataFrame):
                nse_positions = self.build_nse_positions(nse_source)
                if nse_signature is not None:
                    self.source_cache[self.nse_path] = {"signature": nse_signature, "positions": nse_positions}
                else:
                    self.source_cache.pop(self.nse_path, None)
            else:
                nse_positions = dict(nse_source or {})
            desired.update(nse_positions)
            valid_exchanges.add("NSEFO")

        bse_source, bse_ok, bse_signature = self.read_source(self.bse_path, "|")
        if bse_ok:
            if isinstance(bse_source, pd.DataFrame):
                bse_positions = self.build_bse_positions(bse_source)
                if bse_signature is not None:
                    self.source_cache[self.bse_path] = {"signature": bse_signature, "positions": bse_positions}
                else:
                    self.source_cache.pop(self.bse_path, None)
            else:
                bse_positions = dict(bse_source or {})
            desired.update(bse_positions)
            valid_exchanges.add("BSEFO")

        return desired, valid_exchanges

    def actual_positions(self):
        try:
            rows = self.broker.fetch_stratx_traded_orders()
        except Exception as e:
            printt(f"STRATX_RECON_TRADED_FETCH_FAILED | error={e}")
            return None, None
        if rows is None:
            return None, None

        with self.broker.retry_state_lock:
            reference_map = dict(self.broker.retry_state.get("reference_id_to_root_id", {}) if isinstance(self.broker.retry_state, dict) else {})

        positions = {}
        traded_by_root = {}
        seen_row_ids = set()
        for row in rows:
            try:
                status = str(self.broker.get_orderbook_row_value(row, "status", "")).strip().upper()
                if status and status != "TRADED":
                    continue
                row_client = str(self.broker.get_orderbook_row_value(row, "client_id", "")).strip().upper()
                if row_client != self.client_id:
                    continue

                row_id = self.broker.get_orderbook_row_value(row, "id", None)
                if row_id not in (None, ""):
                    row_id = str(row_id)
                    if row_id in seen_row_ids:
                        continue
                    seen_row_ids.add(row_id)

                symbol = self.broker.get_retry_pricing_symbol(self.broker.get_orderbook_row_value(row, "symbol", ""))
                symbol = str(symbol).strip().upper()
                if symbol not in ("NIFTY", "SENSEX"):
                    continue
                right = str(self.broker.get_orderbook_row_value(row, "right", "")).strip().upper()
                if right not in ("CE", "PE"):
                    continue
                exchange = str(self.broker.get_orderbook_row_value(row, "exchange", "")).strip().upper()
                if exchange not in ("NSEFO", "BSEFO"):
                    exchange = "NSEFO" if symbol == "NIFTY" else "BSEFO"
                expiry = self.broker.to_yyyymmdd(self.broker.get_orderbook_row_value(row, "expiry", ""))
                strike = float(self.broker.get_orderbook_row_value(row, "strike", 0))
                quantity = self.broker.get_stratx_traded_quantity(row)
                if not expiry or strike <= 0 or quantity <= 0:
                    continue

                side = str(self.broker.get_orderbook_row_value(row, "buyorsell", "")).strip().upper()
                signed_quantity = quantity if side in ("BUY", "B", "1") else -quantity
                key = self.contract_key(exchange, symbol, expiry, strike, right)
                positions[key] = positions.get(key, 0) + signed_quantity

                reference_id = str(self.broker.get_orderbook_row_value(row, "reference_id", "")).strip()
                root_order_id = reference_map.get(reference_id)
                if root_order_id:
                    root_key = str(root_order_id)
                    traded_by_root[root_key] = traded_by_root.get(root_key, 0) + quantity
            except Exception as e:
                printt(f"STRATX_RECON_TRADED_ROW_SKIPPED | error={e}")

        return positions, traded_by_root

    def mark_correction_submitted(self, contract_key, root_order_id, quantity, side):
        root_key = str(root_order_id)
        with self.state_lock:
            existing = self.pending.get(contract_key)
            if existing and str(existing.get("root_order_id")) == root_key:
                return
            self.pending[contract_key] = {
                "root_order_id": root_key,
                "side": str(side).strip().upper(),
                "submitted_qty": int(float(quantity)),
                "submitted_at": time.time(),
            }
            self.confirmations.pop(contract_key, None)
            self.state_dirty = True
        self.save_state_now()
        printt(f"STRATX_RECON_CORRECTION_SUBMITTED | contract={contract_key} | root_id={root_key} | side={side} | qty={int(float(quantity))}")

    def mark_correction_failed(self, root_order_id, contract_key=None, reason="unknown"):
        root_key = str(root_order_id)
        with self.state_lock:
            matched_key = contract_key if contract_key in self.pending else None
            if matched_key is None:
                for candidate_key, meta in self.pending.items():
                    if str(meta.get("root_order_id")) == root_key:
                        matched_key = candidate_key
                        break
            if matched_key is None:
                return
            self.pending.pop(matched_key, None)
            self.confirmations.pop(matched_key, None)
            self.cooldowns[matched_key] = time.time() + self.cooldown_seconds
            self.state_dirty = True
        self.save_state_now()
        printt(f"STRATX_RECON_CORRECTION_FAILED | contract={matched_key} | root_id={root_key} | reason={reason} | cooldown={self.cooldown_seconds:g}s")

    def settle_traded_corrections(self, traded_by_root):
        settled = []
        with self.state_lock:
            for contract_key, meta in self.pending.items():
                root_order_id = str(meta.get("root_order_id", ""))
                submitted_qty = int(float(meta.get("submitted_qty", 0)))
                if submitted_qty > 0 and traded_by_root.get(root_order_id, 0) >= submitted_qty:
                    settled.append((contract_key, root_order_id))

            for contract_key, _ in settled:
                self.pending.pop(contract_key, None)
                self.confirmations.pop(contract_key, None)
                self.cooldowns[contract_key] = time.time() + self.cooldown_seconds
                self.state_dirty = True

        if settled:
            self.save_state_now()
            for contract_key, root_order_id in settled:
                printt(f"STRATX_RECON_CORRECTION_TRADED | contract={contract_key} | root_id={root_order_id} | cooldown={self.cooldown_seconds:g}s")

    def submit_correction(self, contract_key, difference):
        try:
            return self._submit_correction(contract_key, difference)
        except Exception as e:
            printt(f"STRATX_RECON_CORRECTION_ERROR | contract={contract_key} | diff={difference} | error={e}")
            return False

    def _submit_correction(self, contract_key, difference):
        correction_start_ts = time.perf_counter()
        timing_ctx = {
            "worker_dequeue_ts": correction_start_ts,
            "broker_entry_ts": correction_start_ts,
        }
        exchange, symbol, expiry, strike, right = self.parse_contract_key(contract_key)
        side = "BUY" if difference > 0 else "SELL"
        quantity = abs(int(difference))

        lot_size = type(self.broker).lot_size_by_name.get(symbol)
        if lot_size is None:
            lot_size = 65 if symbol == "NIFTY" else 20
        lot_size = int(float(lot_size))
        if quantity <= 0 or lot_size <= 0 or quantity % lot_size != 0:
            printt(f"STRATX_RECON_CORRECTION_SKIPPED | contract={contract_key} | qty={quantity} | lot_size={lot_size} | reason=invalid_lot_quantity")
            return False

        description, tick_size = self.broker.get_retry_instrument_details(symbol, exchange, expiry, right, strike)
        freeze_quantity = self.broker.get_retry_freeze_quantity(symbol)
        if not description or tick_size is None or freeze_quantity is None:
            printt(f"STRATX_RECON_CORRECTION_SKIPPED | contract={contract_key} | reason=instrument_details_unavailable")
            return False

        cache_symbol = self.broker.build_cache_symbol(symbol, self.broker.to_ddmmmyy(expiry), strike, right)
        price_start_ts = time.perf_counter()
        price = self.broker.price_from_avg_ltp_or_fallback(side=side, tick_size=tick_size, cache_symbol=cache_symbol)
        timing_ctx["price_calc_ms"] = (time.perf_counter() - price_start_ts) * 1000

        payload_symbol = self.broker.get_retry_payload_symbol(symbol, exchange)
        orders = self.broker.place_stratx_single_order(self.order_url, self.strategy_name, payload_symbol, strike, expiry, side, quantity, price, exchange, "NFO-OPT" if exchange == "NSEFO" else "BFO-OPT", right, freeze_quantity, lot_size=lot_size, csv_read_ts=correction_start_ts, timing_ctx=timing_ctx, client_ids=None, description=description, reconciliation_key=contract_key)
        if not orders:
            printt(f"STRATX_RECON_CORRECTION_SKIPPED | contract={contract_key} | reason=placement_not_submitted")
            return False
        return True

    def compare_positions(self, desired, actual, valid_exchanges, unsettled_contracts):
        all_contracts = set(desired) | set(actual)
        active_contracts = {
            contract_key
            for contract_key in all_contracts
            if contract_key.split("|", 1)[0] in valid_exchanges
        }

        for contract_key in sorted(active_contracts):
            desired_qty = int(desired.get(contract_key, 0))
            actual_qty = int(actual.get(contract_key, 0))
            difference = desired_qty - actual_qty

            now = time.time()
            with self.state_lock:
                is_pending = contract_key in self.pending
                is_unsettled = contract_key in unsettled_contracts
                cooldown_until = float(self.cooldowns.get(contract_key, 0))
                if cooldown_until and cooldown_until <= now:
                    self.cooldowns.pop(contract_key, None)
                    self.state_dirty = True
                    cooldown_until = 0

                if is_pending or cooldown_until > now or difference == 0:
                    self.confirmations.pop(contract_key, None)
                    count = 0
                elif is_unsettled:
                    count = 0
                else:
                    previous = self.confirmations.get(contract_key)
                    if previous and previous.get("diff") == difference:
                        count = min(previous.get("count", 0) + 1, self.required_confirmations)
                    else:
                        count = 1
                    self.confirmations[contract_key] = {"diff": difference, "count": count}

            if is_unsettled and difference != 0:
                printt(f"STRATX_RECON_WAITING_UNSETTLED | contract={contract_key} | desired={desired_qty} | actual={actual_qty} | diff={difference}")
                continue

            if count == 0:
                continue

            action = "BUY" if difference > 0 else "SELL"
            printt(f"STRATX_RECON_MISMATCH | contract={contract_key} | desired={desired_qty} | actual={actual_qty} | diff={difference} | action={action} {abs(difference)} | confirmation={count}/{self.required_confirmations} | report_only={self.report_only}")

            if count < self.required_confirmations or self.report_only:
                continue
            if not self.is_market_open():
                continue

            with self.state_lock:
                self.confirmations.pop(contract_key, None)
            self.submit_correction(contract_key, difference)

        with self.state_lock:
            for contract_key in list(self.confirmations):
                if contract_key not in active_contracts:
                    self.confirmations.pop(contract_key, None)

    def run_once(self):
        if not self.is_market_open():
            return

        desired, valid_exchanges = self.desired_positions()
        if not valid_exchanges:
            return

        actual, traded_by_root = self.actual_positions()
        if actual is None:
            printt("STRATX_RECON_SKIPPED | reason=traded_fetch_failed")
            return

        self.broker.settle_unsettled_traded_roots(traded_by_root)
        self.settle_traded_corrections(traded_by_root)
        self.compare_positions(desired, actual, valid_exchanges, self.broker.get_unsettled_contracts())

    def reconciliation_loop(self):
        while True:
            cycle_start = time.perf_counter()
            try:
                self.run_once()
            except Exception as e:
                printt(f"STRATX_RECON_LOOP_ERROR | error={e}")
            elapsed = time.perf_counter() - cycle_start
            time.sleep(max(0, self.interval_seconds - elapsed))
