"""Manual GreekSoft reconciliation. No I/O or broker initialization at import time."""
import csv
import logging
import math
import os
import threading
import time


logger = logging.getLogger("trade")


def integer(value):
    number = float(value)
    if not math.isfinite(number) or number != int(number) or number < 0:
        raise ValueError(f"Invalid quantity: {value}")
    return int(number)


class GreekPositionSync:
    settlement_seconds = 5.0
    confirmation_attempts = 3
    confirmation_interval = 1.0
    sync_timeout = 15.0

    def __init__(self, broker):
        self.broker = broker
        self.lock = threading.RLock()
        self.run_lock = threading.Lock()
        self.pending = {}
        self.revision = 0
        self.copy_revision = 0
        self.config = None
        self.last_click = -float("inf")
        self.ingesting = 0
        self.observed_trades = {}
        self.observed_exchanges = {}
        self.master = {}

    def configure(self, nse_path, bse_path, source_id, strategies, multiplier,
                  headers, market_open, copy_busy, source_consumed=lambda signatures: True):
        self.config = (nse_path, bse_path, str(source_id).strip().upper(),
                       {str(s).strip().upper() for s in strategies},
                       float(multiplier), headers, market_open, copy_busy)
        self.source_consumed = source_consumed

    def key(self, exchange, symbol, expiry, strike, right):
        exchange, symbol, right = (str(v).strip().upper() for v in (exchange, symbol, right))
        if (exchange, symbol) not in (("NSE", "NIFTY"), ("BSE", "SENSEX")):
            return None
        expiry_text = str(expiry).strip()
        expiry = expiry_text if len(expiry_text) == 8 and expiry_text.isdigit() else self.broker.normalize_expiry_yyyymmdd(expiry)
        strike = float(strike)
        if not expiry or not math.isfinite(strike) or strike <= 0 or right not in ("CE", "PE"):
            raise ValueError("Invalid option contract")
        return exchange, symbol, expiry, strike, right

    def task_key(self, task):
        return self.key(task["exchange"], task["symbol"], task["expiry"], task["strike"], task["option_type"])

    def queued(self, task):
        with self.lock:
            root = task["root_order_id"]
            previous = self.pending.get(root, {})
            self.pending[root] = dict(previous, task=dict(task), key=self.task_key(task),
                                      original_quantity=previous.get("original_quantity", int(task["qty"])),
                                      remaining=int(task["qty"]), status="QUEUED", probe=None)
            self.revision += 1
            if not task.get("sync_correction"):
                self.copy_revision += 1

    def submitting(self, task):
        with self.lock:
            record = self.pending.get(task["root_order_id"])
            if record:
                record["status"] = "SUBMITTING"
                self.revision += 1

    def result(self, task, order_id):
        with self.lock:
            record = self.pending.get(task["root_order_id"])
            if not record:
                return
            if order_id:
                record.update(status="PENDING", order_id=str(order_id))
            elif task.get("submission_uncertain"):
                record.update(status="UNKNOWN", since=time.monotonic(), probe=None)
            else:
                self.pending.pop(task["root_order_id"], None)
            self.revision += 1

    def failed(self, root):
        with self.lock:
            self.pending.pop(str(root), None)
            self.revision += 1

    def busy(self):
        return self.ingesting > 0 or any(p["status"] in ("QUEUED", "SUBMITTING") for p in self.pending.values())

    def begin_ingestion(self):
        """Called only after the copier's existing check detects a changed file."""
        with self.lock:
            self.ingesting += 1
            self.revision += 1
            self.copy_revision += 1

    def end_ingestion(self):
        with self.lock:
            self.ingesting -= 1
            self.revision += 1

    @staticmethod
    def signature(path):
        stat = os.stat(path)
        return stat.st_size, stat.st_mtime_ns

    def targets(self):
        nse, bse, source_id, strategies, multiplier, headers, _, _ = self.config
        if not source_id or not strategies or not math.isfinite(multiplier) or multiplier <= 0:
            raise ValueError("Source filters or multiplier missing/invalid")
        positions, instruments, signatures, skipped = {}, {}, {}, {}
        for exchange, path, separator, header in (("NSE", nse, ",", headers[0]), ("BSE", bse, "|", headers[1])):
            try:
                before = self.signature(path)
                stream = open(path, encoding="utf-8-sig", newline="")
            except FileNotFoundError:
                # Missing file is normal only if its parent folder is accessible.
                folder = os.path.dirname(os.path.abspath(path))
                try:
                    with os.scandir(folder):
                        pass
                except OSError as error:
                    raise OSError(f"{exchange} source folder inaccessible: {folder}: {error}") from error
                skipped[exchange] = "No source file"
                continue
            count = 0
            with stream:
                reader = csv.reader(stream, delimiter=separator)
                first = tuple(v.strip() for v in next(reader, []))
                if not any(first):
                    skipped[exchange] = "No source data"
                    continue
                if first != header:
                    raise ValueError(f"{exchange} source header missing/mismatched")
                for row in reader:
                    if not row or not any(v.strip() for v in row):
                        continue
                    if exchange == "NSE":
                        # NSE exports can end with an extra comma; discard only
                        # empty fields beyond the complete, fixed-position layout.
                        if len(row) < len(header) or any(v.strip() for v in row[len(header):]):
                            raise ValueError(f"{exchange} incomplete source row")
                        row = row[:len(header)]
                        id_index, strategy_index = 27, 26
                    else:
                        # The compact BSE export combines book/instrument at 17
                        # and shifts the tail left once. Reject other short layouts.
                        compact = (len(row) == 23 and row[17].strip().upper() == "L,BSE OPT"
                                   and row[20].strip().upper() == "CARRYFORWARD")
                        if len(row) != len(header) and not compact:
                            raise ValueError(f"{exchange} incomplete source row")
                        id_index, strategy_index = -1, -2
                    if row[id_index].strip().upper() != source_id or row[strategy_index].strip().upper() not in strategies:
                        continue
                    if exchange == "NSE":
                        if row[2].strip().upper() != "OPTIDX" or row[3].strip().upper() != "NIFTY":
                            continue
                        side, quantity = row[13].strip(), integer(row[14])
                        if side not in ("1", "2"):
                            raise ValueError("Invalid NSE side")
                        dt = self.broker.getData(row)
                    else:
                        if "OPT" not in row[17].strip().upper() or not row[5].strip().upper().startswith("SENSEX"):
                            continue
                        side, quantity = row[6].strip().upper(), integer(row[7])
                        if side not in ("B", "S"):
                            raise ValueError("Invalid BSE side")
                        dt = self.broker.getDataBSE(row[4])
                    if dt is None:
                        raise ValueError("Source contract mapping failed")
                    key = self.key(exchange, dt.Symbol, dt.ExpiryDate, dt.StrikePrice, dt.OptionType)
                    if key is None:
                        raise ValueError("Source contract maps outside sync scope")
                    signed = quantity if side in ("1", "B") else -quantity
                    positions[key] = positions.get(key, 0) + signed
                    instruments[key] = dt
                    count += 1
            if before != self.signature(path):
                raise ValueError("Source changed while reading; press Sync again")
            if not count:
                skipped[exchange] = "No matching source data"
                continue
            signatures[path] = before
        for key, quantity in positions.items():
            target = quantity * multiplier
            if not math.isfinite(target) or target != int(target) or int(target) % int(instruments[key].LotSize):
                raise ValueError("Target is not a valid lot multiple")
            positions[key] = int(target)
        return positions, instruments, signatures, skipped

    def book(self, rows, exchanges=None):
        if not isinstance(rows, list):
            raise ValueError("GreekSoft order book unavailable")
        get = self.broker.get_orderbook_row_value
        seen, traded, active, indexed, instruments = {}, {}, {}, {}, {}
        master = self.master
        if not master:
            raise ValueError("GreekSoft sync instrument lookup unavailable")
        for row in rows:
            if str(get(row, "instrument", "")).strip().upper() != "OPTIDX":
                continue
            symbol = str(get(row, "scripName", "")).strip().upper()
            exchange = str(get(row, "exchange", "")).strip().upper()
            if exchanges is not None and exchange not in exchanges:
                continue
            if (exchange, symbol) not in (("NSE", "NIFTY"), ("BSE", "SENSEX")):
                continue
            # The order book returns the exchange token, not the placement gtoken.
            token = integer(get(row, "exch_Token", None))
            dt = master.get((exchange, symbol, token))
            if dt is None or str(dt.Symbol).strip().upper() != symbol:
                raise ValueError("Destination contract token missing/ambiguous")
            key = self.key(exchange, symbol, dt.ExpiryDate, dt.StrikePrice, dt.OptionType)
            if key is None or str(get(row, "optionType", "")).strip().upper() != key[-1]:
                raise ValueError("Destination contract mapping mismatch")
            order_id = str(get(row, "gorderid", "")).strip()
            if not order_id:
                raise ValueError("Order-book row missing gorderid")
            qty, pending = integer(get(row, "traded_qty", None)), integer(get(row, "pending_qty", None))
            if qty < self.observed_trades.get(order_id, 0):
                raise ValueError("Order book has gone backwards; wait for a fresh snapshot")
            side = self.broker.normalize_order_side(get(row, "side", ""))
            sign = 1 if side == "BUY" else -1
            status = str(get(row, "order_status", "")).strip().upper()
            terminal = status in ("TRADED", "CANCELLED", "CANCELED", "EXCHANGE REJECTED", "REJECTED")
            fingerprint = (key, sign, qty, pending, status)
            if order_id in seen:
                if seen[order_id] != fingerprint:
                    raise ValueError("Conflicting duplicate order-book rows")
                continue
            seen[order_id] = fingerprint
            traded[key] = traded.get(key, 0) + sign * qty
            if not terminal:
                if not status:
                    raise ValueError("Missing active order status")
                active[order_id] = (key, sign * pending)
            indexed[order_id] = (key, qty, pending, status, row)
            instruments[key] = dt
        observed = self.observed_trades if exchanges is None else {
            oid: quantity for oid, quantity in self.observed_trades.items()
            if self.observed_exchanges.get(oid) in exchanges}
        if any(quantity > 0 and oid not in indexed for oid, quantity in observed.items()):
            raise ValueError("Previously traded orders missing; order book is incomplete")
        return traded, active, indexed, instruments

    def expected(self, rows, parsed=None, exchanges=None):
        traded, active, indexed, instruments = self.book(rows, exchanges) if parsed is None else parsed
        expected = dict(traded)
        represented = set()
        unresolved = set()
        recovered_contract_total = False
        get = self.broker.get_orderbook_row_value
        for root, record in list(self.pending.items()):
            key, task = record["key"], record["task"]
            if exchanges is not None and (key is None or key[0] not in exchanges):
                continue
            order_id = record.get("order_id")
            if record["status"] == "UNKNOWN" and task.get("sync_correction"):
                with self.broker.greek_retry_state_lock:
                    previous_ids = self.broker.greek_retry_state.get("gorderid_to_root_id", {})
                matches = [oid for oid, data in indexed.items()
                           if oid not in previous_ids and
                           (str(get(data[4], "tag", "")) == root or str(get(data[4], "userTag", "")) == root)]
                if len(matches) == 1:
                    order_id = matches[0]
                    self.broker.register_greek_order_id(root, order_id)
                    record.update(order_id=order_id, status="PENDING")
            if record["status"] == "UNKNOWN":
                now = time.monotonic()
                fingerprint = (traded.get(key, 0), tuple(sorted((oid, qty) for oid, (k, qty) in active.items() if k == key)))
                probe = record.get("probe")
                if now - record["since"] < self.settlement_seconds:
                    unresolved.add(key)
                elif probe is None or probe[1] != fingerprint:
                    record["probe"] = (now, fingerprint)
                    unresolved.add(key)
                elif now - probe[0] < 1.0:
                    unresolved.add(key)
                else:
                    # Bounded recovery: use the full contract total instead of an unidentifiable local child.
                    self.pending.pop(root)
                    recovered_contract_total = True
                continue
            if order_id in indexed:
                data = indexed[order_id]
                if data[0] != key or self.broker.normalize_order_side(get(data[4], "side", "")) != self.broker.normalize_order_side(task["side"]):
                    raise ValueError("Tracked order contract mismatch")
                represented.add(order_id)
                record["remaining"] = data[2]
                if data[3] == "TRADED" or (data[2] == 0):
                    self.pending.pop(root)
                    continue
            sign = 1 if self.broker.normalize_order_side(task["side"]) == "BUY" else -1
            if key:
                expected[key] = expected.get(key, 0) + sign * record["remaining"]
        for order_id, (key, qty) in active.items():
            if order_id not in represented:
                expected[key] = expected.get(key, 0) + qty
        for order_id, data in indexed.items():
            self.observed_trades[order_id] = data[1]
            self.observed_exchanges[order_id] = data[0][0]
        if recovered_contract_total and not unresolved:
            # An uncertain submission kept its risk reservation. Replace it from the
            # same snapshot, so accepted fills are retained and absent orders release risk.
            self.refresh_risk(expected, exchanges, unresolved)
        return expected, instruments, unresolved

    def refresh_risk(self, expected, exchanges, unresolved):
        """Caller holds self.lock; preserve skipped and uncertain risk buckets."""
        included_symbols = {symbol for exchange, symbol in (("NSE", "NIFTY"), ("BSE", "SENSEX"))
                            if exchanges is None or exchange in exchanges}
        uncertain = {f"{key[1]}_{key[4]}" for key in unresolved}
        net = {bucket: 0 for bucket in self.broker.greek_net_buckets
               if bucket.split("_")[0] in included_symbols and bucket not in uncertain}
        for key, quantity in expected.items():
            bucket = f"{key[1]}_{key[4]}"
            if bucket in net:
                net[bucket] += quantity
        with self.broker.greek_net_lock:
            changed = {bucket: quantity for bucket, quantity in net.items()
                       if self.broker.greek_net_position.get(bucket) != quantity}
            if changed:
                self.broker.greek_net_position.update(changed)
                self.broker.greek_net_state_dirty = True
        if changed:
            logger.info("GREEK_POSITION_SYNC_RISK_REFRESH | net=%s", changed)

    def sync(self):
        result = self._sync()
        logger.info("GREEK_POSITION_SYNC_RESULT | %s", result)
        return result

    def snapshot(self, deadline):
        """One fresh comparison. Return None if normal copying invalidated it."""
        copy_busy = self.config[-1]
        with self.lock:
            if self.busy() or copy_busy():
                return None
            revision, copy_revision = self.revision, self.copy_revision
        targets, instruments, signatures, skipped = self.targets()
        if time.monotonic() >= deadline or not self.source_consumed(signatures):
            return None
        exchanges = {exchange for exchange, path in zip(("NSE", "BSE"), self.config[:2]) if path in signatures}
        if not exchanges:
            return targets, instruments, signatures, ({}, {}, {}, {}), set(), {}, copy_revision, skipped
        book = self.broker.getOrderBookALL()
        rows = book.get("data") if isinstance(book, dict) else None
        parsed = self.book(rows, exchanges)
        self.broker.retry_failed_greeksoft_orders([data[4] for data in parsed[2].values()])
        if any(self.signature(path) != signature for path, signature in signatures.items()):
            return None
        with self.lock:
            if self.revision != revision or self.busy() or copy_busy():
                return None
            expected, destination_instruments, unresolved = self.expected(rows, parsed, exchanges)
        instruments.update(destination_instruments)
        differences = {key: targets.get(key, 0) - expected.get(key, 0)
                       for key in set(targets) | set(expected)}
        differences = {key: quantity for key, quantity in differences.items() if quantity}
        return targets, instruments, signatures, parsed, unresolved, differences, copy_revision, skipped

    def confirmed_snapshot(self, deadline):
        copy_busy = self.config[-1]
        for attempt in range(self.confirmation_attempts):
            # Only the Sync worker waits. Copy threads never wait on this sleep.
            while time.monotonic() < deadline:
                with self.lock:
                    busy = self.busy() or copy_busy()
                if not busy:
                    break
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            if deadline - time.monotonic() <= self.confirmation_interval:
                return None
            first = self.snapshot(deadline)
            if first is None:
                continue
            if deadline - time.monotonic() <= self.confirmation_interval:
                return None
            time.sleep(self.confirmation_interval)
            second = self.snapshot(deadline)
            if time.monotonic() >= deadline:
                return None
            if second is None:
                continue
            # Source targets/versions, difference and copy generation must agree.
            if (first[0], first[2], first[4], first[5], first[6], first[7]) == (second[0], second[2], second[4], second[5], second[6], second[7]):
                return second
            # Only build diagnostic details for a discarded pair; no extra fetches.
            changes = {}
            for index, name in ((0, "source_target_changed"), (2, "source_file_changed"),
                                (4, "unresolved_orders_changed"), (5, "correction_changed"),
                                (6, "copy_activity_changed"), (7, "skipped_exchanges_changed")):
                before, after = first[index], second[index]
                if before == after:
                    continue
                if isinstance(before, dict):
                    default = 0 if index in (0, 5) else None
                    changes[name] = {key: {"before": before.get(key, default), "after": after.get(key, default)}
                                     for key in sorted(set(before) | set(after))
                                     if before.get(key, default) != after.get(key, default)}
                else:
                    changes[name] = {"before": sorted(before) if isinstance(before, set) else before,
                                     "after": sorted(after) if isinstance(after, set) else after}
            logger.info("GREEK_POSITION_SYNC_RECHECK | attempt=%s | reason=%s | changes=%s",
                        attempt + 1, ",".join(changes), changes)
        return None

    def _sync(self):
        if self.config is None:
            return "Start algo before syncing positions"
        if not self.run_lock.acquire(blocking=False):
            return "Position Sync is already running"
        try:
            if time.monotonic() - self.last_click < 5:
                return "Please wait five seconds between Sync requests"
            self.last_click = time.monotonic()
            deadline = self.last_click + self.sync_timeout
            _, _, _, _, _, _, market_open, copy_busy = self.config
            if not market_open():
                return "Market is closed"
            with self.lock:
                if self.busy() or copy_busy():
                    return "Copy orders are processing; press Sync after submission finishes"
            confirmed = self.confirmed_snapshot(deadline)
            if confirmed is None:
                return "Positions changed during Sync or source rows are awaiting copy processing. No corrections submitted; try again"
            targets, instruments, signatures, parsed, unresolved, differences, copy_revision, skipped = confirmed
            note = "; skipped " + ", ".join(f"{exchange}: {reason}" for exchange, reason in skipped.items()) if skipped else ""
            if skipped:
                logger.info("GREEK_POSITION_SYNC_SOURCE_SKIPPED | %s", skipped)
            if not signatures:
                return "No source file/data available; no orders submitted" + note
            corrections = []
            for key, difference in sorted(differences.items()):
                if key in unresolved:
                    continue
                if difference:
                    dt = instruments[key]
                    lot = int(dt.LotSize)
                    if lot <= 0 or abs(difference) % lot:
                        raise ValueError("Correction is not a valid lot multiple")
                    corrections.append((key, difference, dt))
            with self.lock:
                if self.copy_revision != copy_revision or self.busy() or copy_busy():
                    return "Copy processing resumed; press Sync again"
                # Use the confirmed expected position, not the target: the existing
                # placement path will reserve each correction on top of this base.
                expected = {key: targets.get(key, 0) - differences.get(key, 0)
                            for key in set(targets) | set(differences)}
                exchanges = {exchange for exchange, path in zip(("NSE", "BSE"), self.config[:2])
                             if path in signatures}
                self.refresh_risk(expected, exchanges, unresolved)
            submitted = 0
            for key, difference, dt in corrections:
                # Submit one freeze child at a time, releasing the lock while it sends.
                remaining = abs(difference)
                while remaining:
                    if time.monotonic() >= deadline:
                        return f"Submitted {submitted} corrections; Sync time limit reached. Press Sync again"
                    if any(self.signature(path) != signature for path, signature in signatures.items()):
                        return f"Submitted {submitted} corrections; source changed. Press Sync again"
                    with self.lock:
                        if self.copy_revision != copy_revision or self.busy() or copy_busy() or not market_open():
                            return f"Submitted {submitted} corrections; copy processing resumed. Press Sync again"
                        quantity = self.broker.greek_sync_child_quantity(key[0], remaining, dt)
                        count = self.broker.place_greek_sync_correction(key[0], 1 if difference > 0 else 2, quantity, dt)
                        submitted += count
                        remaining -= quantity
                    if not count:
                        return f"Submitted {submitted} corrections; further corrections blocked by net limits or submission failure"
                    logger.info("GREEK_POSITION_SYNC_CORRECTION | contract=%s | side=%s | requested_qty=%s", key, "BUY" if difference > 0 else "SELL", quantity)
                    while True:
                        with self.lock:
                            if self.copy_revision != copy_revision or copy_busy():
                                return f"Submitted {submitted} corrections; copy processing resumed. Press Sync again"
                            waiting = self.busy()
                            unknown = any(p["status"] == "UNKNOWN" and p["key"] == key
                                          for p in self.pending.values())
                        if unknown:
                            logger.info("GREEK_POSITION_SYNC_WAIT_UNKNOWN | contract=%s", key)
                            break
                        if not waiting:
                            break
                        if time.monotonic() >= deadline:
                            return f"Submitted {submitted} corrections; submission is still processing"
                        time.sleep(0.02)
                    if unknown:
                        # Leave this contract pending; other contracts can continue.
                        unresolved.add(key)
                        break
            if submitted:
                return f"Corrections submitted ({submitted} child orders); orders are pending. Press Sync to verify after settlement" + note
            if corrections:
                return "Corrections could not be submitted; check net limits and logs"
            if unresolved:
                return "Waiting for uncertain submissions to settle; press Sync again"
            if any(self.signature(path) != signature for path, signature in signatures.items()):
                return "Source changed; press Sync again"
            with self.lock:
                if self.copy_revision != copy_revision or self.busy() or copy_busy():
                    return "Copy processing resumed; press Sync again"
                exchanges = {exchange for exchange, path in zip(("NSE", "BSE"), self.config[:2]) if path in signatures}
                pending = any(p["key"] is not None and p["key"][0] in exchanges for p in self.pending.values())
            if pending or parsed[1]:
                return "Target covered; orders are pending" + note
            return "Positions synchronized for available source exchanges" + note if skipped else "Positions synchronized"
        except Exception as error:
            logger.exception("GREEK_POSITION_SYNC_FAILED")
            return f"Position Sync failed: {error}"
        finally:
            self.run_lock.release()
