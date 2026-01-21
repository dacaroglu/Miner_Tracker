"""
Mining Dashboard - Extended Version with Historical Data
Stores share/difficulty history in SQLite for tracking over time
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager
from typing import Optional
import json


DB_PATH = Path("mining_data.db")


def init_db():
    """Initialize the SQLite database"""
    with get_db() as conn:
        conn.executescript("""
            -- Tracked wallets
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                address TEXT NOT NULL,
                pool_adapter TEXT NOT NULL,
                coin TEXT NOT NULL,
                enabled BOOLEAN DEFAULT TRUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(address, pool_adapter)
            );

            -- Pool snapshots (periodic stats capture)
            CREATE TABLE IF NOT EXISTS pool_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                wallet_id INTEGER,
                pool_name TEXT NOT NULL,
                coin TEXT NOT NULL,
                hashrate REAL,
                hashrate_avg REAL,
                workers_online INTEGER,
                workers_offline INTEGER,
                balance REAL,
                best_share REAL,
                best_ever REAL,
                network_difficulty REAL,
                raw_json TEXT,
                FOREIGN KEY (wallet_id) REFERENCES wallets (id)
            );

            -- Worker snapshots
            CREATE TABLE IF NOT EXISTS worker_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                wallet_id INTEGER,
                pool_name TEXT NOT NULL,
                worker_name TEXT NOT NULL,
                hashrate REAL,
                hashrate_avg REAL,
                best_share REAL,
                shares_count INTEGER,
                offline BOOLEAN,
                FOREIGN KEY (wallet_id) REFERENCES wallets (id)
            );

            -- Best shares log (track when new best shares are found)
            CREATE TABLE IF NOT EXISTS best_shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                wallet_id INTEGER,
                pool_name TEXT NOT NULL,
                worker_name TEXT,
                difficulty REAL NOT NULL,
                is_best_ever BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (wallet_id) REFERENCES wallets (id)
            );

            -- Share submissions log (for detailed share tracking)
            CREATE TABLE IF NOT EXISTS share_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                wallet_id INTEGER,
                miner_id INTEGER,
                pool_name TEXT NOT NULL,
                worker_name TEXT,
                difficulty REAL NOT NULL,
                accepted BOOLEAN DEFAULT TRUE,
                FOREIGN KEY (wallet_id) REFERENCES wallets (id),
                FOREIGN KEY (miner_id) REFERENCES miners (id)
            );

            -- Miner devices (physical mining hardware)
            CREATE TABLE IF NOT EXISTS miners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                miner_type TEXT NOT NULL,
                ip_address TEXT,
                mac_address TEXT,
                api_port INTEGER,
                api_url TEXT,
                status TEXT DEFAULT 'unknown',
                enabled BOOLEAN DEFAULT TRUE,
                auto_discovered BOOLEAN DEFAULT FALSE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen DATETIME,
                UNIQUE(ip_address)
            );

            -- Miner configuration (which wallet/pool a miner is pointing to)
            CREATE TABLE IF NOT EXISTS miner_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                miner_id INTEGER NOT NULL,
                wallet_id INTEGER,
                pool_url TEXT,
                worker_name TEXT,
                active BOOLEAN DEFAULT TRUE,
                detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (miner_id) REFERENCES miners (id) ON DELETE CASCADE,
                FOREIGN KEY (wallet_id) REFERENCES wallets (id) ON DELETE SET NULL
            );

            -- Create indexes
            CREATE INDEX IF NOT EXISTS idx_wallets_enabled
                ON wallets(enabled);
            CREATE INDEX IF NOT EXISTS idx_pool_snapshots_time
                ON pool_snapshots(timestamp, pool_name);
            CREATE INDEX IF NOT EXISTS idx_pool_snapshots_wallet
                ON pool_snapshots(wallet_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_worker_snapshots_time
                ON worker_snapshots(timestamp, pool_name, worker_name);
            CREATE INDEX IF NOT EXISTS idx_worker_snapshots_wallet
                ON worker_snapshots(wallet_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_best_shares_time
                ON best_shares(timestamp, pool_name);
            CREATE INDEX IF NOT EXISTS idx_best_shares_wallet
                ON best_shares(wallet_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_share_submissions_wallet
                ON share_submissions(wallet_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_share_submissions_time
                ON share_submissions(timestamp);
            CREATE INDEX IF NOT EXISTS idx_miners_ip
                ON miners(ip_address);
            CREATE INDEX IF NOT EXISTS idx_miners_enabled
                ON miners(enabled);
            CREATE INDEX IF NOT EXISTS idx_miner_configs_miner
                ON miner_configs(miner_id);
            CREATE INDEX IF NOT EXISTS idx_miner_configs_wallet
                ON miner_configs(wallet_id);
        """)


@contextmanager
def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def add_wallet(name: str, address: str, pool_adapter: str, coin: str) -> Optional[int]:
    """Add a new wallet to track"""
    try:
        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO wallets (name, address, pool_adapter, coin)
                VALUES (?, ?, ?, ?)
            """, (name, address, pool_adapter, coin))
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        print(f"Wallet already exists: {address} on {pool_adapter}")
        return None


def get_wallets(enabled_only: bool = True) -> list[dict]:
    """Get all tracked wallets"""
    with get_db() as conn:
        if enabled_only:
            rows = conn.execute("""
                SELECT id, name, address, pool_adapter, coin, enabled, created_at
                FROM wallets
                WHERE enabled = TRUE
                ORDER BY created_at DESC
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, name, address, pool_adapter, coin, enabled, created_at
                FROM wallets
                ORDER BY created_at DESC
            """).fetchall()
        return [dict(row) for row in rows]


def get_wallet(wallet_id: int) -> Optional[dict]:
    """Get a specific wallet by ID"""
    with get_db() as conn:
        row = conn.execute("""
            SELECT id, name, address, pool_adapter, coin, enabled, created_at
            FROM wallets
            WHERE id = ?
        """, (wallet_id,)).fetchone()
        return dict(row) if row else None


def update_wallet(wallet_id: int, name: Optional[str] = None, enabled: Optional[bool] = None) -> bool:
    """Update wallet details"""
    updates = []
    params = []

    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if enabled is not None:
        updates.append("enabled = ?")
        params.append(enabled)

    if not updates:
        return False

    params.append(wallet_id)

    with get_db() as conn:
        conn.execute(f"""
            UPDATE wallets
            SET {', '.join(updates)}
            WHERE id = ?
        """, params)
        return True


def delete_wallet(wallet_id: int) -> bool:
    """Delete a wallet and all its associated data"""
    with get_db() as conn:
        conn.execute("DELETE FROM pool_snapshots WHERE wallet_id = ?", (wallet_id,))
        conn.execute("DELETE FROM worker_snapshots WHERE wallet_id = ?", (wallet_id,))
        conn.execute("DELETE FROM best_shares WHERE wallet_id = ?", (wallet_id,))
        conn.execute("DELETE FROM wallets WHERE id = ?", (wallet_id,))
        return True


def save_pool_snapshot(
    pool_name: str,
    coin: str,
    hashrate: float,
    hashrate_avg: float = None,
    workers_online: int = 0,
    workers_offline: int = 0,
    balance: float = 0,
    best_share: float = None,
    best_ever: float = None,
    network_difficulty: float = None,
    raw_data: dict = None,
    wallet_id: int = None
):
    """Save a pool stats snapshot"""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO pool_snapshots
            (wallet_id, pool_name, coin, hashrate, hashrate_avg, workers_online,
             workers_offline, balance, best_share, best_ever,
             network_difficulty, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            wallet_id, pool_name, coin, hashrate, hashrate_avg, workers_online,
            workers_offline, balance, best_share, best_ever,
            network_difficulty, json.dumps(raw_data) if raw_data else None
        ))


def save_worker_snapshot(
    pool_name: str,
    worker_name: str,
    hashrate: float,
    hashrate_avg: float = None,
    best_share: float = None,
    shares_count: int = 0,
    offline: bool = False,
    wallet_id: int = None
):
    """Save a worker stats snapshot"""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO worker_snapshots
            (wallet_id, pool_name, worker_name, hashrate, hashrate_avg,
             best_share, shares_count, offline)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            wallet_id, pool_name, worker_name, hashrate, hashrate_avg,
            best_share, shares_count, offline
        ))


def log_best_share(
    pool_name: str,
    difficulty: float,
    worker_name: str = None,
    is_best_ever: bool = False,
    wallet_id: int = None
):
    """Log a new best share"""
    with get_db() as conn:
        # Check if this is actually a new best for this wallet
        if wallet_id:
            last = conn.execute("""
                SELECT difficulty FROM best_shares
                WHERE pool_name = ? AND wallet_id = ?
                ORDER BY difficulty DESC LIMIT 1
            """, (pool_name, wallet_id)).fetchone()
        else:
            last = conn.execute("""
                SELECT difficulty FROM best_shares
                WHERE pool_name = ?
                ORDER BY difficulty DESC LIMIT 1
            """, (pool_name,)).fetchone()

        if not last or difficulty > last['difficulty']:
            conn.execute("""
                INSERT INTO best_shares
                (wallet_id, pool_name, worker_name, difficulty, is_best_ever)
                VALUES (?, ?, ?, ?, ?)
            """, (wallet_id, pool_name, worker_name, difficulty, is_best_ever))
            return True
    return False


def get_hashrate_history(
    pool_name: str,
    hours: int = 24
) -> list[dict]:
    """Get hashrate history for a pool"""
    with get_db() as conn:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        rows = conn.execute("""
            SELECT timestamp, hashrate, hashrate_avg, network_difficulty
            FROM pool_snapshots
            WHERE pool_name = ? AND timestamp > ?
            ORDER BY timestamp ASC
        """, (pool_name, cutoff)).fetchall()
        
        return [dict(row) for row in rows]


def get_best_shares_history(
    pool_name: str = None,
    limit: int = 100
) -> list[dict]:
    """Get best shares history"""
    with get_db() as conn:
        if pool_name:
            rows = conn.execute("""
                SELECT timestamp, pool_name, worker_name, difficulty, is_best_ever
                FROM best_shares
                WHERE pool_name = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (pool_name, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT timestamp, pool_name, worker_name, difficulty, is_best_ever
                FROM best_shares
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,)).fetchall()
        
        return [dict(row) for row in rows]


def get_worker_history(
    pool_name: str,
    worker_name: str,
    hours: int = 24
) -> list[dict]:
    """Get history for a specific worker"""
    with get_db() as conn:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        rows = conn.execute("""
            SELECT timestamp, hashrate, hashrate_avg, best_share, shares_count
            FROM worker_snapshots
            WHERE pool_name = ? AND worker_name = ? AND timestamp > ?
            ORDER BY timestamp ASC
        """, (pool_name, worker_name, cutoff)).fetchall()
        
        return [dict(row) for row in rows]


def cleanup_old_data(days: int = 30):
    """Remove data older than specified days"""
    with get_db() as conn:
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        conn.execute(
            "DELETE FROM pool_snapshots WHERE timestamp < ?", (cutoff,)
        )
        conn.execute(
            "DELETE FROM worker_snapshots WHERE timestamp < ?", (cutoff,)
        )
        # Keep best shares longer (90 days)
        best_cutoff = datetime.utcnow() - timedelta(days=90)
        conn.execute(
            "DELETE FROM best_shares WHERE timestamp < ? AND is_best_ever = FALSE",
            (best_cutoff,)
        )


def log_share_submission(
    pool_name: str,
    difficulty: float,
    wallet_id: int = None,
    worker_name: str = None,
    accepted: bool = True
) -> int:
    """Log a share submission for detailed tracking"""
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO share_submissions
            (wallet_id, pool_name, worker_name, difficulty, accepted)
            VALUES (?, ?, ?, ?, ?)
        """, (wallet_id, pool_name, worker_name, difficulty, accepted))
        return cursor.lastrowid


def get_share_submissions(
    wallet_id: int = None,
    pool_name: str = None,
    hours: int = 24,
    limit: int = 1000
) -> list[dict]:
    """Get recent share submissions"""
    with get_db() as conn:
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        if wallet_id and pool_name:
            rows = conn.execute("""
                SELECT timestamp, pool_name, worker_name, difficulty, accepted
                FROM share_submissions
                WHERE wallet_id = ? AND pool_name = ? AND timestamp > ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (wallet_id, pool_name, cutoff, limit)).fetchall()
        elif wallet_id:
            rows = conn.execute("""
                SELECT timestamp, pool_name, worker_name, difficulty, accepted
                FROM share_submissions
                WHERE wallet_id = ? AND timestamp > ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (wallet_id, cutoff, limit)).fetchall()
        elif pool_name:
            rows = conn.execute("""
                SELECT timestamp, pool_name, worker_name, difficulty, accepted
                FROM share_submissions
                WHERE pool_name = ? AND timestamp > ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (pool_name, cutoff, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT timestamp, pool_name, worker_name, difficulty, accepted
                FROM share_submissions
                WHERE timestamp > ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (cutoff, limit)).fetchall()

        return [dict(row) for row in rows]


def get_share_statistics(wallet_id: int, hours: int = 24) -> dict:
    """Get share submission statistics for a wallet"""
    with get_db() as conn:
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        result = conn.execute("""
            SELECT
                COUNT(*) as total_shares,
                SUM(CASE WHEN accepted = 1 THEN 1 ELSE 0 END) as accepted_shares,
                SUM(CASE WHEN accepted = 0 THEN 1 ELSE 0 END) as rejected_shares,
                MAX(difficulty) as best_share,
                AVG(difficulty) as avg_difficulty
            FROM share_submissions
            WHERE wallet_id = ? AND timestamp > ?
        """, (wallet_id, cutoff)).fetchone()

        return dict(result) if result else {}


# Miner management functions
def add_miner(
    name: str,
    miner_type: str,
    ip_address: str,
    mac_address: str = None,
    api_port: int = None,
    api_url: str = None,
    auto_discovered: bool = False
) -> Optional[int]:
    """Add a new miner device"""
    try:
        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO miners
                (name, miner_type, ip_address, mac_address, api_port, api_url, auto_discovered, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, miner_type, ip_address, mac_address, api_port, api_url, auto_discovered, datetime.utcnow()))
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        # Update last_seen if miner already exists
        with get_db() as conn:
            conn.execute("""
                UPDATE miners
                SET last_seen = ?, status = 'online'
                WHERE ip_address = ?
            """, (datetime.utcnow(), ip_address))
        return None


def get_miners(enabled_only: bool = False) -> list[dict]:
    """Get all miners"""
    with get_db() as conn:
        if enabled_only:
            rows = conn.execute("""
                SELECT id, name, miner_type, ip_address, mac_address, api_port, api_url,
                       status, enabled, auto_discovered, created_at, last_seen
                FROM miners
                WHERE enabled = TRUE
                ORDER BY last_seen DESC
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, name, miner_type, ip_address, mac_address, api_port, api_url,
                       status, enabled, auto_discovered, created_at, last_seen
                FROM miners
                ORDER BY last_seen DESC
            """).fetchall()
        return [dict(row) for row in rows]


def get_miner(miner_id: int) -> Optional[dict]:
    """Get a specific miner"""
    with get_db() as conn:
        row = conn.execute("""
            SELECT id, name, miner_type, ip_address, mac_address, api_port, api_url,
                   status, enabled, auto_discovered, created_at, last_seen
            FROM miners
            WHERE id = ?
        """, (miner_id,)).fetchone()
        return dict(row) if row else None


def update_miner(
    miner_id: int,
    name: str = None,
    status: str = None,
    enabled: bool = None,
    last_seen: datetime = None
) -> bool:
    """Update miner details"""
    updates = []
    params = []

    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if enabled is not None:
        updates.append("enabled = ?")
        params.append(enabled)
    if last_seen is not None:
        updates.append("last_seen = ?")
        params.append(last_seen)

    if not updates:
        return False

    params.append(miner_id)

    with get_db() as conn:
        conn.execute(f"""
            UPDATE miners
            SET {', '.join(updates)}
            WHERE id = ?
        """, params)
        return True


def delete_miner(miner_id: int) -> bool:
    """Delete a miner and its configurations"""
    with get_db() as conn:
        conn.execute("DELETE FROM miner_configs WHERE miner_id = ?", (miner_id,))
        conn.execute("DELETE FROM miners WHERE id = ?", (miner_id,))
        return True


def add_miner_config(
    miner_id: int,
    wallet_id: int = None,
    pool_url: str = None,
    worker_name: str = None
) -> int:
    """Link a miner to a wallet/pool"""
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO miner_configs (miner_id, wallet_id, pool_url, worker_name)
            VALUES (?, ?, ?, ?)
        """, (miner_id, wallet_id, pool_url, worker_name))
        return cursor.lastrowid


def get_miner_configs(miner_id: int = None, wallet_id: int = None) -> list[dict]:
    """Get miner configurations"""
    with get_db() as conn:
        if miner_id:
            rows = conn.execute("""
                SELECT mc.*, m.name as miner_name, m.miner_type, m.ip_address,
                       w.name as wallet_name, w.address as wallet_address
                FROM miner_configs mc
                LEFT JOIN miners m ON mc.miner_id = m.id
                LEFT JOIN wallets w ON mc.wallet_id = w.id
                WHERE mc.miner_id = ? AND mc.active = TRUE
                ORDER BY mc.detected_at DESC
            """, (miner_id,)).fetchall()
        elif wallet_id:
            rows = conn.execute("""
                SELECT mc.*, m.name as miner_name, m.miner_type, m.ip_address,
                       w.name as wallet_name, w.address as wallet_address
                FROM miner_configs mc
                LEFT JOIN miners m ON mc.miner_id = m.id
                LEFT JOIN wallets w ON mc.wallet_id = w.id
                WHERE mc.wallet_id = ? AND mc.active = TRUE
                ORDER BY mc.detected_at DESC
            """, (wallet_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT mc.*, m.name as miner_name, m.miner_type, m.ip_address,
                       w.name as wallet_name, w.address as wallet_address
                FROM miner_configs mc
                LEFT JOIN miners m ON mc.miner_id = m.id
                LEFT JOIN wallets w ON mc.wallet_id = w.id
                WHERE mc.active = TRUE
                ORDER BY mc.detected_at DESC
            """).fetchall()
        return [dict(row) for row in rows]


def update_miner_config(config_id: int, wallet_id: int = None, active: bool = None) -> bool:
    """Update miner configuration"""
    updates = []
    params = []

    if wallet_id is not None:
        updates.append("wallet_id = ?")
        params.append(wallet_id)
    if active is not None:
        updates.append("active = ?")
        params.append(active)

    if not updates:
        return False

    params.append(config_id)

    with get_db() as conn:
        conn.execute(f"""
            UPDATE miner_configs
            SET {', '.join(updates)}
            WHERE id = ?
        """, params)
        return True


def delete_miner_config(config_id: int) -> bool:
    """Delete a miner configuration"""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM miner_configs WHERE id = ?", (config_id,))
        return cursor.rowcount > 0


def get_stats_summary(pool_name: str = None) -> dict:
    """Get summary statistics"""
    with get_db() as conn:
        summary = {}
        
        # Total snapshots
        if pool_name:
            count = conn.execute(
                "SELECT COUNT(*) FROM pool_snapshots WHERE pool_name = ?",
                (pool_name,)
            ).fetchone()[0]
        else:
            count = conn.execute(
                "SELECT COUNT(*) FROM pool_snapshots"
            ).fetchone()[0]
        summary['total_snapshots'] = count
        
        # Best share ever
        if pool_name:
            best = conn.execute(
                "SELECT MAX(difficulty) FROM best_shares WHERE pool_name = ?",
                (pool_name,)
            ).fetchone()[0]
        else:
            best = conn.execute(
                "SELECT MAX(difficulty) FROM best_shares"
            ).fetchone()[0]
        summary['best_share_ever'] = best
        
        # Average hashrate (last 24h)
        cutoff = datetime.utcnow() - timedelta(hours=24)
        if pool_name:
            avg = conn.execute("""
                SELECT AVG(hashrate) FROM pool_snapshots 
                WHERE pool_name = ? AND timestamp > ?
            """, (pool_name, cutoff)).fetchone()[0]
        else:
            avg = conn.execute("""
                SELECT AVG(hashrate) FROM pool_snapshots 
                WHERE timestamp > ?
            """, (cutoff,)).fetchone()[0]
        summary['avg_hashrate_24h'] = avg
        
        return summary


# Initialize database on import
init_db()


if __name__ == "__main__":
    # Test the database
    print("Testing database...")
    
    # Save some test data
    save_pool_snapshot(
        pool_name="test_pool",
        coin="BTC",
        hashrate=100e12,
        workers_online=2,
        best_share=1e15
    )
    
    save_worker_snapshot(
        pool_name="test_pool",
        worker_name="worker1",
        hashrate=50e12
    )
    
    log_best_share(
        pool_name="test_pool",
        difficulty=1e15,
        worker_name="worker1"
    )
    
    # Get summary
    summary = get_stats_summary()
    print(f"Summary: {summary}")
    
    # Get history
    history = get_hashrate_history("test_pool", hours=1)
    print(f"History entries: {len(history)}")
    
    print("Database test complete!")
