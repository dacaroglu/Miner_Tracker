"""
Test script to debug miner detection
Run this to check what your miners actually return
"""

import asyncio
import httpx
import json


async def test_nerdminer(ip: str):
    """Test NerdMiner detection and API endpoints"""
    print(f"\n=== Testing NerdMiner at {ip} ===")

    async with httpx.AsyncClient() as client:
        # Test homepage
        print("\n1. Testing homepage (http://{ip}:80/):")
        try:
            response = await client.get(f"http://{ip}:80/", timeout=5.0)
            print(f"   Status: {response.status_code}")
            print(f"   Content preview: {response.text[:500]}")
            print(f"   Contains 'nerdminer': {'nerdminer' in response.text.lower()}")
            print(f"   Contains 'nerd miner': {'nerd miner' in response.text.lower()}")
        except Exception as e:
            print(f"   Error: {e}")

        # Test common API endpoints
        endpoints = [
            "/api/status",
            "/api/system/info",
            "/api",
            "/json",
            "/stats"
        ]

        for endpoint in endpoints:
            print(f"\n2. Testing endpoint: {endpoint}")
            try:
                response = await client.get(f"http://{ip}:80{endpoint}", timeout=5.0)
                print(f"   Status: {response.status_code}")
                if response.status_code == 200:
                    try:
                        data = response.json()
                        print(f"   JSON keys: {list(data.keys())}")
                        print(f"   Content: {json.dumps(data, indent=2)[:500]}")
                    except:
                        print(f"   Content (not JSON): {response.text[:200]}")
            except Exception as e:
                print(f"   Error: {e}")


async def test_avalon(ip: str):
    """Test Avalon CGMiner API"""
    print(f"\n=== Testing Avalon at {ip} ===")

    # Test web interface
    print("\n1. Testing web interface (http://{ip}:80/):")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"http://{ip}:80/", timeout=5.0)
            print(f"   Status: {response.status_code}")
            print(f"   Content preview: {response.text[:300]}")
        except Exception as e:
            print(f"   Error: {e}")

    # Test CGMiner API
    print("\n2. Testing CGMiner API (port 4028):")
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, 4028),
            timeout=5.0
        )

        # Send version command
        print("   Sending 'version' command...")
        writer.write(b'{"command":"version"}')
        await writer.drain()

        # Read response
        data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
        print(f"   Raw response: {data}")
        print(f"   Decoded: {data.decode('utf-8', errors='ignore')}")

        # Close and reopen for summary
        writer.close()
        await writer.wait_closed()

        # New connection for summary
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, 4028),
            timeout=5.0
        )

        print("\n   Sending 'summary' command...")
        writer.write(b'{"command":"summary"}')
        await writer.drain()

        data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
        print(f"   Raw response length: {len(data)}")

        # Try to parse as JSON
        try:
            # Remove null bytes
            cleaned = data.decode('utf-8').replace('\x00', '').strip()
            print(f"   Cleaned response: {cleaned[:500]}")

            # Try to parse
            parsed = json.loads(cleaned)
            print(f"   Parsed successfully!")
            print(f"   JSON structure: {json.dumps(parsed, indent=2)[:500]}")
        except json.JSONDecodeError as e:
            print(f"   JSON parse error: {e}")
            print(f"   Cleaned text: {cleaned[:500]}")

        writer.close()
        await writer.wait_closed()

    except Exception as e:
        print(f"   Error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    print("Miner Detection Test Tool")
    print("=" * 50)

    # Get IPs from user
    print("\nEnter IP addresses of your miners (or press Enter to skip):")

    nerdminer_ips = input("NerdMiner IPs (comma-separated): ").strip()
    avalon_ips = input("Avalon IPs (comma-separated): ").strip()

    # Test NerdMiners
    if nerdminer_ips:
        for ip in nerdminer_ips.split(','):
            ip = ip.strip()
            if ip:
                await test_nerdminer(ip)

    # Test Avalons
    if avalon_ips:
        for ip in avalon_ips.split(','):
            ip = ip.strip()
            if ip:
                await test_avalon(ip)

    print("\n" + "=" * 50)
    print("Testing complete!")
    print("\nPlease share the output so we can fix the adapters.")


if __name__ == "__main__":
    asyncio.run(main())
