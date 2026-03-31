#!/usr/bin/env python3
"""
Simple test script to verify the ML pipeline components work.
"""
import os
import sys
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web3 import Web3

# ============================================================
# Test 1: ClickHouse Connection
# ============================================================
def test_clickhouse():
    print("=" * 60)
    print("TEST 1: ClickHouse Connection")
    print("=" * 60)
    
    try:
        from clickhouse_driver import Client
        
        client = Client(
            host=os.getenv("CLICKHOUSE_HOST", "localhost"),
            port=int(os.getenv("CLICKHOUSE_PORT", "9000")),
            database=os.getenv("CLICKHOUSE_DB", "lumina"),
            user=os.getenv("CLICKHOUSE_USER", "default"),
            password=os.getenv("CLICKHOUSE_PASSWORD", "")
        )
        
        result = client.execute("SELECT 1")
        print(f"  ✓ Connected to ClickHouse")
        
        # Check tables
        tables = client.execute("SHOW TABLES")
        print(f"  ✓ Tables: {[t[0] for t in tables]}")
        
        # Check token_migrations count
        count = client.execute("SELECT count() FROM token_migrations")[0][0]
        print(f"  ✓ token_migrations rows: {count}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ ClickHouse error: {e}")
        return False


# ============================================================
# Test 2: QuickNode RPC Connection
# ============================================================
def test_quicknode():
    print()
    print("=" * 60)
    print("TEST 2: QuickNode RPC Connection")
    print("=" * 60)
    
    rpc_url = os.getenv("QUICK_NODE_BSC_RPC") or os.getenv("QUICKNODE_RPC_URL")
    
    if not rpc_url:
        print("  ✗ QUICK_NODE_BSC_RPC not set")
        return False
        
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        
        if not w3.is_connected():
            print("  ✗ Web3 not connected")
            return False
            
        block = w3.eth.block_number
        print(f"  ✓ Connected to BSC")
        print(f"  ✓ Current block: {block:,}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Web3 error: {e}")
        return False


# ============================================================
# Test 3: Feature Engineering
# ============================================================
def test_features():
    print()
    print("=" * 60)
    print("TEST 3: Feature Engineering")
    print("=" * 60)
    
    try:
        from ml.features import build_feature_vector, FEATURE_COLS, validate_features
        
        sample_row = {
            "initial_liq_bnb": 10.5,
            "initial_liq_usd": 6300.0,
            "initial_price_usd": 0.0001,
            "is_honeypot": 0,
            "buy_tax": 5.0,
            "sell_tax": 8.0,
            "holder_count": 150,
            "deployer_total_tokens": 3,
            "deployer_rug_count": 0,
            "lp_locked": 1,
            "lp_lock_pct": 100.0,
            "lp_lock_days": 180,
        }
        
        features = build_feature_vector(sample_row)
        
        print(f"  ✓ Feature vector built")
        print(f"  ✓ Total features: {len(features)}")
        print(f"  ✓ security_risk_score: {features.get('security_risk_score', 'N/A')}")
        print(f"  ✓ lp_lock_score: {features.get('lp_lock_score', 'N/A')}")
        
        warnings = validate_features(features)
        if warnings:
            print(f"  ! Warnings: {warnings}")
        else:
            print(f"  ✓ No validation warnings")
            
        return True
        
    except Exception as e:
        print(f"  ✗ Feature error: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# Test 4: GoPlus API
# ============================================================
async def test_goplus():
    print()
    print("=" * 60)
    print("TEST 4: GoPlus API")
    print("=" * 60)
    
    import aiohttp
    
    # Test with WBNB
    token = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses={token}"
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = data.get("result", {}).get(token.lower(), {})
                    print(f"  ✓ GoPlus API working")
                    print(f"  ✓ Token name: {result.get('token_name', 'N/A')}")
                    print(f"  ✓ Is honeypot: {result.get('is_honeypot', 'N/A')}")
                    return True
                else:
                    print(f"  ✗ GoPlus returned {resp.status}")
                    return False
                    
    except Exception as e:
        print(f"  ✗ GoPlus error: {e}")
        return False


# ============================================================
# Test 5: Insert Test Record
# ============================================================
def test_insert():
    print()
    print("=" * 60)
    print("TEST 5: Insert Test Record")
    print("=" * 60)
    
    try:
        from clickhouse_driver import Client
        
        client = Client(
            host=os.getenv("CLICKHOUSE_HOST", "localhost"),
            port=int(os.getenv("CLICKHOUSE_PORT", "9000")),
            database=os.getenv("CLICKHOUSE_DB", "lumina"),
            user=os.getenv("CLICKHOUSE_USER", "default"),
            password=os.getenv("CLICKHOUSE_PASSWORD", "")
        )
        
        # Insert test record
        client.execute(
            """
            INSERT INTO token_migrations (
                token_address, pair_address, deployer_address,
                block_number, block_timestamp,
                token_name, token_symbol,
                initial_liq_bnb, initial_liq_usd, initial_price_usd,
                is_honeypot, buy_tax, sell_tax,
                data_source
            ) VALUES
            """,
            [(
                "0xtest123", "0xpair123", "0xdeployer123",
                12345678, datetime.now(timezone.utc),
                "TestToken", "TEST",
                10.0, 6000.0, 0.0001,
                0, 5.0, 8.0,
                "test"
            )]
        )
        
        print(f"  ✓ Test record inserted")
        
        # Verify
        count = client.execute("SELECT count() FROM token_migrations WHERE data_source = 'test'")[0][0]
        print(f"  ✓ Test records in DB: {count}")
        
        # Clean up
        client.execute("ALTER TABLE token_migrations DELETE WHERE data_source = 'test'")
        print(f"  ✓ Test record cleaned up")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Insert error: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# Main
# ============================================================
async def main():
    print()
    print("╔════════════════════════════════════════════════════════════╗")
    print("║         LUMINA BSC PIPELINE TEST                           ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print()
    
    results = {}
    
    results["clickhouse"] = test_clickhouse()
    results["quicknode"] = test_quicknode()
    results["features"] = test_features()
    results["goplus"] = await test_goplus()
    results["insert"] = test_insert()
    
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {name:15} {status}")
        if not passed:
            all_passed = False
            
    print()
    if all_passed:
        print("All tests passed! Pipeline is ready.")
        print()
        print("Next steps:")
        print("  1. Run backfill: python ml/backfill.py --days 7")
        print("  2. Run label worker: python services/label_worker.py --once")
        print("  3. Start collector: python services/collector.py")
    else:
        print("Some tests failed. Please fix the issues above.")
        
    return all_passed


if __name__ == "__main__":
    asyncio.run(main())
