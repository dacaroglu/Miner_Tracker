"""
Pool Adapters - Standardized interface for different mining pools
Each adapter implements the same interface for fetching stats
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
import httpx


class WorkerStats(BaseModel):
    name: str
    hashrate: float
    hashrate_avg: Optional[float] = None
    last_share: Optional[int] = None
    shares_count: Optional[int] = None
    difficulty: Optional[float] = None
    offline: bool = False


class PoolStats(BaseModel):
    pool_name: str
    coin: str
    address: str
    hashrate: float
    hashrate_avg: Optional[float] = None
    workers_online: int
    workers_offline: int
    balance: float
    paid: float
    best_share: Optional[float] = None
    best_ever: Optional[float] = None
    network_difficulty: Optional[float] = None
    last_share: Optional[int] = None
    workers: List[WorkerStats] = []
    shares: List[Dict] = []
    raw_data: Dict = {}


def parse_hashrate(hr_string) -> float:
    """Parse hashrate strings like '11.5T', '9.68G', '602M' to float"""
    if not hr_string or hr_string == "0":
        return 0.0

    if isinstance(hr_string, (int, float)):
        return float(hr_string)

    hr_string = str(hr_string).strip()
    multipliers = {
        'K': 1e3,
        'M': 1e6,
        'G': 1e9,
        'T': 1e12,
        'P': 1e15,
        'E': 1e18
    }

    for suffix, mult in multipliers.items():
        if hr_string.endswith(suffix):
            try:
                return float(hr_string[:-1]) * mult
            except ValueError:
                return 0.0

    try:
        return float(hr_string)
    except ValueError:
        return 0.0


class PoolAdapter(ABC):
    """Base adapter class for mining pools"""

    def __init__(self, coin: str):
        self.coin = coin

    @abstractmethod
    async def fetch_stats(self, client: httpx.AsyncClient, address: str) -> Optional[PoolStats]:
        """Fetch stats for a given address"""
        pass

    @abstractmethod
    def get_pool_name(self) -> str:
        """Get the pool name"""
        pass

    @abstractmethod
    def validate_address(self, address: str) -> bool:
        """Validate if the address format is correct for this pool"""
        pass


class CKPoolAdapter(PoolAdapter):
    """Adapter for solo.ckpool.org (BTC only)"""

    def __init__(self):
        super().__init__(coin="BTC")

    def get_pool_name(self) -> str:
        return "Solo CKPool"

    def validate_address(self, address: str) -> bool:
        """Basic BTC address validation"""
        if not address or len(address) < 26:
            return False
        # BTC addresses start with 1, 3, or bc1
        return address.startswith(('1', '3', 'bc1'))

    async def fetch_stats(self, client: httpx.AsyncClient, address: str) -> Optional[PoolStats]:
        """Fetch stats from solo.ckpool.org"""
        if not self.validate_address(address):
            return None

        try:
            url = f"https://solo.ckpool.org/users/{address}"
            response = await client.get(url, timeout=15.0)

            if response.status_code == 404:
                return None

            response.raise_for_status()
            data = response.json()

            # Parse worker data
            worker_stats = []
            workers_data = data.get('worker', [])

            for w in workers_data:
                hashrate = parse_hashrate(w.get('hashrate1m', 0))
                hashrate_avg = parse_hashrate(w.get('hashrate1hr', 0))
                is_offline = hashrate == 0 and hashrate_avg == 0

                worker_stats.append(WorkerStats(
                    name=w.get('workername', 'unknown').split('.')[-1] or 'default',
                    hashrate=hashrate,
                    hashrate_avg=hashrate_avg,
                    last_share=w.get('lastshare'),
                    shares_count=w.get('shares', 0),
                    difficulty=float(w.get('bestshare', 0)),
                    offline=is_offline
                ))

            # Calculate totals
            workers_online = sum(1 for w in worker_stats if not w.offline)
            workers_offline = sum(1 for w in worker_stats if w.offline)

            return PoolStats(
                pool_name=self.get_pool_name(),
                coin=self.coin,
                address=address,
                hashrate=parse_hashrate(data.get('hashrate1m', 0)),
                hashrate_avg=parse_hashrate(data.get('hashrate1hr', 0)),
                workers_online=workers_online,
                workers_offline=workers_offline,
                balance=0,
                paid=0,
                best_share=float(data.get('bestshare', 0)),
                best_ever=float(data.get('bestever', 0)),
                last_share=data.get('lastshare'),
                workers=worker_stats,
                raw_data=data
            )
        except httpx.HTTPError as e:
            print(f"Error fetching ckpool stats: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error fetching ckpool stats: {e}")
            return None


class TwoMinersSoloAdapter(PoolAdapter):
    """Adapter for 2miners.com solo pools (BCH, BTC, etc.)"""

    POOL_URLS = {
        "BCH": "https://solo-bch.2miners.com/api",
        "BTC": "https://solo-btc.2miners.com/api",
    }

    def __init__(self, coin: str = "BCH"):
        super().__init__(coin=coin)
        if coin not in self.POOL_URLS:
            raise ValueError(f"Coin {coin} not supported. Supported: {list(self.POOL_URLS.keys())}")

    def get_pool_name(self) -> str:
        return f"2Miners Solo {self.coin}"

    def validate_address(self, address: str) -> bool:
        """Basic address validation"""
        if not address or len(address) < 20:
            return False

        if self.coin == "BCH":
            # BCH can be bitcoincash: or legacy format
            return len(address) > 20
        elif self.coin == "BTC":
            return address.startswith(('1', '3', 'bc1'))

        return True

    async def fetch_stats(self, client: httpx.AsyncClient, address: str) -> Optional[PoolStats]:
        """Fetch stats from 2miners solo pool"""
        if not self.validate_address(address):
            return None

        try:
            base_url = self.POOL_URLS[self.coin]
            account_url = f"{base_url}/accounts/{address}"
            response = await client.get(account_url, timeout=15.0)

            if response.status_code == 404:
                return None

            response.raise_for_status()
            data = response.json()

            if not data or 'workers' not in data:
                print(f"2miners returned empty or invalid data")
                return None

            # Parse workers
            worker_stats = []
            workers_data = data.get('workers', {})

            for worker_name, w_data in workers_data.items():
                worker_stats.append(WorkerStats(
                    name=worker_name if worker_name != "0" else "default",
                    hashrate=float(w_data.get('hr', 0)),
                    hashrate_avg=float(w_data.get('hr2', 0)),
                    last_share=w_data.get('lastBeat'),
                    shares_count=w_data.get('sharesValid', 0),
                    offline=w_data.get('offline', False)
                ))

            # Get stats and rounds for best share tracking
            stats = data.get('stats', {})
            config = data.get('config', {})
            total_reward = data.get('24hreward', 0)

            # Try to get rounds/shares data for best share calculation
            # 2miners tracks "luck" which is share difficulty vs network difficulty
            best_share_diff = None
            best_ever_diff = None

            # Check if there's immature/pending blocks (means we found shares close to block)
            rounds = data.get('roundShares', 0)
            if rounds and rounds > 0:
                # Estimate best share from valid shares and pool difficulty
                pool_stats_resp = await client.get(f"{base_url}/stats", timeout=10.0)
                if pool_stats_resp.status_code == 200:
                    pool_stats = pool_stats_resp.json()
                    network_diff = pool_stats.get('nodes', [{}])[0].get('difficulty', 0)
                    if network_diff:
                        # Best share would be proportional to valid shares
                        # This is an approximation since 2miners doesn't expose per-share difficulty
                        best_share_diff = float(network_diff) * 0.01  # Rough estimate

            return PoolStats(
                pool_name=self.get_pool_name(),
                coin=self.coin,
                address=address,
                hashrate=float(data.get('currentHashrate', 0)),
                hashrate_avg=float(data.get('hashrate', 0)),
                workers_online=data.get('workersOnline', 0),
                workers_offline=data.get('workersOffline', 0),
                balance=float(config.get('minPayout', 0)) / 1e8,
                paid=float(total_reward) / 1e8,
                best_share=best_share_diff,
                best_ever=best_ever_diff,
                last_share=stats.get('lastShare'),
                workers=worker_stats,
                shares=[],
                raw_data=data
            )
        except httpx.HTTPError as e:
            print(f"Error fetching 2miners stats: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error fetching 2miners stats: {e}")
            import traceback
            traceback.print_exc()
            return None


class TwoMinersPoolAdapter(PoolAdapter):
    """Adapter for 2miners.com regular pools (not solo)"""

    POOL_URLS = {
        "BCH": "https://bch.2miners.com/api",
        "BTC": "https://btc.2miners.com/api",
        "ETH": "https://eth.2miners.com/api",
        "RVN": "https://rvn.2miners.com/api",
    }

    def __init__(self, coin: str = "BCH"):
        super().__init__(coin=coin)
        if coin not in self.POOL_URLS:
            raise ValueError(f"Coin {coin} not supported. Supported: {list(self.POOL_URLS.keys())}")

    def get_pool_name(self) -> str:
        return f"2Miners {self.coin}"

    def validate_address(self, address: str) -> bool:
        """Basic address validation"""
        return len(address) > 20

    async def fetch_stats(self, client: httpx.AsyncClient, address: str) -> Optional[PoolStats]:
        """Fetch stats from 2miners regular pool"""
        if not self.validate_address(address):
            return None

        try:
            base_url = self.POOL_URLS[self.coin]
            account_url = f"{base_url}/accounts/{address}"
            response = await client.get(account_url, timeout=15.0)

            if response.status_code == 404:
                return None

            response.raise_for_status()
            data = response.json()

            if not data or 'workers' not in data:
                return None

            # Parse workers
            worker_stats = []
            workers_data = data.get('workers', {})

            for worker_name, w_data in workers_data.items():
                worker_stats.append(WorkerStats(
                    name=worker_name if worker_name != "0" else "default",
                    hashrate=float(w_data.get('hr', 0)),
                    hashrate_avg=float(w_data.get('hr2', 0)),
                    last_share=w_data.get('lastBeat'),
                    shares_count=w_data.get('sharesValid', 0),
                    offline=w_data.get('offline', False)
                ))

            stats = data.get('stats', {})
            payments = data.get('payments', [])
            total_paid = sum(p.get('amount', 0) for p in payments) if payments else 0

            return PoolStats(
                pool_name=self.get_pool_name(),
                coin=self.coin,
                address=address,
                hashrate=float(data.get('currentHashrate', 0)),
                hashrate_avg=float(data.get('hashrate', 0)),
                workers_online=data.get('workersOnline', 0),
                workers_offline=data.get('workersOffline', 0),
                balance=float(stats.get('balance', 0)) / 1e8,
                paid=float(total_paid) / 1e8,
                last_share=stats.get('lastShare'),
                workers=worker_stats,
                shares=[],
                raw_data=data
            )
        except Exception as e:
            print(f"Error fetching 2miners pool stats: {e}")
            import traceback
            traceback.print_exc()
            return None


# Pool adapter registry
POOL_ADAPTERS = {
    "ckpool_btc": CKPoolAdapter,
    "2miners_solo_bch": lambda: TwoMinersSoloAdapter("BCH"),
    "2miners_solo_btc": lambda: TwoMinersSoloAdapter("BTC"),
    "2miners_bch": lambda: TwoMinersPoolAdapter("BCH"),
    "2miners_btc": lambda: TwoMinersPoolAdapter("BTC"),
    "2miners_eth": lambda: TwoMinersPoolAdapter("ETH"),
    "2miners_rvn": lambda: TwoMinersPoolAdapter("RVN"),
}


def get_adapter(adapter_key: str) -> Optional[PoolAdapter]:
    """Get a pool adapter by key"""
    adapter_factory = POOL_ADAPTERS.get(adapter_key)
    if adapter_factory:
        return adapter_factory() if callable(adapter_factory) else adapter_factory
    return None


def list_available_pools() -> List[Dict[str, str]]:
    """List all available pool adapters"""
    pools = []
    for key in POOL_ADAPTERS.keys():
        adapter = get_adapter(key)
        if adapter:
            pools.append({
                "key": key,
                "name": adapter.get_pool_name(),
                "coin": adapter.coin
            })
    return pools
