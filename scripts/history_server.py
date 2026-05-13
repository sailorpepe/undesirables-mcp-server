#!/usr/bin/env python3
"""
TCG Price History API — Direct SQLite Server
Replaces the Upstash KV middleman. Reads directly from market_memory.sqlite.
Runs on port 8787, exposed via Cloudflare tunnel.
"""
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="TCG Oracle History API", version="2.0")

# CORS — allow requests from anywhere (Tauri app, web, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Database path
WORK_DIR = Path(os.environ.get("CI_PROJECT_DIR", Path(__file__).parent.parent))
DB_PATH = WORK_DIR / ".cache" / "market_memory.sqlite"


@contextmanager
def get_db():
    """Thread-safe read-only connection."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@app.get("/api/v1/history")
async def history(
    product_id: int = Query(None, description="Lookup by product ID"),
    name: str = Query(None, description="Search by card name"),
    days: int = Query(365, description="Limit history to last N days"),
):
    """
    TCG Price History endpoint — drop-in replacement for the Vercel KV route.
    Same query params, same response format.
    """
    headers = {
        "Cache-Control": "public, max-age=3600",
    }

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # ── Direct product lookup ──────────────────
            if product_id:
                # Get stats
                cursor.execute(
                    "SELECT last_price, drift, volatility FROM shroomy_stats WHERE product_id = ?",
                    (product_id,),
                )
                stats_row = cursor.fetchone()

                # Get price history
                cursor.execute(
                    """
                    SELECT date, market_price, low_price, high_price
                    FROM price_history
                    WHERE product_id = ?
                      AND date >= date('now', ?)
                    ORDER BY date ASC
                    """,
                    (product_id, f"-{days} days"),
                )
                history_rows = cursor.fetchall()

                if not stats_row and not history_rows:
                    return JSONResponse(
                        {"error": "Product not found", "product_id": str(product_id)},
                        status_code=404,
                        headers=headers,
                    )

                stats = None
                if stats_row:
                    stats = {
                        "lastPrice": stats_row["last_price"],
                        "drift": stats_row["drift"],
                        "volatility": stats_row["volatility"],
                    }

                history = [
                    {
                        "date": r["date"],
                        "price": r["market_price"],
                        "low": r["low_price"],
                        "high": r["high_price"],
                    }
                    for r in history_rows
                ]

                return JSONResponse(
                    {
                        "product_id": product_id,
                        "stats": stats,
                        "history": history,
                    },
                    headers=headers,
                )

            # ── Name search ────────────────────────────
            if name:
                search_term = f"%{name.lower().strip()}%"

                # Search cards table for matches
                cursor.execute(
                    """
                    SELECT c.product_id, c.name, c.category_id,
                           s.last_price, s.drift, s.volatility
                    FROM cards c
                    LEFT JOIN shroomy_stats s ON c.product_id = s.product_id
                    WHERE LOWER(c.name) LIKE ? OR LOWER(c.clean_name) LIKE ?
                    ORDER BY COALESCE(s.last_price, 0) DESC
                    LIMIT 10
                    """,
                    (search_term, search_term),
                )
                matches = cursor.fetchall()

                if not matches:
                    return JSONResponse(
                        {"error": "No cards found", "query": name},
                        status_code=404,
                        headers=headers,
                    )

                results = []
                for m in matches:
                    # Fetch history for each match
                    cursor.execute(
                        """
                        SELECT date, market_price, low_price, high_price
                        FROM price_history
                        WHERE product_id = ?
                          AND date >= date('now', ?)
                        ORDER BY date ASC
                        """,
                        (m["product_id"], f"-{days} days"),
                    )
                    hist_rows = cursor.fetchall()

                    results.append({
                        "product_id": m["product_id"],
                        "name": m["name"],
                        "category_id": m["category_id"],
                        "last_price": m["last_price"] or 0,
                        "drift": m["drift"] or 0,
                        "volatility": m["volatility"] or 0,
                        "history": [
                            {
                                "date": r["date"],
                                "price": r["market_price"],
                                "low": r["low_price"],
                                "high": r["high_price"],
                            }
                            for r in hist_rows
                        ],
                    })

                return JSONResponse(
                    {"query": name, "results": results},
                    headers=headers,
                )

            # ── No params — return API status ──────────
            cursor.execute("SELECT COUNT(*) as cnt FROM shroomy_stats")
            stats_count = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(*) as cnt FROM price_history")
            history_count = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(DISTINCT product_id) as cnt FROM price_history")
            unique_products = cursor.fetchone()["cnt"]

            cursor.execute("SELECT MIN(date) as min_d, MAX(date) as max_d FROM price_history")
            date_range = cursor.fetchone()

            cursor.execute("SELECT COUNT(*) as cnt FROM cards")
            cards_count = cursor.fetchone()["cnt"]

            return JSONResponse(
                {
                    "endpoint": "/api/v1/history",
                    "status": "operational",
                    "version": "2.0-direct",
                    "usage": {
                        "by_product": "/api/v1/history?product_id=12345",
                        "by_name": "/api/v1/history?name=Charizard",
                    },
                    "data_source": "market_memory.sqlite (direct)",
                    "meta": {
                        "productCount": stats_count,
                        "cardsCount": cards_count,
                        "priceHistoryRows": history_count,
                        "uniqueProducts": unique_products,
                        "dateRange": {
                            "min": date_range["min_d"],
                            "max": date_range["max_d"],
                        },
                    },
                },
                headers=headers,
            )

    except Exception as e:
        return JSONResponse(
            {"error": "Internal server error", "detail": str(e)},
            status_code=500,
            headers=headers,
        )


if __name__ == "__main__":
    print(f"[TCG History API] Database: {DB_PATH}")
    print(f"[TCG History API] Database exists: {DB_PATH.exists()}")
    if DB_PATH.exists():
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM shroomy_stats")
            print(f"[TCG History API] Stats: {c.fetchone()[0]:,} products")
            c.execute("SELECT COUNT(*) FROM price_history")
            print(f"[TCG History API] History: {c.fetchone()[0]:,} rows")
    uvicorn.run(app, host="0.0.0.0", port=8787)
