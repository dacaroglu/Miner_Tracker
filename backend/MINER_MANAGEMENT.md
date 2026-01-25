# Miner Management System

The dashboard now includes comprehensive miner device management with automatic discovery, pool detection, and share tracking.

## Overview

The miner management system provides:

- **Network Scanning**: Auto-discover miners on your local network
- **Miner Adapters**: Support for NerdMiner, Avalon (Nano/Q), Antminer, and generic CGMiner
- **Auto-Matching**: Automatically link miners to tracked wallets based on pool configuration
- **Real-time Monitoring**: Poll miners for hashrate, temperature, and share data
- **Share Tracking**: Automatic share submission logging from supported miners

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                 Mining Dashboard                         │
├─────────────────────────────────────────────────────────┤
│  1. Network Scanner                                      │
│     └─> Discovers miners on LAN                         │
│                                                          │
│  2. Miner Adapters                                       │
│     ├─> NerdMiner (HTTP API)                           │
│     ├─> Avalon Nano/Q (CGMiner API)                    │
│     ├─> Antminer (CGMiner API)                         │
│     └─> Generic CGMiner                                 │
│                                                          │
│  3. Auto-Matching Engine                                 │
│     └─> Links Miners ──> Wallets                        │
│                                                          │
│  4. Real-time Polling                                    │
│     └─> Fetches shares every 30s                        │
└─────────────────────────────────────────────────────────┘
```

## Supported Miners

| Miner Type | Manufacturer | API | Auto-Discovery | Share Tracking |
|------------|--------------|-----|----------------|----------------|
| NerdMiner | Community | HTTP | ✅ | ✅ |
| Avalon Nano | Canaan | CGMiner | ✅ | ⚠️ Limited |
| Avalon Q | Canaan | CGMiner | ✅ | ⚠️ Limited |
| Antminer | Bitmain | CGMiner | ✅ | ⚠️ Limited |
| Generic | Various | CGMiner | ✅ | ❌ |

**Note**: CGMiner-based miners (Avalon, Antminer) don't expose per-share data via their API. For detailed share tracking on these devices, you'll need to parse log files or use a stratum proxy.

## Quick Start

### 1. Scan Your Network

Use the API to scan for miners:

```bash
curl -X POST http://localhost:8000/api/miners/scan
```

This will:
- Scan your local network (auto-detects network range)
- Identify miner types
- Read pool configurations
- Auto-match miners to wallets

### 2. View Discovered Miners

```bash
curl http://localhost:8000/api/miners
```

### 3. Check Miner Details

```bash
curl http://localhost:8000/api/miners/1/info
```

Gets live data:
- Current hashrate
- Temperature
- Pool configuration
- Worker name
- Status

## Auto-Matching Logic

The system automatically links miners to wallets by:

1. **Reading Pool Configuration** from the miner
2. **Extracting Wallet Address** from the pool user field (format: `wallet.worker`)
3. **Matching Pool Domain** to tracked pool adapters
4. **Creating Link** between miner and wallet

Example:
```
Miner Config:
  Pool URL: stratum+tcp://solo.ckpool.org:3333
  User: bc1qyouraddress.nerdminer01

Dashboard Wallet:
  Address: bc1qyouraddress
  Pool: Solo CKPool (ckpool_btc)

→ Auto-matched! ✅
```

## API Endpoints

### Miner Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/miners` | GET | List all miners |
| `/api/miners` | POST | Manually add a miner |
| `/api/miners/{id}` | GET | Get miner details |
| `/api/miners/{id}` | PATCH | Update miner |
| `/api/miners/{id}` | DELETE | Delete miner |
| `/api/miners/{id}/info` | GET | Get live miner status |
| `/api/miners/{id}/configs` | GET | Get miner configurations |
| `/api/miners/{id}/link-wallet` | POST | Link miner to wallet |
| `/api/miners/scan` | POST | Scan network for miners |
| `/api/miner-types` | GET | List supported miner types |

### Examples

**Scan Network:**
```bash
curl -X POST http://localhost:8000/api/miners/scan
```

**Get Live Miner Info:**
```bash
curl http://localhost:8000/api/miners/1/info
```

Response:
```json
{
  "miner_type": "nerdminer",
  "firmware_version": "v2.1.0",
  "hashrate": 50000000000,
  "temperature": 45.2,
  "pool_url": "stratum+tcp://solo.ckpool.org:3333",
  "pool_user": "bc1qyouraddress.nerdminer01",
  "status": "online"
}
```

**Manually Add Miner:**
```bash
curl -X POST http://localhost:8000/api/miners \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Avalon Nano",
    "miner_type": "avalon",
    "ip_address": "192.168.1.100",
    "api_port": 4028
  }'
```

**Link Miner to Wallet:**
```bash
curl -X POST "http://localhost:8000/api/miners/1/link-wallet?wallet_id=1"
```

## Network Scanning

### Automatic Network Detection

The scanner automatically detects your local network:

```python
# Detects your LAN (e.g., 192.168.1.0/24)
# Scans all hosts in parallel
# Identifies miner types
# Saves to database
```

### Manual Network Specification

You can specify a custom network range:

```python
from app.network_scanner import scan_network

miners = await scan_network(network_cidr="192.168.0.0/24")
```

### Scanning Process

1. **Ping Check**: Verifies host is reachable
2. **Port Detection**: Tries common miner ports (80, 4028)
3. **Type Detection**: Identifies miner manufacturer/type
4. **Info Retrieval**: Fetches current status and configuration
5. **Database Storage**: Saves miner details
6. **Auto-Matching**: Links to wallets if possible

## Miner Adapters

### Adding Custom Miner Types

To support a new miner type, create an adapter in `app/miner_adapters.py`:

```python
class MyMinerAdapter(MinerAdapter):
    def get_miner_type(self) -> str:
        return "my_miner"

    async def detect(self, ip: str, timeout: float = 2.0) -> bool:
        # Detection logic
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://{ip}:80/", timeout=timeout)
                return "my_miner" in response.text.lower()
        except:
            return False

    async def get_info(self, ip: str, port: int = None) -> Optional[MinerInfo]:
        # Fetch miner info
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://{ip}:{port}/api/status")
                data = response.json()

                return MinerInfo(
                    miner_type=self.get_miner_type(),
                    hashrate=data['hashrate'],
                    temperature=data['temp'],
                    pool_url=data['pool'],
                    pool_user=data['user'],
                    status='online'
                )
        except:
            return None

    async def get_recent_shares(self, ip: str, port: int = None, count: int = 10) -> List[ShareInfo]:
        # Get recent shares if supported
        return []
```

Register the adapter:

```python
MINER_ADAPTERS = {
    # ... existing adapters
    "my_miner": MyMinerAdapter(),
}
```

## Real-time Share Tracking

### Automatic Polling

The system automatically polls miners every 30 seconds for:
- Share submissions
- Hashrate updates
- Temperature monitoring
- Status changes

### Manual Share Logging

For miners that don't support automatic share retrieval:

```bash
curl -X POST http://localhost:8000/api/wallet/1/shares \
  -H "Content-Type: application/json" \
  -d '{
    "pool_name": "Solo CKPool",
    "difficulty": 1234567890.12,
    "worker_name": "avalon_nano_01",
    "accepted": true
  }'
```

## Dashboard Integration

### Viewing Miner Data

Miners linked to wallets will appear in the dashboard:

- **Miner Status**: Online/Offline indicators
- **Live Hashrate**: Real-time from device
- **Share Statistics**: Accepted/rejected rates
- **Temperature**: Device temperature monitoring
- **Auto-sync**: Updates every 30 seconds

### Combined View

The dashboard shows:
- All tracked wallets with pool stats
- Linked miners with live device data
- Combined hashrate across all devices
- Share submission history

## Troubleshooting

### "No miners found during scan"

**Solutions:**
- Ensure miners are powered on and connected to network
- Check that you're on the same subnet as the miners
- Verify miner web interface is accessible
- Check firewall settings (allow ports 80, 4028)

### "Miner detected but auto-match failed"

**Causes:**
- Wallet address format doesn't match
- Pool URL domain not recognized
- Worker name parsing failed

**Manual Fix:**
```bash
curl -X POST "http://localhost:8000/api/miners/1/link-wallet?wallet_id=1"
```

### "Share tracking not working"

**For NerdMiner**: Should work automatically if API is enabled

**For Avalon/Antminer**:
- Automatic share tracking is limited (CGMiner API doesn't expose per-share data)
- Use manual share logging
- Consider setting up a stratum proxy for detailed tracking

### "Miner status shows 'offline'"

**Check:**
1. Miner is powered on
2. Network connection is stable
3. IP address hasn't changed (use DHCP reservation)
4. Miner API is enabled and accessible

## Advanced Configuration

### Scheduled Network Scans

Add to your scheduler (e.g., cron):

```bash
# Scan every hour
0 * * * * curl -X POST http://localhost:8000/api/miners/scan
```

### Miner Health Monitoring

```python
# Check all miners and alert if offline
miners = requests.get("http://localhost:8000/api/miners?enabled_only=true").json()

for miner in miners:
    if miner['status'] == 'offline':
        send_alert(f"Miner {miner['name']} is offline!")
```

### Performance Tracking

```python
# Get miner performance over time
configs = requests.get("http://localhost:8000/api/miners/1/configs").json()
shares = requests.get(f"http://localhost:8000/api/wallet/{wallet_id}/shares").json()

# Analyze share rate, rejection rate, etc.
```

## Database Schema

```sql
-- Miners table
miners (
  id, name, miner_type, ip_address, mac_address,
  api_port, status, enabled, auto_discovered,
  created_at, last_seen
)

-- Miner configurations (links to wallets)
miner_configs (
  id, miner_id, wallet_id, pool_url,
  worker_name, active, detected_at
)

-- Share submissions (enhanced with miner_id)
share_submissions (
  id, timestamp, wallet_id, miner_id,
  pool_name, worker_name, difficulty, accepted
)
```

## Best Practices

1. **Use DHCP Reservations**: Assign static IPs to miners to prevent IP changes
2. **Regular Scans**: Run network scans periodically to catch new devices
3. **Monitor Health**: Set up alerts for offline miners
4. **Backup Database**: Contains historical miner data and configurations
5. **Secure API Access**: Use authentication if exposing dashboard externally

## Example Workflow

### Initial Setup

1. **Add Wallets** - Add all your mining wallets to the dashboard
2. **Scan Network** - Run `POST /api/miners/scan`
3. **Verify Links** - Check that miners are auto-matched to wallets
4. **Manual Links** - Link any miners that weren't auto-matched

### Daily Operation

- Dashboard automatically polls miners every 30s
- Share data is logged automatically (for supported miners)
- Temperature and hashrate are updated in real-time
- Alerts trigger if miners go offline

### Maintenance

- Re-scan network after adding new miners
- Update miner names for clarity
- Disable miners that are no longer in use
- Archive historical data periodically

## Future Enhancements

Potential additions:
- Email/SMS alerts for offline miners
- Overclocking/underclocking control
- Power consumption tracking
- Profitability calculator
- Historical charts for temperature/hashrate
- Mobile app integration

## Support

For issues or feature requests, check the main [README.md](README.md) file.
