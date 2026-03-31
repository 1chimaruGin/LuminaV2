#!/usr/bin/env python3
"""
Enrich Four.meme / BSC token candidates with binary gates:
  - GoPlus token_security (BSC)
  - Logo heuristics: Trust Wallet CDN, CoinGecko BSC list cache, optional Moralis via lumina-backend
  - KOL convergence: distinct wallets from top.json that bought token in ClickHouse kol_swaps
    (optional time window from launch block -> timestamp via BSC JSON-RPC)

stdin: one JSON object per line (e.g. lumina_hotpath or lumina_replay_fourmeme), or bare 0x addresses.
Also supports --tokens-csv for backtest-style exports.

Environment:
  CLICKHOUSE_BIN, KOL_MIN_WALLETS, KOL_WINDOW_SEC,
  LUMINA_BACKEND_URL, LUMINA_API_PREFIX, QUICK_NODE_BSC_RPC / BSC_RPC for block timestamps.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
TOKEN_FIELD_RE = re.compile(r'"token"\s*:\s*"(0x[a-fA-F0-9]{40})"')


def _load_env_files() -> None:
    for env_path in (PROJECT_ROOT / ".env", PROJECT_ROOT.parent / "lumina-backend" / ".env"):
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_env_files()

CG_BSC_LIST = "https://tokens.coingecko.com/binance-smart-chain/all.json"
TW_LOGO_TMPL = (
    "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/smartchain/assets/{}/logo.png"
)
GOPLUS_TMPL = "https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses={}"


def load_valid_kol_wallets(top_path: Path) -> list[str]:
    if not top_path.exists():
        return []
    data = json.loads(top_path.read_text())
    out: list[str] = []
    for row in data:
        addr = (row.get("address") or "").strip().lower()
        if ADDR_RE.match(addr):
            out.append(addr)
    return list(dict.fromkeys(out))


def ch_query(clickhouse_bin: str, query: str) -> list[dict]:
    cmd = [clickhouse_bin, "client", "--query", f"{query} FORMAT JSONEachRow"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if result.returncode != 0:
        sys.stderr.write(f"ClickHouse error: {result.stderr[:400]}\n")
        return []
    rows = []
    for line in result.stdout.strip().split("\n"):
        if line:
            rows.append(json.loads(line))
    return rows


def http_json(url: str, headers: dict | None = None, timeout: float = 20.0) -> dict | list | None:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "lumina-enrich-candidates/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        sys.stderr.write(f"HTTP {url[:60]}... : {e}\n")
        return None


def http_head_ok(url: str, timeout: float = 8.0) -> bool:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "lumina-enrich-candidates/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as _:
            return True
    except OSError:
        # Some servers reject HEAD; try small GET
        try:
            req2 = urllib.request.Request(
                url, headers={"User-Agent": "lumina-enrich-candidates/1.0", "Range": "bytes=0-0"}
            )
            with urllib.request.urlopen(req2, timeout=timeout) as r:
                return r.status in (200, 206)
        except OSError:
            return False


def load_coingecko_bsc_addresses(cache_path: Path, max_age_sec: int = 86400) -> set[str]:
    now = time.time()
    if cache_path.exists() and now - cache_path.stat().st_mtime < max_age_sec:
        data = json.loads(cache_path.read_text())
    else:
        raw = http_json(CG_BSC_LIST)
        if not isinstance(raw, list):
            return set()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(raw))
        data = raw
    return {str(t.get("address", "")).lower() for t in data if t.get("address")}


def goplus_token(addr: str) -> dict:
    url = GOPLUS_TMPL.format(addr.lower())
    hdr = {"User-Agent": "lumina-enrich-candidates/1.0", "Accept": "application/json"}
    data = http_json(url, hdr)
    if not isinstance(data, dict) or data.get("code") != 1:
        return {}
    result = data.get("result") or {}
    info = result.get(addr.lower()) or next(iter(result.values()), {}) if result else {}
    if not isinstance(info, dict):
        return {}
    return info


def goplus_honeypot_flag(info: dict) -> bool | None:
    v = info.get("is_honeypot")
    if v in ("1", 1, True):
        return True
    if v in ("0", 0, False):
        return False
    return None


def block_timestamp(rpc_url: str, block_num: int) -> int | None:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "eth_getBlockByNumber",
            "params": [hex(int(block_num)), False],
            "id": 1,
        }
    ).encode()
    req = urllib.request.Request(
        rpc_url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "lumina-enrich-candidates/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read().decode())
        ts = (res.get("result") or {}).get("timestamp")
        if isinstance(ts, str) and ts.startswith("0x"):
            return int(ts, 16)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


def kol_buy_counts(
    clickhouse_bin: str,
    token: str,
    kol_wallets: list[str],
    window: tuple[int, int] | None,
) -> tuple[int, int]:
    """Returns (buyers_in_window_or_0, buyers_ever)."""
    if not kol_wallets:
        return 0, 0
    in_list = ",".join(f"'{w}'" for w in kol_wallets)
    tok = token.lower().replace("'", "")
    base_where = (
        f"lower(token_address) = '{tok}' AND side = 'buy' AND wallet_address IN ({in_list})"
    )
    q_ever = f"SELECT uniqExact(wallet_address) AS n FROM lumina.kol_swaps WHERE {base_where}"
    rows_e = ch_query(clickhouse_bin, q_ever)
    ever = int(rows_e[0]["n"]) if rows_e else 0
    if window is None:
        return 0, ever
    t0, t1 = window
    q_win = (
        f"SELECT uniqExact(wallet_address) AS n FROM lumina.kol_swaps WHERE {base_where} "
        f"AND block_timestamp >= {t0} AND block_timestamp <= {t1}"
    )
    rows_w = ch_query(clickhouse_bin, q_win)
    win = int(rows_w[0]["n"]) if rows_w else 0
    return win, ever


def parse_input_line(line: str) -> dict | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("{"):
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            return None
        tok = (o.get("token") or o.get("token_address") or "").strip().lower()
        if not tok and "address" in o:
            tok = str(o["address"]).strip().lower()
        if not ADDR_RE.match(tok):
            return None
        block = o.get("launch_block")
        if block is None:
            block = o.get("block")
        return {"raw": o, "token": tok, "block": int(block) if block is not None else None}
    if ADDR_RE.match(line):
        return {"raw": {}, "token": line.lower(), "block": None}
    # tokens_*.txt: "SYMBOL, 0x..., 1.2x"
    parts = [p.strip() for p in line.split(",")]
    for p in parts:
        if ADDR_RE.match(p):
            return {"raw": {}, "token": p.lower(), "block": None}
    return None


def try_backend_check(base_url: str, api_prefix: str, token: str) -> dict | None:
    _d = str(Path(__file__).resolve().parent)
    if _d not in sys.path:
        sys.path.insert(0, _d)
    from lumina_backend_client import fetch_bsc_candidate_check

    return fetch_bsc_candidate_check(base_url, api_prefix, token)


def main() -> None:
    ap = argparse.ArgumentParser(description="Enrich token candidates with gates (stdin JSONL or addresses)")
    ap.add_argument("--top-json", type=Path, default=PROJECT_ROOT / "top.json", help="KOL wallet list")
    ap.add_argument("--kol-min", type=int, default=int(os.environ.get("KOL_MIN_WALLETS", "2")))
    ap.add_argument(
        "--kol-window-sec",
        type=int,
        default=int(os.environ.get("KOL_WINDOW_SEC", "1800")),
        help="Seconds after launch block timestamp to count KOL buys (0 = disable window, use ever-only)",
    )
    ap.add_argument("--require-logo", action="store_true", help="Fail gate if no logo heuristic matches")
    ap.add_argument("--skip-clickhouse", action="store_true")
    ap.add_argument(
        "--kol-gate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require KOL convergence when ClickHouse is available (default: on)",
    )
    ap.add_argument("--bsc-rpc", default=os.environ.get("QUICK_NODE_BSC_RPC") or os.environ.get("BSC_RPC", ""))
    ap.add_argument("--tokens-csv", type=Path, help="File with comma-separated rows (like tokens_*.txt)")
    ap.add_argument(
        "--backend-url",
        default=os.environ.get("LUMINA_BACKEND_URL", "").rstrip("/"),
        help="If set, call /token/bsc-candidate-check for logo + GoPlus merge",
    )
    args = ap.parse_args()

    clickhouse_bin = os.environ.get("CLICKHOUSE_BIN", str(PROJECT_ROOT / "clickhouse-bin"))
    api_prefix = os.environ.get("LUMINA_API_PREFIX", "/api/v1")

    kol_wallets = load_valid_kol_wallets(args.top_json)
    cg_cache = PROJECT_ROOT / ".cache" / "coingecko_bsc_tokens.json"
    cg_set: set[str] = set()
    try:
        cg_set = load_coingecko_bsc_addresses(cg_cache)
    except OSError:
        pass

    def process_record(rec: dict) -> None:
        token = rec["token"]
        block = rec.get("block")
        raw = rec.get("raw") or {}

        reasons: list[str] = []
        backend_blob: dict | None = None
        if args.backend_url:
            backend_blob = try_backend_check(args.backend_url, api_prefix, token)

        if backend_blob and not backend_blob.get("error"):
            logo_ok = bool(backend_blob.get("logo_ok"))
            hp = backend_blob.get("is_honeypot")
            goplus_hp = True if hp is True else False if hp is False else None
            in_cg = bool(backend_blob.get("in_coingecko_list"))
            tw_ok = bool(backend_blob.get("trust_wallet_logo_ok"))
        else:
            info = goplus_token(token)
            goplus_hp = goplus_honeypot_flag(info)
            tw_ok = http_head_ok(TW_LOGO_TMPL.format(token.lower()))
            in_cg = token.lower() in cg_set
            logo_ok = tw_ok or in_cg
            backend_blob = None

        if goplus_hp is True:
            reasons.append("goplus_honeypot")
        if args.require_logo and not logo_ok:
            reasons.append("no_logo")

        launch_ts: int | None = None
        if block is not None and args.bsc_rpc:
            launch_ts = block_timestamp(args.bsc_rpc, block)

        window: tuple[int, int] | None = None
        if (
            launch_ts is not None
            and args.kol_window_sec > 0
            and not args.skip_clickhouse
            and kol_wallets
        ):
            window = (launch_ts, launch_ts + args.kol_window_sec)

        kol_win, kol_ever = (0, 0)
        kol_gate_skipped = True
        if args.kol_gate and not args.skip_clickhouse and kol_wallets and Path(clickhouse_bin).exists():
            kol_gate_skipped = False
            try:
                kol_win, kol_ever = kol_buy_counts(clickhouse_bin, token, kol_wallets, window)
            except (FileNotFoundError, subprocess.SubprocessError) as e:
                kol_gate_skipped = True
                sys.stderr.write(f"enrich_candidates: ClickHouse skip for {token}: {e}\n")
        elif args.kol_gate and not args.skip_clickhouse and kol_wallets:
            kol_gate_skipped = True
            sys.stderr.write(
                f"enrich_candidates: CLICKHOUSE_BIN not found ({clickhouse_bin}); KOL gate skipped\n"
            )

        kol_metric = kol_win if window else kol_ever
        if not kol_gate_skipped and kol_metric < args.kol_min:
            reasons.append(f"kol_convergence_lt_{args.kol_min}")

        gates_pass = not reasons

        out = {
            **raw,
            "enrich": {
                "token": token,
                "logo_ok": logo_ok,
                "trust_wallet_logo": tw_ok if backend_blob is None else backend_blob.get("trust_wallet_logo_ok"),
                "in_coingecko_list": in_cg if backend_blob is None else backend_blob.get("in_coingecko_list"),
                "goplus_honeypot": goplus_hp,
                "kol_wallets_tracked": len(kol_wallets),
                "kol_distinct_buyers_window": kol_win,
                "kol_distinct_buyers_ever": kol_ever,
                "kol_gate_metric": kol_metric,
                "kol_min_required": args.kol_min,
                "kol_gate_skipped": kol_gate_skipped,
                "launch_block": block,
                "launch_ts": launch_ts,
                "kol_window_sec": args.kol_window_sec if window else None,
                "gate_reasons": reasons,
                "gates_pass": gates_pass,
            },
        }
        if backend_blob:
            out["enrich"]["backend"] = {
                k: backend_blob.get(k)
                for k in ("logo_url", "symbol", "name", "goplus_risk_score")
                if backend_blob.get(k) is not None
            }
        print(json.dumps(out, separators=(",", ":")))

    lines_iter: list[str] = []
    if args.tokens_csv:
        lines_iter = args.tokens_csv.read_text().splitlines()
    else:
        lines_iter = sys.stdin.read().splitlines()

    for line in lines_iter:
        rec = parse_input_line(line)
        if rec:
            process_record(rec)


if __name__ == "__main__":
    main()
