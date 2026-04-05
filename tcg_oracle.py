import os
import sqlite3
import requests
import json
import csv
import logging
from datetime import datetime
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='[TCG Oracle] %(message)s')
logger = logging.getLogger(__name__)

# Constants
CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)
DB_PATH = CACHE_DIR / "market_memory.sqlite"

# TCGPlayer Category Codes (per TCGCSV docs)
CATEGORIES = {
    "magic": 1,
    "pokemon": 3,
    "yugioh": 2
}

def init_db():
    """Build the rolling historical Memory Bank for AI Souls."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Stores the raw card metadata
    c.execute('''CREATE TABLE IF NOT EXISTS cards
                 (product_id INTEGER PRIMARY KEY, category_id INTEGER, group_id INTEGER, 
                  name TEXT, clean_name TEXT, rarity TEXT)''')
                  
    # The Time-Series pricing ledger (The 'Memory')
    c.execute('''CREATE TABLE IF NOT EXISTS price_history
                 (product_id INTEGER, 
                  date TEXT, 
                  low_price REAL, 
                  mid_price REAL, 
                  high_price REAL, 
                  market_price REAL,
                  PRIMARY KEY(product_id, date))''')
    conn.commit()
    return conn

def fetch_active_groups(category_id=3):
    """Hits TCGCSV to get all active sets/groups for a game."""
    url = f"https://tcgcsv.com/tcgplayer/{category_id}/groups"
    logger.info(f"Fetching groups for Category: {category_id}")
    
    try:
        req = requests.get(url, timeout=10)
        req.raise_for_status()
        data = req.json()
        return data.get('results', [])
    except Exception as e:
        logger.error(f"Failed to fetch groups: {e}")
        return []

def snapshot_daily_prices(category_name="pokemon", max_groups=5):
    """
    Downloads the top groups for a given category and records the snapshot 
    in the rolling Monte Carlo SQLite Database.
    We limit to max_groups to respect the 9,000 req/day limit and save bandwidth.
    """
    conn = init_db()
    c = conn.cursor()
    cat_id = CATEGORIES.get(category_name.lower(), 3)
    
    groups = fetch_active_groups(cat_id)
    if not groups:
        return
        
    # Sort groups by ID descending (usually the newest/most actively traded sets)
    groups = sorted(groups, key=lambda x: x.get('groupId', 0), reverse=True)[:max_groups]
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    for group in groups:
        g_id = group['groupId']
        g_name = group.get('name', 'Unknown Set')
        logger.info(f"Processing Set: {g_name} ({g_id})")
        
        # 1. Fetch Products
        try:
            p_req = requests.get(f"https://tcgcsv.com/tcgplayer/{cat_id}/{g_id}/products", timeout=10)
            if p_req.status_code == 200:
                products = p_req.json().get('results', [])
                for p in products:
                    c.execute("INSERT OR IGNORE INTO cards (product_id, category_id, group_id, name, clean_name, rarity) VALUES (?, ?, ?, ?, ?, ?)",
                              (p['productId'], cat_id, g_id, p['name'], p['cleanName'], p.get('rarityName', '')))
            
            # 2. Fetch Prices
            pr_req = requests.get(f"https://tcgcsv.com/tcgplayer/{cat_id}/{g_id}/prices", timeout=10)
            if pr_req.status_code == 200:
                prices = pr_req.json().get('results', [])
                for pr in prices:
                    c.execute('''INSERT OR REPLACE INTO price_history 
                                 (product_id, date, low_price, mid_price, high_price, market_price) 
                                 VALUES (?, ?, ?, ?, ?, ?)''',
                              (pr['productId'], today_str, pr.get('lowPrice'), pr.get('midPrice'), pr.get('highPrice'), pr.get('marketPrice')))
        except Exception as e:
            logger.error(f"Failed processing group {g_id}: {e}")
            
    conn.commit()
    conn.close()
    logger.info("Daily Snapshot Complete! Engine memory updated.")

def get_historical_volatility(card_name_query):
    """
    Returns empirical Merton volatility (sigma) and average drift (mu)
    by computing the variance of the card's historical market paths.
    """
    conn = init_db()
    c = conn.cursor()
    
    # 1. Resolve product ID via LIKE query
    c.execute("SELECT product_id, name FROM cards WHERE clean_name LIKE ? OR name LIKE ? LIMIT 1", 
              (f"%{card_name_query}%", f"%{card_name_query}%"))
    row = c.fetchone()
    if not row:
         return None
         
    pid, exact_name = row
    
    # 2. Retrieve chronological history
    c.execute("SELECT date, market_price FROM price_history WHERE product_id = ? ORDER BY date ASC", (pid,))
    history = c.fetchall()
    
    if len(history) < 2:
        return {"name": exact_name, "points": len(history), "error": "Insufficient depth for Monte Carlo"}
        
    prices = [h[1] for h in history if h[1] is not None and h[1] > 0]
    if len(prices) < 2:
         return {"name": exact_name, "points": 0, "error": "No valid prices"}
         
    # Calculate geometric returns (R_i = ln(S_i / S_i-1))
    import math
    import statistics
    
    returns = []
    for i in range(1, len(prices)):
        returns.append(math.log(prices[i] / prices[i-1]))
        
    mean_return = statistics.mean(returns) if len(returns) > 0 else 0
    # Sample standard dev of daily returns
    volatility = statistics.stdev(returns) if len(returns) > 1 else 0
    
    # Annualize (approx 365 trading days for crypto/cards)
    mu = mean_return * 365
    sigma = volatility * math.sqrt(365)
    
    return {
        "name": exact_name,
        "product_id": pid,
        "data_points": len(prices),
        "mu_annual": round(mu, 4),
        "sigma_annual": round(sigma, 4),
        "last_price": prices[-1],
        "jump_diffusion_factor": round(volatility * 2.5, 4) # Empirical jump intensity parameter lambda
    }

def import_shroomy_dataset(json_path):
    """
    Bulk-imports the Shroomy Simulator's pre-computed tcg_stats.json
    (813K+ products with empirical drift, volatility, lastPrice).
    This gives users instant market depth on first launch.
    """
    conn = init_db()
    c = conn.cursor()
    
    # Create the pre-computed stats table
    c.execute('''CREATE TABLE IF NOT EXISTS shroomy_stats
                 (product_id INTEGER PRIMARY KEY, 
                  drift REAL, 
                  volatility REAL, 
                  last_price REAL)''')
    
    logger.info(f"Loading Shroomy dataset from {json_path}...")
    
    with open(json_path, 'r') as fh:
        data = json.load(fh)
    
    count = 0
    batch = []
    for pid_str, stats in data.items():
        try:
            pid = int(pid_str)
            drift = float(stats.get('drift', 0)) if stats.get('drift') is not None else 0
            vol = float(stats.get('volatility', 0)) if stats.get('volatility') is not None else 0
            last = float(stats.get('lastPrice', 0)) if stats.get('lastPrice') is not None else 0
            batch.append((pid, drift, vol, last))
            count += 1
            
            if len(batch) >= 5000:
                c.executemany("INSERT OR REPLACE INTO shroomy_stats (product_id, drift, volatility, last_price) VALUES (?, ?, ?, ?)", batch)
                batch = []
                if count % 50000 == 0:
                    logger.info(f"  Imported {count:,} products...")
        except (ValueError, TypeError):
            continue
    
    if batch:
        c.executemany("INSERT OR REPLACE INTO shroomy_stats (product_id, drift, volatility, last_price) VALUES (?, ?, ?, ?)", batch)
    
    conn.commit()
    conn.close()
    logger.info(f"✅ Shroomy import complete! {count:,} products loaded into market_memory.sqlite")

def get_shroomy_stats(card_name_query):
    """
    Queries the Shroomy pre-computed stats by joining with the cards table.
    Returns empirical drift/volatility/lastPrice from the massive historical dataset.
    """
    conn = init_db()
    c = conn.cursor()
    
    # Join shroomy_stats with cards table for name-based lookups
    c.execute("""SELECT c.name, s.drift, s.volatility, s.last_price, s.product_id
                 FROM shroomy_stats s 
                 JOIN cards c ON c.product_id = s.product_id
                 WHERE c.clean_name LIKE ? OR c.name LIKE ?
                 ORDER BY s.last_price DESC
                 LIMIT 5""",
              (f"%{card_name_query}%", f"%{card_name_query}%"))
    
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return None
    
    results = []
    for name, drift, vol, price, pid in rows:
        results.append({
            "name": name,
            "product_id": pid,
            "mu_annual": round(drift * 365, 4) if drift else 0,
            "sigma_annual": round(vol * (365 ** 0.5), 4) if vol else 0,
            "last_price": price,
            "source": "shroomy_simulator"
        })
    
    return results

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("""
╔══════════════════════════════════════════════════════════╗
║  TCG Market Oracle — Stochastic Intelligence Engine     ║
╠══════════════════════════════════════════════════════════╣
║  Commands:                                               ║
║    --snapshot         Daily TCGCSV cron job               ║
║    --import-shroomy   Load Shroomy Simulator 24MB dataset ║
║    --query <name>     Lookup card market physics           ║
╚══════════════════════════════════════════════════════════╝
        """)
        sys.exit(0)
    
    cmd = sys.argv[1]
    
    if cmd == "--snapshot":
        logger.info("Triggering Cron Job Daily Snapshot...")
        snapshot_daily_prices(category_name="pokemon", max_groups=5)
    
    elif cmd == "--import-shroomy":
        shroomy_path = "/Users/davidluna/shroomy/shroomy_simulator/data/tcg_stats.json"
        if len(sys.argv) > 2:
            shroomy_path = sys.argv[2]
        import_shroomy_dataset(shroomy_path)
    
    elif cmd == "--query":
        if len(sys.argv) < 3:
            print("Usage: python tcg_oracle.py --query 'Charizard'")
            sys.exit(1)
        query = " ".join(sys.argv[2:])
        
        # Try Shroomy stats first, then fall back to historical volatility
        result = get_shroomy_stats(query)
        if result:
            logger.info(f"Shroomy Stats for '{query}':")
            for r in result:
                print(json.dumps(r, indent=2))
        else:
            result = get_historical_volatility(query)
            if result:
                logger.info(f"Historical Volatility for '{query}':")
                print(json.dumps(result, indent=2))
            else:
                logger.warning(f"No data found for '{query}'. Run --snapshot or --import-shroomy first.")

