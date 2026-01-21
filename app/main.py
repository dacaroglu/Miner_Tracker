"""
Mining Dashboard - Flexible Multi-Pool Multi-Wallet Tracker
Uses pool adapters for easy addition of new pools
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
import httpx
import asyncio
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from pydantic_settings import BaseSettings

from app.pool_adapters import get_adapter, list_available_pools, PoolStats
from app.miner_adapters import get_miner_adapter, list_miner_types
from app.network_scanner import scan_network, discover_and_register_miners, poll_miners_for_shares
from app import database as db


class Settings(BaseSettings):
    # Refresh interval in seconds
    refresh_interval: int = 60

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()


# Data models
class WalletData(BaseModel):
    wallet_id: int
    name: str
    address: str
    pool_adapter: str
    coin: str
    enabled: bool
    stats: Optional[PoolStats] = None
    error: Optional[str] = None


class DashboardData(BaseModel):
    wallets: List[WalletData]
    last_updated: str
    network_difficulties: dict = {}


class WalletCreate(BaseModel):
    name: str
    address: str
    pool_adapter: str


class WalletUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None


# Global state for caching
cache = {
    "data": None,
    "last_fetch": None
}


async def fetch_network_stats(client: httpx.AsyncClient, coins_needed: set) -> dict:
    """Fetch network difficulty for coins being mined"""
    difficulties = {}

    # BTC difficulty
    if 'BTC' in coins_needed:
        try:
            # Use blockchain.info API for reliable BTC difficulty
            btc_resp = await client.get("https://blockchain.info/q/getdifficulty", timeout=10.0)
            if btc_resp.status_code == 200:
                difficulties['BTC'] = float(btc_resp.text.strip())
        except Exception as e:
            print(f"Error fetching BTC difficulty: {e}")
            # Fallback to mempool.space
            try:
                btc_resp = await client.get("https://mempool.space/api/v1/difficulty-adjustment", timeout=10.0)
                if btc_resp.status_code == 200:
                    btc_data = btc_resp.json()
                    if btc_data.get('difficulty'):
                        difficulties['BTC'] = float(btc_data['difficulty'])
            except Exception as e2:
                print(f"Fallback BTC difficulty fetch failed: {e2}")

    # BCH difficulty
    if 'BCH' in coins_needed:
        try:
            bch_resp = await client.get("https://bch.2miners.com/api/stats", timeout=10.0)
            if bch_resp.status_code == 200:
                bch_data = bch_resp.json()
                nodes = bch_data.get('nodes', [])
                if nodes:
                    difficulties['BCH'] = float(nodes[0].get('difficulty', 0))
        except Exception as e:
            print(f"Error fetching BCH difficulty: {e}")

    return difficulties


async def fetch_wallet_stats(client: httpx.AsyncClient, wallet: dict) -> WalletData:
    """Fetch stats for a single wallet"""
    adapter = get_adapter(wallet['pool_adapter'])

    if not adapter:
        return WalletData(
            wallet_id=wallet['id'],
            name=wallet['name'],
            address=wallet['address'],
            pool_adapter=wallet['pool_adapter'],
            coin=wallet['coin'],
            enabled=wallet['enabled'],
            error=f"Unknown pool adapter: {wallet['pool_adapter']}"
        )

    try:
        stats = await adapter.fetch_stats(client, wallet['address'])

        # Save snapshot to database
        if stats:
            db.save_pool_snapshot(
                wallet_id=wallet['id'],
                pool_name=stats.pool_name,
                coin=stats.coin,
                hashrate=stats.hashrate,
                hashrate_avg=stats.hashrate_avg,
                workers_online=stats.workers_online,
                workers_offline=stats.workers_offline,
                balance=stats.balance,
                best_share=stats.best_share,
                best_ever=stats.best_ever,
                raw_data=stats.raw_data
            )

            # Save worker snapshots
            for worker in stats.workers:
                db.save_worker_snapshot(
                    wallet_id=wallet['id'],
                    pool_name=stats.pool_name,
                    worker_name=worker.name,
                    hashrate=worker.hashrate,
                    hashrate_avg=worker.hashrate_avg,
                    best_share=worker.difficulty,
                    shares_count=worker.shares_count,
                    offline=worker.offline
                )

            # Log best shares
            if stats.best_share:
                db.log_best_share(
                    wallet_id=wallet['id'],
                    pool_name=stats.pool_name,
                    difficulty=stats.best_share
                )

        return WalletData(
            wallet_id=wallet['id'],
            name=wallet['name'],
            address=wallet['address'],
            pool_adapter=wallet['pool_adapter'],
            coin=wallet['coin'],
            enabled=wallet['enabled'],
            stats=stats,
            error=None if stats else "No data available"
        )
    except Exception as e:
        print(f"Error fetching stats for wallet {wallet['name']}: {e}")
        return WalletData(
            wallet_id=wallet['id'],
            name=wallet['name'],
            address=wallet['address'],
            pool_adapter=wallet['pool_adapter'],
            coin=wallet['coin'],
            enabled=wallet['enabled'],
            error=str(e)
        )


async def fetch_all_stats() -> DashboardData:
    """Fetch all wallet stats"""
    async with httpx.AsyncClient() as client:
        # Get all enabled wallets
        wallets = db.get_wallets(enabled_only=True)

        # Determine which coins we need network difficulty for
        coins_needed = set(wallet['coin'] for wallet in wallets)

        # Fetch stats for all wallets concurrently
        wallet_tasks = [fetch_wallet_stats(client, wallet) for wallet in wallets]
        network_task = fetch_network_stats(client, coins_needed)

        results = await asyncio.gather(*wallet_tasks, network_task)

        wallet_data = results[:-1]
        network_difficulties = results[-1]

        return DashboardData(
            wallets=list(wallet_data),
            last_updated=datetime.utcnow().isoformat(),
            network_difficulties=network_difficulties
        )


# Background task for periodic updates
async def periodic_fetch():
    """Background task to periodically fetch stats"""
    while True:
        try:
            data = await fetch_all_stats()
            cache["data"] = data
            cache["last_fetch"] = datetime.utcnow()
            print(f"[{datetime.utcnow().isoformat()}] Fetched stats for {len(data.wallets)} wallets")
        except Exception as e:
            print(f"Error in periodic fetch: {e}")
            import traceback
            traceback.print_exc()

        await asyncio.sleep(settings.refresh_interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Start background tasks
    fetch_task = asyncio.create_task(periodic_fetch())
    miner_task = asyncio.create_task(poll_miners_for_shares())
    yield
    # Cancel background tasks
    fetch_task.cancel()
    miner_task.cancel()


# Create FastAPI app
app = FastAPI(
    title="Mining Dashboard",
    description="Multi-Pool Multi-Wallet Mining Dashboard with Pool Adapters",
    version="2.0.0",
    lifespan=lifespan
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the main dashboard"""
    data = cache.get("data")
    if not data:
        # Fetch data if cache is empty
        data = await fetch_all_stats()
        cache["data"] = data
        cache["last_fetch"] = datetime.utcnow()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "data": data,
        "settings": settings
    })


@app.get("/api/stats")
async def get_stats():
    """API endpoint to get all stats as JSON"""
    data = cache.get("data")
    if not data:
        data = await fetch_all_stats()
        cache["data"] = data
        cache["last_fetch"] = datetime.utcnow()

    return data


@app.get("/api/refresh")
async def refresh_stats():
    """Force refresh all stats"""
    data = await fetch_all_stats()
    cache["data"] = data
    cache["last_fetch"] = datetime.utcnow()
    return {"status": "refreshed", "timestamp": cache["last_fetch"].isoformat()}


# Wallet management endpoints
@app.get("/api/wallets")
async def get_wallets(enabled_only: bool = True):
    """Get all tracked wallets"""
    return db.get_wallets(enabled_only=enabled_only)


@app.get("/api/wallets/{wallet_id}")
async def get_wallet(wallet_id: int):
    """Get a specific wallet"""
    wallet = db.get_wallet(wallet_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return wallet


@app.post("/api/wallets")
async def create_wallet(wallet: WalletCreate):
    """Add a new wallet to track"""
    # Validate pool adapter exists
    adapter = get_adapter(wallet.pool_adapter)
    if not adapter:
        raise HTTPException(status_code=400, detail=f"Unknown pool adapter: {wallet.pool_adapter}")

    # Validate address format
    if not adapter.validate_address(wallet.address):
        raise HTTPException(status_code=400, detail=f"Invalid address format for {wallet.pool_adapter}")

    # Add wallet
    wallet_id = db.add_wallet(
        name=wallet.name,
        address=wallet.address,
        pool_adapter=wallet.pool_adapter,
        coin=adapter.coin
    )

    if not wallet_id:
        raise HTTPException(status_code=409, detail="Wallet already exists")

    return {"wallet_id": wallet_id, "message": "Wallet added successfully"}


@app.patch("/api/wallets/{wallet_id}")
async def update_wallet(wallet_id: int, update: WalletUpdate):
    """Update wallet details"""
    success = db.update_wallet(
        wallet_id=wallet_id,
        name=update.name,
        enabled=update.enabled
    )

    if not success:
        raise HTTPException(status_code=404, detail="Wallet not found")

    return {"message": "Wallet updated successfully"}


@app.delete("/api/wallets/{wallet_id}")
async def delete_wallet(wallet_id: int):
    """Delete a wallet"""
    success = db.delete_wallet(wallet_id)
    if not success:
        raise HTTPException(status_code=404, detail="Wallet not found")

    return {"message": "Wallet deleted successfully"}


@app.get("/api/pools")
async def get_available_pools():
    """Get list of available pool adapters"""
    return list_available_pools()


@app.get("/api/wallet/{wallet_id}/stats")
async def get_wallet_stats(wallet_id: int):
    """Get current stats for a specific wallet"""
    wallet = db.get_wallet(wallet_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    async with httpx.AsyncClient() as client:
        wallet_data = await fetch_wallet_stats(client, wallet)
        return wallet_data


@app.get("/api/wallet/{wallet_id}/history")
async def get_wallet_history(wallet_id: int, hours: int = 24):
    """Get historical data for a wallet"""
    wallet = db.get_wallet(wallet_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    history = db.get_hashrate_history(wallet['pool_adapter'], hours=hours)
    return history


# Share tracking endpoints
class ShareSubmission(BaseModel):
    pool_name: str
    difficulty: float
    worker_name: Optional[str] = None
    accepted: bool = True


@app.post("/api/wallet/{wallet_id}/shares")
async def log_share(wallet_id: int, share: ShareSubmission):
    """Log a share submission for tracking"""
    wallet = db.get_wallet(wallet_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    share_id = db.log_share_submission(
        wallet_id=wallet_id,
        pool_name=share.pool_name,
        difficulty=share.difficulty,
        worker_name=share.worker_name,
        accepted=share.accepted
    )

    return {"share_id": share_id, "message": "Share logged successfully"}


@app.get("/api/wallet/{wallet_id}/shares")
async def get_shares(wallet_id: int, hours: int = 24, limit: int = 100):
    """Get recent share submissions for a wallet"""
    wallet = db.get_wallet(wallet_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    shares = db.get_share_submissions(wallet_id=wallet_id, hours=hours, limit=limit)
    return shares


@app.get("/api/wallet/{wallet_id}/share-stats")
async def get_share_stats(wallet_id: int, hours: int = 24):
    """Get share submission statistics for a wallet"""
    wallet = db.get_wallet(wallet_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    stats = db.get_share_statistics(wallet_id=wallet_id, hours=hours)
    return stats


# Miner management endpoints
class MinerCreate(BaseModel):
    name: str
    miner_type: str
    ip_address: str
    mac_address: Optional[str] = None
    api_port: Optional[int] = None


class MinerUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None


@app.get("/api/miners")
async def get_miners_list(enabled_only: bool = False):
    """Get all miners"""
    return db.get_miners(enabled_only=enabled_only)


@app.get("/api/miners/{miner_id}")
async def get_miner_details(miner_id: int):
    """Get specific miner details"""
    miner = db.get_miner(miner_id)
    if not miner:
        raise HTTPException(status_code=404, detail="Miner not found")
    return miner


@app.post("/api/miners")
async def create_miner(miner: MinerCreate):
    """Manually add a miner"""
    miner_id = db.add_miner(
        name=miner.name,
        miner_type=miner.miner_type,
        ip_address=miner.ip_address,
        mac_address=miner.mac_address,
        api_port=miner.api_port,
        auto_discovered=False
    )

    if not miner_id:
        raise HTTPException(status_code=409, detail="Miner with this IP already exists")

    return {"miner_id": miner_id, "message": "Miner added successfully"}


@app.patch("/api/miners/{miner_id}")
async def update_miner_details(miner_id: int, update: MinerUpdate):
    """Update miner details"""
    success = db.update_miner(
        miner_id=miner_id,
        name=update.name,
        enabled=update.enabled
    )

    if not success:
        raise HTTPException(status_code=404, detail="Miner not found")

    return {"message": "Miner updated successfully"}


@app.delete("/api/miners/{miner_id}")
async def delete_miner_device(miner_id: int):
    """Delete a miner"""
    success = db.delete_miner(miner_id)
    if not success:
        raise HTTPException(status_code=404, detail="Miner not found")

    return {"message": "Miner deleted successfully"}


@app.get("/api/miners/{miner_id}/info")
async def get_miner_live_info(miner_id: int):
    """Get live information from a miner"""
    miner = db.get_miner(miner_id)
    if not miner:
        raise HTTPException(status_code=404, detail="Miner not found")

    adapter = get_miner_adapter(miner['miner_type'])
    if not adapter:
        raise HTTPException(status_code=400, detail=f"No adapter for miner type: {miner['miner_type']}")

    info = await adapter.get_info(miner['ip_address'], miner['api_port'] or 80)
    if not info:
        raise HTTPException(status_code=503, detail="Could not connect to miner")

    # Update last_seen
    db.update_miner(miner_id, status='online', last_seen=datetime.utcnow())

    return info


@app.get("/api/miner-types")
async def get_miner_types():
    """Get list of supported miner types"""
    return list_miner_types()


@app.post("/api/miners/scan")
async def scan_for_miners(network: Optional[str] = None):
    """Scan network for mining devices"""
    miners = await discover_and_register_miners(save_to_db=True)
    return {
        "discovered": len(miners),
        "miners": miners
    }


@app.get("/api/miners/{miner_id}/configs")
async def get_miner_configurations(miner_id: int):
    """Get miner pool configurations"""
    configs = db.get_miner_configs(miner_id=miner_id)
    return configs


@app.post("/api/miners/{miner_id}/link-wallet")
async def link_miner_to_wallet(miner_id: int, wallet_id: int):
    """Link a miner to a tracked wallet"""
    miner = db.get_miner(miner_id)
    if not miner:
        raise HTTPException(status_code=404, detail="Miner not found")

    wallet = db.get_wallet(wallet_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    # Get miner's pool configuration
    adapter = get_miner_adapter(miner['miner_type'])
    if adapter:
        info = await adapter.get_info(miner['ip_address'], miner['api_port'] or 80)
        if info:
            config_id = db.add_miner_config(
                miner_id=miner_id,
                wallet_id=wallet_id,
                pool_url=info.pool_url,
                worker_name=info.pool_user
            )
            return {"config_id": config_id, "message": "Miner linked to wallet"}

    raise HTTPException(status_code=503, detail="Could not get miner configuration")


@app.delete("/api/miners/configs/{config_id}")
async def delete_miner_config(config_id: int):
    """Delete a miner configuration (unlink from wallet)"""
    success = db.delete_miner_config(config_id)
    if not success:
        raise HTTPException(status_code=404, detail="Config not found")

    return {"message": "Miner configuration deleted successfully"}
