#!/usr/bin/env python3

import json
from scapy.all import PcapReader, IP, TCP, ICMP

def diagnose_pcaps(folder_path):
    """Diagnose what's in the PCAP files to understand why SSH detection isn't working"""

    import glob
    import os

    files = sorted(glob.glob(os.path.join(folder_path, "*.pcap")))

    if not files:
        print("No PCAP files found")
        return

    print(f"Found {len(files)} PCAP files")

    # IP configuration from analyzer
    SERVER_IP = "172.31.0.10"       # Server in network B
    COMPROMISED_IP = "172.30.0.10"  # Compromised host in network A

    packet_stats = {
        'total_packets': 0,
        'ip_packets': 0,
        'tcp_packets': 0,
        'ssh_port_22_packets': 0,
        'packets_from_compromised': 0,
        'packets_to_server': 0,
        'packets_from_server': 0,
        'ssh_payload_packets': 0,
        'sample_packets': []
    }

    for file_path in files:
        print(f"\nAnalyzing: {os.path.basename(file_path)}")

        try:
            with PcapReader(file_path) as packets:
                for i, pkt in enumerate(packets):
                    packet_stats['total_packets'] += 1

                    if not pkt.haslayer(IP):
                        continue

                    packet_stats['ip_packets'] += 1
                    ip = pkt[IP]
                    tcp = pkt[TCP] if pkt.haslayer(TCP) else None

                    # Track packet flows
                    if ip.src == COMPROMISED_IP:
                        packet_stats['packets_from_compromised'] += 1
                    if ip.dst == SERVER_IP:
                        packet_stats['packets_to_server'] += 1
                    if ip.src == SERVER_IP:
                        packet_stats['packets_from_server'] += 1

                    if tcp:
                        packet_stats['tcp_packets'] += 1

                        # Check for SSH port 22
                        if tcp.sport == 22 or tcp.dport == 22:
                            packet_stats['ssh_port_22_packets'] += 1

                            # Check for SSH payload
                            if tcp.payload and len(tcp.payload) > 0:
                                packet_stats['ssh_payload_packets'] += 1

                                # Save sample packet info
                                if len(packet_stats['sample_packets']) < 5:
                                    payload_bytes = bytes(tcp.payload)
                                    packet_stats['sample_packets'].append({
                                        'src': ip.src,
                                        'dst': ip.dst,
                                        'sport': tcp.sport,
                                        'dport': tcp.dport,
                                        'flags': int(tcp.flags),
                                        'payload_size': len(payload_bytes),
                                        'payload_start': payload_bytes[:50].hex(),
                                        'has_ssh_string': b'SSH-' in payload_bytes,
                                        'ascii_preview': payload_bytes[:50].decode('ascii', errors='ignore')
                                    })

                    # Stop after processing some packets for debugging
                    if i > 200:
                        break

        except Exception as e:
            print(f"Error reading {file_path}: {e}")

    print(f"\n{'='*60}")
    print("PACKET STATISTICS")
    print(f"{'='*60}")
    for key, value in packet_stats.items():
        if key != 'sample_packets':
            print(f"{key}: {value}")

    print(f"\n{'='*60}")
    print("SSH PORT 22 SAMPLE PACKETS")
    print(f"{'='*60}")
    for i, pkt in enumerate(packet_stats['sample_packets']):
        print(f"\nSample {i+1}:")
        print(f"  {pkt['src']}:{pkt['sport']} -> {pkt['dst']}:{pkt['dport']}")
        print(f"  Flags: {pkt['flags']}")
        print(f"  Payload size: {pkt['payload_size']}")
        print(f"  Has SSH string: {pkt['has_ssh_string']}")
        print(f"  ASCII preview: {repr(pkt['ascii_preview'])}")
        print(f"  Hex start: {pkt['payload_start']}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python3 diagnose_pcap.py <pcap_folder>")
        sys.exit(1)

    diagnose_pcaps(sys.argv[1])