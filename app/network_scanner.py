"""
Network Scanner - Discover mining devices on the local network
"""

import asyncio
import ipaddress
import socket
from typing import List, Dict, Optional
import httpx
from app.miner_adapters import detect_miner_type, get_miner_adapter, MINER_ADAPTERS
from app import database as db


async def ping_host(ip: str, timeout: float = 1.0) -> bool:
    """Check if a host is reachable"""
    try:
        # Try to connect to common miner ports
        for port in [80, 4028]:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port),
                    timeout=timeout
                )
                writer.close()
                await writer.wait_closed()
                return True
            except:
                continue
        return False
    except:
        return False


async def scan_host(ip: str) -> Optional[Dict]:
    """Scan a single host for mining devices"""
    # Check if host is up
    if not await ping_host(ip):
        return None

    print(f"[Scanner] Checking {ip}...")

    # Try to detect miner type
    miner_type = await detect_miner_type(ip)
    if not miner_type:
        return None

    print(f"[Scanner] Found {miner_type} at {ip}")

    # Get miner info
    adapter = get_miner_adapter(miner_type)
    if not adapter:
        return None

    info = await adapter.get_info(ip)
    if not info:
        return None

    return {
        "ip_address": ip,
        "miner_type": miner_type,
        "info": info,
        "adapter": adapter
    }


def get_local_network() -> str:
    """Get the local network CIDR"""
    try:
        # Get local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()

        # Assume /24 network
        network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
        return str(network)
    except:
        return "192.168.1.0/24"  # Default fallback


async def scan_network(network_cidr: str = None, timeout: float = 1.0) -> List[Dict]:
    """Scan network for mining devices"""
    if not network_cidr:
        network_cidr = get_local_network()

    print(f"[Scanner] Scanning network: {network_cidr}")

    network = ipaddress.IPv4Network(network_cidr, strict=False)
    hosts = [str(ip) for ip in network.hosts()]

    # Scan hosts in parallel (batches of 20)
    discovered = []
    batch_size = 20

    for i in range(0, len(hosts), batch_size):
        batch = hosts[i:i + batch_size]
        results = await asyncio.gather(*[scan_host(ip) for ip in batch])
        discovered.extend([r for r in results if r])

        # Progress update
        print(f"[Scanner] Progress: {min(i + batch_size, len(hosts))}/{len(hosts)} hosts scanned")

    return discovered


async def auto_match_wallet(miner_info: Dict, wallet_list: List[Dict]) -> Optional[int]:
    """Try to match a miner to a wallet based on pool configuration"""
    pool_url = miner_info['info'].pool_url
    pool_user = miner_info['info'].pool_user

    if not pool_url or not pool_user:
        return None

    # Extract wallet address from pool_user (usually wallet.worker format)
    adapter = miner_info['adapter']
    wallet_address, worker_name = adapter.extract_wallet_worker(pool_user)

    if not wallet_address:
        return None

    # Try to match with tracked wallets
    for wallet in wallet_list:
        # Check if wallet address matches
        if wallet_address.lower() in wallet['address'].lower():
            # Verify pool URL matches (at least the domain)
            # Extract domain from pool URL
            try:
                pool_domain = pool_url.split('//')[1].split('/')[0].split(':')[0]

                # Check common pool domains
                pool_matches = {
                    'solo.ckpool.org': 'ckpool_btc',
                    'solo-bch.2miners.com': '2miners_solo_bch',
                    'solo-btc.2miners.com': '2miners_solo_btc',
                    'bch.2miners.com': '2miners_bch',
                    'btc.2miners.com': '2miners_btc',
                }

                for domain, adapter_key in pool_matches.items():
                    if domain in pool_domain and wallet['pool_adapter'] == adapter_key:
                        return wallet['id']

            except:
                pass

    return None


async def discover_and_register_miners(save_to_db: bool = True) -> List[Dict]:
    """Discover miners and optionally save to database"""
    miners = await scan_network()

    if not save_to_db:
        return miners

    # Get existing wallets for auto-matching
    wallets = db.get_wallets(enabled_only=True)

    registered = []
    for miner in miners:
        # Add miner to database
        miner_name = f"{miner['miner_type']}_{miner['ip_address']}"

        miner_id = db.add_miner(
            name=miner_name,
            miner_type=miner['miner_type'],
            ip_address=miner['ip_address'],
            api_port=80 if miner['miner_type'] == 'nerdminer' else 4028,
            auto_discovered=True
        )

        if not miner_id:
            # Miner already exists, get its ID
            existing_miners = db.get_miners()
            for m in existing_miners:
                if m['ip_address'] == miner['ip_address']:
                    miner_id = m['id']
                    break

        if miner_id:
            # Try to auto-match with wallet
            wallet_id = await auto_match_wallet(miner, wallets)

            if wallet_id:
                # Create miner config linking it to wallet
                db.add_miner_config(
                    miner_id=miner_id,
                    wallet_id=wallet_id,
                    pool_url=miner['info'].pool_url,
                    worker_name=miner['info'].pool_user
                )
                print(f"[Scanner] Auto-matched miner {miner['ip_address']} to wallet ID {wallet_id}")
            else:
                # Save config without wallet link
                db.add_miner_config(
                    miner_id=miner_id,
                    pool_url=miner['info'].pool_url,
                    worker_name=miner['info'].pool_user
                )
                print(f"[Scanner] Registered miner {miner['ip_address']} (no wallet match)")

        registered.append({
            **miner,
            "miner_id": miner_id,
            "wallet_id": wallet_id if wallet_id else None
        })

    return registered


async def poll_miners_for_shares():
    """Poll all registered miners for share data (background task)"""
    # Track last seen share counts to detect new shares
    last_share_counts = {}

    while True:
        try:
            miners = db.get_miners(enabled_only=True)

            for miner in miners:
                adapter = get_miner_adapter(miner['miner_type'])
                if not adapter:
                    continue

                try:
                    # Get pool info which includes share counts
                    info = await adapter.get_info(
                        miner['ip_address'],
                        miner['api_port'] or (80 if miner['miner_type'] == 'nerdminer' else 4028)
                    )

                    if not info:
                        continue

                    # Get miner config to find wallet
                    configs = db.get_miner_configs(miner_id=miner['id'])
                    if not configs or not configs[0].get('wallet_id'):
                        continue

                    wallet_id = configs[0]['wallet_id']
                    pool_url = configs[0].get('pool_url', 'unknown')

                    # Extract share count from raw data
                    share_count = 0
                    difficulty = 0

                    if miner['miner_type'] in ['avalon', 'antminer', 'cgminer']:
                        # CGMiner-based miners
                        pools = info.raw_data.get('pools', {}).get('POOLS', [])
                        if pools:
                            share_count = pools[0].get('Accepted', 0)
                            difficulty = pools[0].get('Pool Difficulty', pools[0].get('Difficulty Accepted', 0))
                    elif miner['miner_type'] == 'nerdminer':
                        # NerdMiner/NerdAxe
                        stratum = info.raw_data.get('stratum', {})
                        pools = stratum.get('pools', [])
                        if pools:
                            share_count = pools[0].get('accepted', 0)
                            difficulty = pools[0].get('poolDifficulty', 0)

                    # Check if we have new shares
                    miner_key = f"{miner['id']}"
                    last_count = last_share_counts.get(miner_key, 0)

                    if share_count > last_count:
                        # New shares found!
                        new_shares = share_count - last_count
                        print(f"[Miner Poll] {miner['ip_address']} submitted {new_shares} new share(s), difficulty: {difficulty}")

                        # Log each new share
                        for _ in range(min(new_shares, 10)):  # Cap at 10 to avoid spam
                            db.log_share_submission(
                                wallet_id=wallet_id,
                                pool_name=pool_url,
                                difficulty=float(difficulty),
                                worker_name=info.pool_user,
                                accepted=True
                            )

                        last_share_counts[miner_key] = share_count

                    # Update miner status
                    db.update_miner(
                        miner['id'],
                        status='online' if info.status == 'online' else 'idle',
                        last_seen=db.datetime.utcnow()
                    )

                except Exception as e:
                    print(f"[Miner Poll] Error polling {miner['ip_address']}: {e}")

        except Exception as e:
            print(f"[Miner Poll] Error: {e}")
            import traceback
            traceback.print_exc()

        # Poll every 30 seconds
        await asyncio.sleep(30)


if __name__ == "__main__":
    # Test scanner
    print("Starting network scan...")
    miners = asyncio.run(discover_and_register_miners(save_to_db=False))

    print(f"\nDiscovered {len(miners)} miners:")
    for miner in miners:
        print(f"  - {miner['miner_type']} at {miner['ip_address']}")
        print(f"    Pool: {miner['info'].pool_url}")
        print(f"    User: {miner['info'].pool_user}")
        print(f"    Hashrate: {miner['info'].hashrate / 1e9:.2f} GH/s")
        print()
