# Share Tracking Guide

The mining dashboard now includes detailed share tracking capabilities to help you monitor your mining performance beyond what pool APIs provide.

## Features

- **Share Submission Logging**: Track every share you submit with its difficulty
- **Acceptance Rate**: Monitor accepted vs rejected shares
- **Difficulty Analysis**: See your average share difficulty and best shares
- **Performance Metrics**: Analyze share patterns over time

## How It Works

### Automatic Tracking (CKPool)

CKPool provides best share information directly from their API:
- Best share in current session
- Best share ever found
- Automatically displayed on the dashboard

### Manual Share Logging (2Miners & Others)

For pools like 2Miners that don't expose per-share difficulty, you can manually log shares using the API.

## Manual Share Logging

### Method 1: API Endpoint

Log shares using the REST API:

```bash
curl -X POST http://localhost:8000/api/wallet/{wallet_id}/shares \
  -H "Content-Type: application/json" \
  -d '{
    "pool_name": "2Miners Solo BCH",
    "difficulty": 1234567.89,
    "worker_name": "worker1",
    "accepted": true
  }'
```

### Method 2: Mining Software Integration

You can integrate this with your mining software's API or logs:

#### Example with a Python Script

```python
import requests
import re
import time

WALLET_ID = 1  # Your wallet ID from dashboard
DASHBOARD_URL = "http://localhost:8000"

def parse_miner_log(log_line):
    """Parse share difficulty from miner log"""
    # Example for bfgminer/cgminer format
    match = re.search(r'Share difficulty: ([\d.]+)', log_line)
    if match:
        return float(match.group(1))
    return None

def log_share(difficulty, worker="worker1", accepted=True):
    """Send share to dashboard"""
    data = {
        "pool_name": "2Miners Solo BCH",
        "difficulty": difficulty,
        "worker_name": worker,
        "accepted": accepted
    }

    try:
        response = requests.post(
            f"{DASHBOARD_URL}/api/wallet/{WALLET_ID}/shares",
            json=data,
            timeout=5
        )
        if response.ok:
            print(f"Logged share: {difficulty:.2e}")
    except Exception as e:
        print(f"Failed to log share: {e}")

# Monitor your miner log file
with open('/path/to/miner.log', 'r') as f:
    f.seek(0, 2)  # Go to end of file
    while True:
        line = f.readline()
        if not line:
            time.sleep(0.1)
            continue

        difficulty = parse_miner_log(line)
        if difficulty:
            log_share(difficulty)
```

### Method 3: Webhook from Mining Pool

Some pools support webhooks. Configure the pool to POST to:
```
http://your-dashboard:8000/api/wallet/{wallet_id}/shares
```

## Viewing Share Statistics

### Via Dashboard

Share statistics are automatically calculated and displayed for each wallet:
- Total shares submitted (last 24h)
- Best share difficulty
- Progress toward block (for solo mining)

### Via API

Get detailed share statistics:

```bash
# Get recent shares
curl http://localhost:8000/api/wallet/1/shares?hours=24&limit=100

# Get share statistics
curl http://localhost:8000/api/wallet/1/share-stats?hours=24
```

Response:
```json
{
  "total_shares": 1250,
  "accepted_shares": 1248,
  "rejected_shares": 2,
  "best_share": 1234567890.12,
  "avg_difficulty": 123456.78
}
```

## Mining Software Examples

### BFGMiner/CGMiner

Monitor the API:
```bash
# Get stats from miner
echo -n '{"command":"summary"}' | nc localhost 4028

# Parse and extract share info
# Then POST to dashboard API
```

### bmminer (Antminer)

Read from system logs:
```bash
tail -f /var/log/log | while read line; do
    # Extract share difficulty
    # POST to dashboard API
done
```

### Custom Stratum Proxy

Create a stratum proxy that:
1. Forwards mining requests to the pool
2. Intercepts share submissions
3. Logs difficulty to the dashboard API
4. Returns pool response to miner

## Best Practices

1. **Log Immediately**: Log shares as soon as they're submitted for accurate timestamps
2. **Include Worker Names**: Track which workers find best shares
3. **Log Rejections**: Track rejected shares to monitor for issues
4. **Set Reasonable Intervals**: Don't flood the API - batch if needed
5. **Monitor Storage**: The database grows with share logs - clean up old data periodically

## Database Maintenance

Share submissions are stored indefinitely. To prevent database bloat:

```python
# Add to your maintenance script
from app import database as db

# Keep only last 30 days of share submissions
db.cleanup_old_data(days=30)
```

## Understanding Share Difficulty

### What is Share Difficulty?

Share difficulty represents how hard it was to find that share. Higher difficulty = rarer/better share.

- **Solo Mining**: You need a share with difficulty >= network difficulty to find a block
- **Pool Mining**: Shares with any difficulty contribute to rewards

### Example Difficulties (Bitcoin)

- Pool minimum: ~1,000 - 100,000
- Good share: 1,000,000 - 10,000,000
- Great share: 100,000,000+
- Network difficulty: ~60,000,000,000,000 (60 trillion)

When your best share reaches 100% of network difficulty, you've found a block!

## Troubleshooting

### "Wallet not found"
Make sure the wallet_id in your API calls matches an existing wallet in the dashboard.

### Shares not appearing
- Check API response for errors
- Verify the pool_name matches exactly (case-sensitive)
- Check database file permissions

### Database growing too large
Run cleanup periodically or adjust retention period in your needs.

## Advanced: Real-time Share Monitoring

For real-time share visualization, you could:

1. **WebSocket Updates**: Modify the dashboard to use WebSockets for live share updates
2. **Share Rate Graphs**: Plot shares/minute to monitor performance
3. **Difficulty Distribution**: Histogram showing share difficulty ranges
4. **Luck Calculation**: Compare expected vs actual shares for your hashrate

These features can be added as enhancements to the dashboard!
