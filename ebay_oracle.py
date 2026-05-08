"""
eBay Market Depth Oracle — Ported from Shroomy Simulator (ebay-service.ts)
Provides secondary market listings data for TCG cards via the eBay Browse API.
Synthesizes historical price paths from current listings for Monte Carlo simulations.
"""

import os
import json
import logging
import math
import random
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

logging.basicConfig(level=logging.INFO, format='[eBay Oracle] %(message)s')
logger = logging.getLogger(__name__)

# eBay OAuth2 Credentials (User provides via .env)
EBAY_APP_ID = os.environ.get("EBAY_APP_ID", "")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")
EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

# In-memory token cache
_cached_token = None
_token_expiry = 0


def get_ebay_access_token():
    """OAuth2 Client Credentials flow for eBay Browse API."""
    global _cached_token, _token_expiry
    
    import time
    if _cached_token and time.time() < _token_expiry:
        return _cached_token
    
    if not EBAY_APP_ID or not EBAY_CLIENT_SECRET:
        raise ValueError(
            "Missing eBay credentials. Please configure them in the Universal Live Market interface."
        )
    
    import base64
    credentials = base64.b64encode(f"{EBAY_APP_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    
    response = requests.post(
        EBAY_OAUTH_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {credentials}"
        },
        data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
        timeout=10
    )
    
    if response.status_code != 200:
        logger.error(f"eBay OAuth Failed: {response.text}")
        raise ConnectionError("Failed to authenticate with eBay")
    
    data = response.json()
    _cached_token = data["access_token"]
    _token_expiry = time.time() + data["expires_in"] - 60  # 60s buffer
    return _cached_token


def search_ebay_listings(query, limit=50):
    """
    Search eBay Browse API for current fixed-price listings.
    Returns structured listing data with prices.
    """
    if not requests:
        logger.error("requests library not available")
        return []
    
    try:
        token = get_ebay_access_token()
    except (ValueError, ConnectionError) as e:
        logger.warning(f"eBay auth skipped: {e}")
        return []
    
    all_items = []
    offset = 0
    PAGE_SIZE = 200
    
    while len(all_items) < limit:
        fetch_limit = min(PAGE_SIZE, limit - len(all_items))
        url = (
            f"{EBAY_BROWSE_URL}?q={requests.utils.quote(query)}"
            f"&limit={fetch_limit}&offset={offset}"
            f"&filter=buyingOptions:{{FIXED_PRICE}}"
        )
        
        # Enterprise endpoint: if the server running this supports sold comps, 
        # append the soldItemsOnly filter.
        if "soldItemsOnly" in os.environ.get("EBAY_FILTERS", ""):
             url += ",soldItemsOnly:true"
        
        try:
            response = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "X-EBAY-C-MARKETPLACE-ID": "EBAY-US"
                },
                timeout=15
            )
            
            if response.status_code != 200:
                logger.error(f"eBay Search Failed: {response.text[:200]}")
                break
            
            data = response.json()
            summaries = data.get("itemSummaries", [])
            
            if not summaries:
                break
            
            for item in summaries:
                all_items.append({
                    "itemId": item.get("itemId"),
                    "title": item.get("title"),
                    "price": float(item.get("price", {}).get("value", 0)),
                    "currency": item.get("price", {}).get("currency", "USD"),
                    "imageUrl": item.get("image", {}).get("imageUrl"),
                    "itemWebUrl": item.get("itemWebUrl"),
                })
            
            offset += len(summaries)
            
            if len(summaries) < fetch_limit or offset >= 1000:
                break
                
        except Exception as e:
            logger.error(f"eBay Fetch Error: {e}")
            break
    
    return all_items


def synthesize_history_from_listings(listings):
    """
    Converts current eBay listings into a synthetic 90-day price history.
    Uses market spread (variance of listing prices) as a volatility proxy.
    Ported from Shroomy's synthesizeHistoryFromListings().
    """
    if not listings:
        return {"prices": [], "volatility": 0.05}
    
    prices = [item["price"] for item in listings if isinstance(item.get("price"), (int, float)) and item["price"] > 0]
    
    if not prices:
        return {"prices": [], "volatility": 0.05}
    
    avg = sum(prices) / len(prices)
    variance = sum((p - avg) ** 2 for p in prices) / len(prices)
    std_dev = math.sqrt(variance)
    
    # Volatility proxy: StdDev/Avg * Scaling Factor, clamped 5%-30%
    volatility = max(0.05, min(0.30, (std_dev / avg) * 0.5))
    
    # Generate 90-day synthetic history anchored at avg price
    hist = []
    p = avg
    for i in range(90):
        hist.insert(0, p)
        change = (random.random() - 0.5) * (p * volatility * 0.2)
        p += change
    
    return {
        "prices": hist,
        "volatility": round(volatility, 4),
        "avg_listing_price": round(avg, 2),
        "num_listings": len(prices),
        "price_range": {
            "low": round(min(prices), 2),
            "high": round(max(prices), 2),
            "spread": round(max(prices) - min(prices), 2)
        }
    }


def get_market_depth(card_name, limit=50, app_id=None, client_secret=None):
    """
    Full pipeline: Search eBay → compute market depth → synthesize history.
    Returns everything needed for the Monte Carlo simulation engine.
    """
    global EBAY_APP_ID, EBAY_CLIENT_SECRET
    if app_id:
        EBAY_APP_ID = app_id
    if client_secret:
        EBAY_CLIENT_SECRET = client_secret

    logger.info(f"Querying eBay market depth for: '{card_name}'")
    
    listings = search_ebay_listings(f"{card_name}", limit=limit) # Query directly instead of appending 'TCG card' so folks can search Rolex
    
    if not listings:
        logger.warning(f"No eBay listings found for '{card_name}'")
        return None
    
    synthesis = synthesize_history_from_listings(listings)
    
    return {
        "card_query": card_name,
        "timestamp": datetime.now().isoformat(),
        "listings_found": len(listings),
        "market_depth": synthesis,
        "sample_listings": listings[:150]  # Allow scrolling through a deep list
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("""
╔══════════════════════════════════════════════════════╗
║  eBay Market Depth Oracle                            ║
╠══════════════════════════════════════════════════════╣
║  Usage:                                              ║
║    python ebay_oracle.py "Charizard Base Set"         ║
║                                                      ║
║  Env Vars Required:                                  ║
║    EBAY_APP_ID         (eBay Developer App ID)       ║
║    EBAY_CLIENT_SECRET  (eBay Developer Secret)       ║
║                                                      ║
║  Get keys: https://developer.ebay.com/my/keys        ║
╚══════════════════════════════════════════════════════╝
        """)
        sys.exit(0)
    
    query = " ".join(sys.argv[1:])
    result = get_market_depth(query)
    
    if result:
        print(json.dumps(result, indent=2))
    else:
        print("No market depth data available. Check your eBay API credentials.")
