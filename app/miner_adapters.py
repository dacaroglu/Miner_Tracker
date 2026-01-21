"""
Miner Adapters - Interface for different mining hardware
Each adapter knows how to communicate with specific miner types
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, List
from pydantic import BaseModel
import httpx
import re
import asyncio
import json
import re


def extract_clean_json(raw_data: bytes) -> Optional[dict]:
    """Extract and parse the first valid JSON object from CGMiner response"""
    # Decode and clean
    text = raw_data.decode('utf-8', errors='ignore')
    # Remove null bytes and control characters except valid JSON chars
    text = ''.join(char for char in text if char.isprintable() or char in '\n\r\t')
    text = text.replace('\x00', '').strip()

    # Find first opening brace
    start = text.find('{')
    if start == -1:
        return None

    # Count braces to find matching closing brace
    brace_count = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            brace_count += 1
        elif text[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                json_str = text[start:i+1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    # Try to fix common issues
                    # Remove trailing commas before closing braces/brackets
                    json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
                    try:
                        return json.loads(json_str)
                    except:
                        return None
    return None


class MinerInfo(BaseModel):
    """Information about a miner device"""
    miner_type: str
    firmware_version: Optional[str] = None
    hashrate: float = 0.0
    temperature: Optional[float] = None
    fan_speed: Optional[int] = None
    uptime: Optional[int] = None
    pool_url: Optional[str] = None
    pool_user: Optional[str] = None  # This is usually wallet.worker
    status: str = "unknown"
    raw_data: Dict = {}


class ShareInfo(BaseModel):
    """Information about a submitted share"""
    difficulty: float
    worker_name: Optional[str] = None
    accepted: bool = True
    timestamp: Optional[str] = None


class MinerAdapter(ABC):
    """Base class for miner adapters"""

    @abstractmethod
    def get_miner_type(self) -> str:
        """Get the miner type identifier"""
        pass

    @abstractmethod
    async def detect(self, ip: str, timeout: float = 2.0) -> bool:
        """Detect if this miner type is at the given IP"""
        pass

    @abstractmethod
    async def get_info(self, ip: str, port: int = None) -> Optional[MinerInfo]:
        """Get miner information"""
        pass

    @abstractmethod
    async def get_recent_shares(self, ip: str, port: int = None, count: int = 10) -> List[ShareInfo]:
        """Get recent share submissions (if supported)"""
        pass

    def extract_wallet_worker(self, pool_user: str) -> tuple[Optional[str], Optional[str]]:
        """Extract wallet address and worker name from pool user string"""
        if not pool_user:
            return None, None

        # Common formats:
        # wallet.worker
        # wallet
        # user.worker
        parts = pool_user.split('.')
        if len(parts) == 2:
            return parts[0], parts[1]
        elif len(parts) == 1:
            return parts[0], None
        return None, None


class NerdMinerAdapter(MinerAdapter):
    """Adapter for NerdMiner devices"""

    def get_miner_type(self) -> str:
        return "nerdminer"

    async def detect(self, ip: str, timeout: float = 2.0) -> bool:
        """Detect NerdMiner by checking its API endpoint"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://{ip}:80/api/system/info", timeout=timeout)
                if response.status_code == 200:
                    data = response.json()
                    # NerdQAxe/NerdMiner has specific fields like deviceModel, asicCount, stratumURL
                    if isinstance(data, dict) and any(key in data for key in ['deviceModel', 'asicCount', 'stratumURL', 'ASICModel']):
                        return True
        except:
            pass

        return False

    async def get_info(self, ip: str, port: int = 80) -> Optional[MinerInfo]:
        """Get NerdMiner information from its API"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://{ip}:{port}/api/system/info", timeout=5.0)
                if response.status_code == 200:
                    data = response.json()

                    if not isinstance(data, dict):
                        return None

                    # Extract from actual NerdMiner/NerdQAxe API format
                    # User provided actual structure: hashRate, temp, stratumURL, stratumPort, stratumUser, etc.
                    hashrate_gh = float(data.get('hashRate', 0))
                    hashrate = hashrate_gh * 1e9  # Convert GH/s to H/s for consistency
                    temp = data.get('temp')
                    device_model = data.get('deviceModel')
                    asic_model = data.get('ASICModel')

                    # Build firmware/version string from available info
                    version_parts = []
                    if device_model:
                        version_parts.append(device_model)
                    if asic_model:
                        version_parts.append(f"({asic_model})")
                    version = ' '.join(version_parts) if version_parts else None

                    # Get pool info from the same response
                    stratum_url = data.get('stratumURL', '')
                    stratum_port = data.get('stratumPort', '')
                    pool_url = f"{stratum_url}:{stratum_port}" if stratum_url else None
                    pool_user = data.get('stratumUser')

                    # Determine status based on pool connection and hashrate
                    status = 'offline'
                    if hashrate_gh > 0:
                        # Check if connected to pool
                        stratum_data = data.get('stratum', {})
                        if isinstance(stratum_data, dict):
                            pools = stratum_data.get('pools', [])
                            if pools and isinstance(pools, list) and len(pools) > 0:
                                if pools[0].get('connected', False):
                                    status = 'online'
                                else:
                                    status = 'idle'
                            else:
                                status = 'online'  # Has hashrate but no pool info
                        else:
                            status = 'online'  # Has hashrate

                    return MinerInfo(
                        miner_type=self.get_miner_type(),
                        firmware_version=version,
                        hashrate=hashrate,
                        temperature=temp,
                        pool_url=pool_url,
                        pool_user=pool_user,
                        status=status,
                        raw_data=data
                    )

        except Exception as e:
            print(f"Error getting NerdMiner info from {ip}: {e}")

        return None

    async def get_recent_shares(self, ip: str, port: int = 80, count: int = 10) -> List[ShareInfo]:
        """Get recent shares from NerdMiner"""
        shares = []
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://{ip}:{port}/api/shares", timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    for share in data.get('shares', [])[:count]:
                        shares.append(ShareInfo(
                            difficulty=float(share.get('diff', 0)),
                            accepted=share.get('accepted', True),
                            timestamp=share.get('time')
                        ))
        except Exception as e:
            print(f"Error getting shares from NerdMiner {ip}: {e}")
        return shares


class AvalonAdapter(MinerAdapter):
    """Adapter for Avalon miners (Nano, Q, etc.)"""

    def get_miner_type(self) -> str:
        return "avalon"

    async def detect(self, ip: str, timeout: float = 2.0) -> bool:
        """Detect Avalon miner"""
        try:
            async with httpx.AsyncClient() as client:
                # Avalon web interface
                response = await client.get(f"http://{ip}:80/", timeout=timeout)
                return "avalon" in response.text.lower()
        except:
            pass

        # Try CGMiner API
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, 4028),
                timeout=timeout
            )
            writer.write(b'{"command":"version"}')
            await writer.drain()
            data = await asyncio.wait_for(reader.read(1024), timeout=timeout)
            writer.close()
            await writer.wait_closed()
            return b'avalon' in data.lower() or b'canaan' in data.lower()
        except:
            return False

    async def get_info(self, ip: str, port: int = 4028) -> Optional[MinerInfo]:
        """Get Avalon miner info via CGMiner API"""
        try:
            # Get summary - use separate connection for each command
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=5.0
            )

            writer.write(b'{"command":"summary"}')
            await writer.drain()
            data = await asyncio.wait_for(reader.read(8192), timeout=5.0)

            writer.close()
            await writer.wait_closed()

            summary = extract_clean_json(data)
            if not summary:
                print(f"Failed to parse summary JSON from {ip}")
                return None

            # Get pools - new connection
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=5.0
            )

            writer.write(b'{"command":"pools"}')
            await writer.drain()
            pool_data = await asyncio.wait_for(reader.read(8192), timeout=5.0)

            writer.close()
            await writer.wait_closed()

            pools = extract_clean_json(pool_data)

            # Extract info
            summary_data = summary.get('SUMMARY', [{}])[0]
            pool_info = pools.get('POOLS', [{}])[0] if pools and pools.get('POOLS') else {}

            return MinerInfo(
                miner_type=self.get_miner_type(),
                hashrate=float(summary_data.get('MHS av', 0)) * 1e6,  # Convert MH/s to H/s
                temperature=float(summary_data.get('Temperature', 0)),
                uptime=summary_data.get('Elapsed'),
                pool_url=pool_info.get('URL'),
                pool_user=pool_info.get('User'),
                status='online' if summary_data.get('MHS av', 0) > 0 else 'idle',
                raw_data={'summary': summary, 'pools': pools}
            )
        except Exception as e:
            print(f"Error getting Avalon info from {ip}: {e}")
            import traceback
            traceback.print_exc()
        return None

    async def get_recent_shares(self, ip: str, port: int = 4028, count: int = 10) -> List[ShareInfo]:
        """Get share statistics from Avalon CGMiner API"""
        shares = []
        try:
            # Connect to CGMiner API
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=5.0
            )

            # Get pool stats which includes share info
            writer.write(b'{"command":"pools"}')
            await writer.drain()
            data = await asyncio.wait_for(reader.read(8192), timeout=5.0)

            writer.close()
            await writer.wait_closed()

            pools_data = extract_clean_json(data)
            if not pools_data:
                return shares

            pools = pools_data.get('POOLS', [])
            for pool in pools[:1]:  # Only check first pool
                # CGMiner tracks accepted/rejected shares
                accepted = pool.get('Accepted', 0)
                rejected = pool.get('Rejected', 0)
                difficulty = pool.get('Pool Difficulty', pool.get('Difficulty Accepted', 0))

                # Store the current accepted share count as a pseudo-share
                # In real implementation, you'd track deltas between polls
                if accepted > 0:
                    shares.append(ShareInfo(
                        difficulty=float(difficulty),
                        worker_name=pool.get('User'),
                        accepted=True,
                        timestamp=None
                    ))

        except Exception as e:
            print(f"Error getting Avalon shares from {ip}: {e}")

        return shares


class AntminerAdapter(MinerAdapter):
    """Adapter for Bitmain Antminer series"""

    def get_miner_type(self) -> str:
        return "antminer"

    async def detect(self, ip: str, timeout: float = 2.0) -> bool:
        """Detect Antminer"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://{ip}:80/", timeout=timeout)
                return "antminer" in response.text.lower() or "bitmain" in response.text.lower()
        except:
            return False

    async def get_info(self, ip: str, port: int = 4028) -> Optional[MinerInfo]:
        """Get Antminer info via CGMiner API (similar to Avalon)"""
        try:
            # Get summary - separate connection
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=5.0
            )

            writer.write(b'{"command":"summary"}')
            await writer.drain()
            data = await asyncio.wait_for(reader.read(8192), timeout=5.0)

            writer.close()
            await writer.wait_closed()

            summary = extract_clean_json(data)
            if not summary:
                print(f"Failed to parse summary JSON from {ip}")
                return None

            # Get pools - new connection
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=5.0
            )

            writer.write(b'{"command":"pools"}')
            await writer.drain()
            pool_data = await asyncio.wait_for(reader.read(8192), timeout=5.0)

            writer.close()
            await writer.wait_closed()

            pools = extract_clean_json(pool_data)

            summary_data = summary.get('SUMMARY', [{}])[0]
            pool_info = pools.get('POOLS', [{}])[0] if pools and pools.get('POOLS') else {}

            return MinerInfo(
                miner_type=self.get_miner_type(),
                hashrate=float(summary_data.get('GHS av', 0)) * 1e9,  # Convert GH/s to H/s
                temperature=float(summary_data.get('Temperature', 0)),
                uptime=summary_data.get('Elapsed'),
                pool_url=pool_info.get('URL'),
                pool_user=pool_info.get('User'),
                status='online' if summary_data.get('GHS av', 0) > 0 else 'idle',
                raw_data={'summary': summary, 'pools': pools}
            )
        except Exception as e:
            print(f"Error getting Antminer info from {ip}: {e}")
            import traceback
            traceback.print_exc()
        return None

    async def get_recent_shares(self, ip: str, port: int = 4028, count: int = 10) -> List[ShareInfo]:
        """Antminer doesn't expose per-share data via API"""
        return []


class GenericCGMinerAdapter(MinerAdapter):
    """Generic adapter for any CGMiner-compatible miner"""

    def get_miner_type(self) -> str:
        return "cgminer"

    async def detect(self, ip: str, timeout: float = 2.0) -> bool:
        """Detect CGMiner API"""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, 4028),
                timeout=timeout
            )
            writer.write(b'{"command":"version"}')
            await writer.drain()
            data = await asyncio.wait_for(reader.read(1024), timeout=timeout)
            writer.close()
            await writer.wait_closed()
            return b'cgminer' in data.lower() or b'bfgminer' in data.lower()
        except:
            return False

    async def get_info(self, ip: str, port: int = 4028) -> Optional[MinerInfo]:
        """Get info from CGMiner API"""
        try:
            # Get summary - separate connection
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=5.0
            )

            writer.write(b'{"command":"summary"}')
            await writer.drain()
            data = await asyncio.wait_for(reader.read(8192), timeout=5.0)

            writer.close()
            await writer.wait_closed()

            summary = extract_clean_json(data)
            if not summary:
                print(f"Failed to parse summary JSON from {ip}")
                return None

            # Get pools - new connection
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=5.0
            )

            writer.write(b'{"command":"pools"}')
            await writer.drain()
            pool_data = await asyncio.wait_for(reader.read(8192), timeout=5.0)

            writer.close()
            await writer.wait_closed()

            pools = extract_clean_json(pool_data)

            summary_data = summary.get('SUMMARY', [{}])[0]
            pool_info = pools.get('POOLS', [{}])[0] if pools and pools.get('POOLS') else {}

            # Try different hashrate fields
            hashrate = 0
            for field in ['GHS av', 'MHS av', 'KHS av']:
                if field in summary_data:
                    multiplier = {'GHS av': 1e9, 'MHS av': 1e6, 'KHS av': 1e3}[field]
                    hashrate = float(summary_data[field]) * multiplier
                    break

            return MinerInfo(
                miner_type=self.get_miner_type(),
                hashrate=hashrate,
                uptime=summary_data.get('Elapsed'),
                pool_url=pool_info.get('URL'),
                pool_user=pool_info.get('User'),
                status='online' if hashrate > 0 else 'idle',
                raw_data={'summary': summary, 'pools': pools}
            )
        except Exception as e:
            print(f"Error getting CGMiner info from {ip}: {e}")
            import traceback
            traceback.print_exc()
        return None

    async def get_recent_shares(self, ip: str, port: int = 4028, count: int = 10) -> List[ShareInfo]:
        """CGMiner doesn't expose per-share history"""
        return []


# Miner adapter registry
MINER_ADAPTERS = {
    "nerdminer": NerdMinerAdapter(),
    "avalon": AvalonAdapter(),
    "antminer": AntminerAdapter(),
    "cgminer": GenericCGMinerAdapter(),
}


def get_miner_adapter(miner_type: str) -> Optional[MinerAdapter]:
    """Get a miner adapter by type"""
    return MINER_ADAPTERS.get(miner_type)


async def detect_miner_type(ip: str) -> Optional[str]:
    """Try to detect what type of miner is at an IP address"""
    # Try specific adapters first
    for miner_type in ["nerdminer", "avalon", "antminer"]:
        adapter = MINER_ADAPTERS[miner_type]
        if await adapter.detect(ip):
            return miner_type

    # Fall back to generic CGMiner
    adapter = MINER_ADAPTERS["cgminer"]
    if await adapter.detect(ip):
        return "cgminer"

    return None


def list_miner_types() -> List[Dict[str, str]]:
    """List all supported miner types"""
    return [
        {"type": "nerdminer", "name": "NerdMiner"},
        {"type": "avalon", "name": "Avalon (Nano/Q)"},
        {"type": "antminer", "name": "Bitmain Antminer"},
        {"type": "cgminer", "name": "Generic CGMiner"},
    ]
