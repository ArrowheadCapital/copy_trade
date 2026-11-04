# CTCL AutoOnlineBackup File Behaviour

This document records the CTCL behaviour.

The AUTOTRD filename contains only the month and day (`MMDD`), without a year. A file left from last year can therefore have the same name as today's file.

## Case 1: No Trades Have Happened Today

1. The AUTOTRD `.txt` file contains last year's trade rows.
2. No trades have happened today in CTCL.
3. Logging in to CTCL leaves the old rows in the file. Login alone does not replace them in this case.
4. When today's first trade happens, CTCL removes the old rows and writes today's trade data into the file.

Until that first trade, the existing file can still contain last year's data even though CTCL is logged in.

## Case 2: Trades Have Already Happened Today

1. Trades have already happened today in CTCL.
2. The AUTOTRD `.txt` file is subsequently changed to contain last year's data.
3. On the next CTCL login, CTCL replaces the old contents with today's trade data.
4. Another trade is not required to trigger this replacement.

In this case, today's trade history already exists, so login restores today's data into the file.

## Difference Between the Cases

| State when logging in to CTCL      | What happens to a file containing last year's rows?                                     |
| ---------------------------------- | --------------------------------------------------------------------------------------- |
| No trades have happened today      | Old rows remain until today's first trade.                                              |
| Trades have already happened today | Login replaces the old rows with today's trade data, without waiting for another trade. |

## Effect on Copy Trade

CTCL login alone does not establish that the AUTOTRD file contains today's data. Copy Trade checks the dates inside an existing readable file before setting its startup row pointer.

If the file contains old dates at startup, Copy Trade keeps that exchange's pointer at `0` and waits for valid today's data. Once CTCL replaces the contents, the copier processes from the first data row through the existing filters, including `COPY_ALLOWED_DELAY_SECONDS`.

If CTCL has already restored today's data before Copy Trade starts, the copier preserves its normal startup behaviour: existing current-day rows become the baseline and only subsequent rows are considered for copying. It does not automatically replay the trades already present at startup.
