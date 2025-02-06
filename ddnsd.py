# **Development and Application of a Decentralized Domain Name Service**

#### Phi Lab Foundation
#### **info@philab.fund**

##### Version: 0.1 

import asyncio
import aiohttp
import socket
from dnslib import DNSRecord, RR, QTYPE, A, AAAA, CNAME, MX

# Configuration
LISTEN_ADDRESS = "127.0.0.1"  # Address to bind the DNS server
LISTEN_PORT = 5553            # Port to listen for DNS queries
FORWARD_DNS = "1.1.1.1"       # Fallback DNS server address
FORWARD_PORT = 53             # Fallback DNS server port

PHICOIN_RPC_URL = "http://127.0.0.1:28964/"  # PhiCoin RPC endpoint
RPC_USER = "phi"              # RPC username
RPC_PASSWORD = "phi"          # RPC password

DEFAULT_INVALID_HASHES = {
    "0000000000000000000000000000000000000000000000000000000000000000", # for domain names Initialization
    "Qm00000000000000000000000000000000000000000000" # for disabling flags of domain names
}


async def query_asset_data(asset_name):
    """
    Asynchronously query PhiCoin RPC to fetch asset data.
    """
    payload = {
        "jsonrpc": "1.0",
        "id": "dns-query",
        "method": "getassetdata",
        "params": [asset_name.upper()]
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                PHICOIN_RPC_URL,
                json=payload,
                auth=aiohttp.BasicAuth(RPC_USER, RPC_PASSWORD),
                headers={"Content-Type": "application/json"}
            ) as response:
                result = await response.json()
                print(f"RPC Response for {asset_name.upper()}: {result}")
                return result.get("result")
        except Exception as e:
            print(f"Error querying asset {asset_name.upper()}: {e}")
            return None


async def resolve_ipfs(ipfs_hash):
    """
    Asynchronously resolve data from IPFS using the given hash.
    """
    url = f"https://ipfs.io/ipfs/{ipfs_hash}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    record = await response.json()
                    print(f"Resolved IPFS {ipfs_hash}: {record}")
                    return record
        except Exception as e:
            print(f"Error resolving IPFS hash {ipfs_hash}: {e}")
    return None


def format_to_asset_name(domain):
    """
    Convert a .DDNS domain into the PhiCoin asset name format.
    """
    if not domain.endswith(".DDNS"):
        return None
    parts = domain[:-5].split(".")
    if len(parts) < 2:
        return None
    root_domain = "DDNS"
    top_level_domain = parts[-1].upper()
    subdomains = ".".join(part.upper() for part in parts[:-1])
    return f"{root_domain}/{top_level_domain}/{subdomains}"


async def handle_ddns(domain):
    """
    Handle .DDNS requests by resolving to PhiCoin assets.
    """
    asset_name = format_to_asset_name(domain.upper())
    if not asset_name:
        print(f"Invalid DDNS domain: {domain.upper()}")
        return None

    asset_data = await query_asset_data(asset_name)
    if not asset_data or asset_data.get("has_ipfs") != 1:
        return None

    ipfs_hash = asset_data.get("ipfs_hash")
    if not ipfs_hash or ipfs_hash in DEFAULT_INVALID_HASHES:
        return None

    return await resolve_ipfs(ipfs_hash)


async def forward_dns_request(data):
    """
    Asynchronously forward DNS requests to the fallback DNS server.
    """
    try:
        loop = asyncio.get_running_loop()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            await loop.sock_sendto(sock, data, (FORWARD_DNS, FORWARD_PORT))
            response = await loop.sock_recv(sock, 512)
            return response
    except Exception as e:
        print(f"Error forwarding DNS request: {e}")
        return None


class DNSProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self.loop = asyncio.get_event_loop()

    def connection_made(self, transport):
        self.transport = transport
        print(f"Listening on {LISTEN_ADDRESS}:{LISTEN_PORT}")

    def datagram_received(self, data, addr):
        print(f"Received DNS query from {addr}, raw data: {data}")
        self.loop.create_task(self.handle_request(data, addr))

    async def handle_request(self, data, addr):
        """
        Handle incoming DNS requests and send appropriate responses.
        """
        try:
            request = DNSRecord.parse(data)
            domain = str(request.q.qname)[:-1]
            qtype = QTYPE[request.q.qtype]
            print(f"Query for {domain.upper()} (Type: {qtype}) from client {addr}")

            if domain.upper().endswith(".DDNS"):
                record = await handle_ddns(domain.upper())
                if record:
                    reply = request.reply()
                    if record["Type"] == "A":
                        reply.add_answer(RR(domain.upper(), QTYPE.A, rdata=A(record["Address"])))
                    elif record["Type"] == "AAAA":
                        reply.add_answer(RR(domain.upper(), QTYPE.AAAA, rdata=AAAA(record["Address"])))
                    elif record["Type"] == "CNAME":
                        reply.add_answer(RR(domain.upper(), QTYPE.CNAME, rdata=CNAME(record["Target"])))
                    elif record["Type"] == "MX":
                        reply.add_answer(RR(domain.upper(), QTYPE.MX, ttl=record["TTL"], rdata=MX(record["MailServer"], record["Priority"])))
                    self.transport.sendto(reply.pack(), addr)
                    print(f"Replied with DDNS record for {domain.upper()} to {addr}")
                    return

            response = await forward_dns_request(data)
            if response:
                self.transport.sendto(response, addr)
                print(f"Forwarded response for {domain.upper()} to {addr}")
            else:
                print(f"Failed to forward DNS query for {domain.upper()}")
        except Exception as e:
            print(f"Error processing request from {addr}: {e}")


async def main():
    """
    Main entry point for starting the DNS server.
    """
    print("Starting DNS Server...")
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: DNSProtocol(),
        local_addr=(LISTEN_ADDRESS, LISTEN_PORT)
    )
    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        transport.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Server stopped.")
