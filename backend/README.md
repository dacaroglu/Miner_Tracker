# ⛏️ Mining Dashboard v2.0

A flexible, multi-pool, multi-wallet cryptocurrency mining dashboard with historical tracking and pool adapter architecture.

## What's New in v2.0

- **Multi-Wallet Support**: Track unlimited wallets across different pools
- **Pool Adapter System**: Easy-to-extend architecture for adding new mining pools
- **Wallet Management UI**: Add/remove wallets directly from the dashboard
- **Enhanced Database**: SQLite storage with wallet tracking and historical data
- **More Pools**: Support for CKPool, 2Miners Solo, and 2Miners Regular pools
- **Multiple Coins**: BTC, BCH, ETH, RVN and easy to add more

## Features

- 📊 Real-time hashrate monitoring across all wallets
- 👷 Per-worker statistics and status
- 🎯 Best share difficulty tracking
- 💰 Balance and payout tracking
- 🔄 Auto-refresh every 60 seconds
- 📱 Responsive dark-mode UI
- 🗄️ Historical data storage in SQLite
- 🔌 RESTful API for external integrations
- 🧩 Modular pool adapter system

## Quick Start

### 1. Install dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install packages
pip install -r requirements.txt
```

### 2. Run the dashboard

```bash
# Development mode (auto-reload)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Production mode
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 3. Add your wallets

1. Open http://localhost:8000 in your browser
2. Click "Add Wallet" button
3. Fill in:
   - **Name**: Friendly name (e.g., "My BTC Solo Mining")
   - **Pool Adapter**: Select from dropdown (e.g., "Solo CKPool (BTC)")
   - **Address**: Your wallet address
4. Click "Add Wallet"

That's it! The dashboard will start tracking your mining stats automatically.

## Supported Pools

| Pool | Coins | Adapter Key |
|------|-------|-------------|
| Solo CKPool | BTC | `ckpool_btc` |
| 2Miners Solo | BTC, BCH | `2miners_solo_btc`, `2miners_solo_bch` |
| 2Miners Regular | BTC, BCH, ETH, RVN | `2miners_btc`, `2miners_bch`, `2miners_eth`, `2miners_rvn` |

## API Endpoints

### Wallet Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/wallets` | GET | List all tracked wallets |
| `/api/wallets` | POST | Add a new wallet |
| `/api/wallets/{id}` | GET | Get specific wallet |
| `/api/wallets/{id}` | PATCH | Update wallet (name, enabled) |
| `/api/wallets/{id}` | DELETE | Delete wallet |

### Pool Information

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/pools` | GET | List available pool adapters |

### Stats

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stats` | GET | Get all current stats |
| `/api/wallet/{id}/stats` | GET | Get stats for specific wallet |
| `/api/wallet/{id}/history` | GET | Get historical data |
| `/api/refresh` | GET | Force refresh all stats |

### Example: Add Wallet via API

```bash
curl -X POST http://localhost:8000/api/wallets \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My BTC Wallet",
    "address": "bc1qyouraddress...",
    "pool_adapter": "ckpool_btc"
  }'
```

## Project Structure

```
mining-dashboard/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application & routes
│   ├── pool_adapters.py     # Pool adapter implementations
│   ├── database.py          # SQLite database operations
│   ├── static/              # Static files
│   └── templates/
│       └── dashboard.html   # Frontend UI
├── mining_data.db           # SQLite database (auto-created)
├── .env                     # Optional configuration
├── requirements.txt         # Python dependencies
└── README.md
```

## Adding New Pool Adapters

To add support for a new mining pool:

### 1. Create Adapter Class

Edit `app/pool_adapters.py` and add a new class:

```python
class MyNewPoolAdapter(PoolAdapter):
    def __init__(self):
        super().__init__(coin="BTC")  # Set the coin

    def get_pool_name(self) -> str:
        return "My Pool Name"

    def validate_address(self, address: str) -> bool:
        # Validate address format for this pool
        return address.startswith('bc1')

    async def fetch_stats(self, client: httpx.AsyncClient, address: str) -> Optional[PoolStats]:
        # Fetch stats from the pool's API
        url = f"https://api.mypool.com/stats/{address}"
        response = await client.get(url, timeout=15.0)
        data = response.json()

        # Parse and return PoolStats
        return PoolStats(
            pool_name=self.get_pool_name(),
            coin=self.coin,
            address=address,
            hashrate=data['hashrate'],
            # ... map other fields
        )
```

### 2. Register Adapter

Add to the `POOL_ADAPTERS` dictionary:

```python
POOL_ADAPTERS = {
    # ... existing adapters
    "my_new_pool": MyNewPoolAdapter,
}
```

That's it! The new pool will appear in the "Add Wallet" dropdown.

## Configuration

Create a `.env` file for custom settings:

```env
REFRESH_INTERVAL=60  # Stats refresh interval in seconds (default: 60)
```

## Database

The application uses SQLite (`mining_data.db`) to store:

- **Wallets**: Configuration for each tracked wallet
- **Pool Snapshots**: Periodic captures of pool statistics
- **Worker Snapshots**: Per-worker performance history
- **Best Shares**: Historical record of best shares found

### Database Schema

```sql
wallets (id, name, address, pool_adapter, coin, enabled, created_at)
pool_snapshots (id, wallet_id, timestamp, hashrate, workers, balance, ...)
worker_snapshots (id, wallet_id, timestamp, worker_name, hashrate, ...)
best_shares (id, wallet_id, timestamp, difficulty, is_best_ever)
```

## Migration from v1.0

If you're upgrading from v1.0 (which used `.env` for addresses):

1. Start the new version
2. Use the UI to add your wallets manually
3. The new system is much more flexible!

Old `.env` variables (`CKPOOL_BTC_ADDRESS`, `TWOMINERS_BCH_ADDRESS`) are no longer used.

## Running with Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t mining-dashboard .
docker run -p 8000:8000 -v $(pwd)/mining_data.db:/app/mining_data.db mining-dashboard
```

## Running as a Service (systemd)

Create `/etc/systemd/system/mining-dashboard.service`:

```ini
[Unit]
Description=Mining Dashboard v2.0
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/mining-dashboard
Environment=PATH=/path/to/mining-dashboard/venv/bin
ExecStart=/path/to/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable mining-dashboard
sudo systemctl start mining-dashboard
```

## Architecture Overview

The v2.0 architecture is designed for flexibility:

```
┌─────────────┐
│  Dashboard  │ ← Frontend UI (Jinja2 + Tailwind)
│    (HTML)   │
└──────┬──────┘
       │
┌──────▼──────┐
│  FastAPI    │ ← REST API & Business Logic
│   Routes    │
└──────┬──────┘
       │
   ┌───┴────┬────────┬──────────┐
   │        │        │          │
┌──▼──┐ ┌──▼──┐ ┌──▼──┐    ┌──▼──┐
│CKPool│ │2Miners│ │Pool3│ ... │PoolN│ ← Pool Adapters
└──┬──┘ └──┬──┘ └──┬──┘    └──┬──┘
   │        │        │          │
   └────────┴────────┴──────────┘
              │
        ┌─────▼─────┐
        │  SQLite   │ ← Data Storage
        │ Database  │
        └───────────┘
```

### Key Components

1. **Pool Adapters**: Standardized interface for different pools
2. **Database Layer**: Wallet configs + historical data
3. **API Layer**: RESTful endpoints for all operations
4. **Frontend**: Modern responsive UI with wallet management

## Understanding the Data

### Solo Mining (CKPool, 2Miners Solo)

- **Hashrate**: Your current mining speed
- **Best Share**: Highest difficulty share found
- **Best Ever**: All-time highest share
- **Progress**: Best share vs network difficulty (100% = block found!)

### Pool Mining (2Miners Regular)

- **Hashrate**: Current and average hashrate
- **Balance**: Unpaid coins waiting for payout
- **Paid**: Total coins paid out to your address

## Troubleshooting

### "No wallets tracked yet"
- Click "Add Wallet" to add your first wallet

### "Error: Unknown pool adapter"
- Make sure you selected a pool from the dropdown
- Check `app/pool_adapters.py` for available adapters

### "Error: Invalid address format"
- Verify your wallet address is correct for the selected pool
- BTC: Should start with 1, 3, or bc1
- BCH: Can be legacy or bitcoincash: format

### Stats not updating
- Check your internet connection
- Verify the wallet address is correct
- Check if the pool's API is accessible

## Contributing

To add support for new pools:

1. Implement a new `PoolAdapter` class
2. Register it in `POOL_ADAPTERS`
3. Test with your wallet address
4. Submit a pull request!

## License

MIT

## Version History

- **v2.0.0** (2025-01): Complete rewrite with multi-wallet support and pool adapters
- **v1.0.0** (2024): Initial release with CKPool and 2Miners BCH support
#   M i n e r _ T r a c k e r  
 