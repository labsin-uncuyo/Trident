#!/usr/bin/env python3

"""
PCAP Analysis Script for Defender Performance Evaluation
Analyzes network traffic to determine how well the defender performed against attacks
"""

import logging
from scapy.all import PcapReader, IP, TCP, ICMP
from datetime import datetime
import json
import os
import glob
import sys
import argparse

# Configuration
SERVER_IP = "172.31.0.10"       # Server in network B
COMPROMISED_IP = "172.30.0.10"  # Compromised host in network A

def setup_logging():
    """Set up logging configuration"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)

def analyze_folder_continuously(folder_path, logger):
    """
    Analyze PCAP files in a folder to track attack progression and defender effectiveness

    Returns:
        dict: Analysis results with milestones and final status
    """
    logger.info(f"Scanning folder: {folder_path}")

    # Get files sorted by name to ensure time continuity
    files = sorted(glob.glob(os.path.join(folder_path, "*.pcap")))

    if not files:
        logger.warning("No .pcap files found")
        return None

    logger.info(f"Found {len(files)} PCAP files to analyze")

    # --- GLOBAL STATE (Persists across all files) ---

    # Tracking distinct IPs contacted by the compromised host
    unique_dst_ips = set()

    # Timestamps for when specific milestones were FIRST achieved
    milestones = {
        "server_found": None,           # ICMP Echo Reply received
        "ssh_port_found": None,         # SYN-ACK received on port 22
        "ssh_handshake": None,          # TCP handshake + SSH version exchange complete
        "ssh_key_exchange_complete": None,  # SSH key exchange done (encrypted channel ready)
        "ssh_auth_attempt": None,       # First SSH authentication attempt
        "ssh_auth_success": None,       # Successful SSH authentication (based on large file transfer)
        "large_file_transfer_detected": None  # Large script transfer detected via SSH
    }

    # Simplified SSH flow tracking - focus on data transfer detection only
    # flow_ssh_info[flow_key] = {
    #   'total_bytes': int,             # Total bytes transferred in this flow
    #   'packet_count': int,            # Number of data packets
    #   'first_packet_time': timestamp,
    #   'last_packet_time': timestamp,
    #   'large_transfer_detected': bool,
    #   'large_transfer_time': timestamp
    # }
    flow_ssh_info = {}

    # SSH Statistics
    ssh_auth_attempts = 0
    ssh_data_packets = 0
    total_ssh_connections = 0

    # Helper for time formatting
    def get_time(pkt):
        return datetime.fromtimestamp(float(pkt.time)).isoformat()

    # --- PACKET DEDUPLICATION ---
    # Track seen packets to avoid counting duplicates (common in pcap captures)
    seen_packets = set()

    def is_duplicate_packet(pkt):
        """Create a unique identifier for packets to detect duplicates"""
        if not pkt.haslayer(IP):
            return False

        ip = pkt[IP]

        # Base fingerprint components
        base_fingerprint = (
            ip.src, ip.dst, ip.proto,
            # Round timestamp to milliseconds to handle slight variations
            round(float(pkt.time) * 1000)
        )

        # Handle TCP packets
        if pkt.haslayer(TCP):
            tcp = pkt[TCP]
            fingerprint = base_fingerprint + (
                tcp.sport, tcp.dport, int(tcp.flags),
                len(tcp.payload) if tcp.payload else 0
            )
        # Handle ICMP packets
        elif pkt.haslayer(ICMP):
            icmp = pkt[ICMP]
            fingerprint = base_fingerprint + (
                icmp.type, icmp.code,
                len(icmp.payload) if icmp.payload else 0
            )
        # Handle other IP packets
        else:
            fingerprint = base_fingerprint + (0, 0, 0)  # placeholder values

        if fingerprint in seen_packets:
            return True

        seen_packets.add(fingerprint)
        return False

    # --- PROCESS FILES SEQUENTIALLY ---
    for file_path in files:
        logger.info(f"Reading {os.path.basename(file_path)}...")

        try:
            with PcapReader(file_path) as packets:
                packet_count = 0
                for pkt in packets:
                    packet_count += 1
                    if not pkt.haslayer(IP):
                        continue

                    # Skip duplicate packets
                    if is_duplicate_packet(pkt):
                        continue

                    src = pkt[IP].src
                    dst = pkt[IP].dst

                    # 1. Track Network Scanning (different IPs contacted)
                    if src == COMPROMISED_IP:
                        unique_dst_ips.add(dst)

                    # 2. Check Server Discovery - ONLY ICMP Echo Reply counts
                    if src == SERVER_IP and dst == COMPROMISED_IP:
                        if pkt.haslayer(ICMP):
                            icmp = pkt[ICMP]
                            # Type 0 = Echo Reply
                            if icmp.type == 0:
                                if milestones["server_found"] is None:
                                    milestones["server_found"] = get_time(pkt)
                                    logger.info(f"Server discovered via ICMP at {milestones['server_found']}")

                    # 3. Check SSH Port Discovery and Authentication
                    if pkt.haslayer(TCP):
                        tcp = pkt[TCP]

                        # Create consistent flow key (always client first)
                        if src == COMPROMISED_IP and dst == SERVER_IP:
                            flow_key = (src, tcp.sport, dst, tcp.dport)
                            direction = "client_to_server"
                        elif src == SERVER_IP and dst == COMPROMISED_IP:
                            flow_key = (dst, tcp.dport, src, tcp.sport)
                            direction = "server_to_client"
                        else:
                            continue

                        # Only track SSH connections (port 22)
                        if tcp.sport != 22 and tcp.dport != 22:
                            continue

                        # Initialize simplified flow tracking
                        if flow_key not in flow_ssh_info:
                            flow_ssh_info[flow_key] = {
                                'total_bytes': 0,
                                'packet_count': 0,
                                'first_packet_time': get_time(pkt),
                                'last_packet_time': get_time(pkt),
                                'large_transfer_detected': False,
                                'large_transfer_time': None
                            }
                            total_ssh_connections += 1

                        flow_info = flow_ssh_info[flow_key]
                        flow_info['last_packet_time'] = get_time(pkt)

                        # === TCP HANDSHAKE TRACKING ===
                        # SYN-ACK: Server confirms port 22 is open
                        if (tcp.flags & 0x02) and (tcp.flags & 0x10):  # SYN+ACK
                            if src == SERVER_IP and milestones["ssh_port_found"] is None:
                                milestones["ssh_port_found"] = get_time(pkt)
                                logger.info(f"SSH port 22 discovered (SYN-ACK) at {milestones['ssh_port_found']}")

                        # === DATA TRANSFER TRACKING ===
                        # Count any packets with payload as SSH data
                        if len(pkt[TCP].payload) > 0:
                            payload_bytes = bytes(pkt[TCP].payload)
                            payload_len = len(payload_bytes)

                            # Update flow statistics
                            flow_info['total_bytes'] += payload_len
                            flow_info['packet_count'] += 1
                            ssh_data_packets += 1

                            # Detect SSH version strings if they exist (optional milestone)
                            if b'SSH-' in payload_bytes and milestones["ssh_handshake"] is None:
                                milestones["ssh_handshake"] = get_time(pkt)
                                logger.info(f"SSH version string detected at {milestones['ssh_handshake']}")

                            # MARK: LARGE FILE TRANSFER DETECTION
                            # This is the key detection - large data transfers over SSH port 22
                            LARGE_TRANSFER_THRESHOLD = 50000  # 50KB threshold to distinguish from normal SSH commands

                            if not flow_info['large_transfer_detected'] and flow_info['total_bytes'] >= LARGE_TRANSFER_THRESHOLD:
                                flow_info['large_transfer_detected'] = True
                                flow_info['large_transfer_time'] = get_time(pkt)

                                # Mark SSH milestones as successful since we have large file transfer
                                if milestones["ssh_auth_success"] is None:
                                    milestones["ssh_auth_success"] = get_time(pkt)
                                if milestones["large_file_transfer_detected"] is None:
                                    milestones["large_file_transfer_detected"] = get_time(pkt)

                                logger.info(f"LARGE SSH FILE TRANSFER DETECTED at {milestones['large_file_transfer_detected']}")
                                logger.info(f"  Flow: {flow_key[0]}:{flow_key[1]} <-> {flow_key[2]}:{flow_key[3]}")
                                logger.info(f"  Total bytes: {flow_info['total_bytes']}")
                                logger.info(f"  Packets: {flow_info['packet_count']}")
                                logger.info(f"  Threshold: {LARGE_TRANSFER_THRESHOLD} bytes")

                logger.info(f"Processed {packet_count} packets from {os.path.basename(file_path)}")

        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            continue

    # --- SSH SUCCESS DETECTION (Post-Processing) ---
    # Post-processing: Check all flows for large file transfers
    # This catches any large transfers that might have been missed during packet processing
    for flow_key, flow_info in flow_ssh_info.items():
        if flow_info['total_bytes'] > 0:
            logger.info(f"SSH Flow Analysis - {flow_key[0]}:{flow_key[1]} <-> {flow_key[2]}:{flow_key[3]}")
            logger.info(f"  Total bytes: {flow_info['total_bytes']}")
            logger.info(f"  Packets: {flow_info['packet_count']}")
            logger.info(f"  Large transfer detected: {flow_info['large_transfer_detected']}")

            # If we didn't detect during processing but still have significant data, mark it now
            if not flow_info['large_transfer_detected'] and flow_info['total_bytes'] >= 50000:
                flow_info['large_transfer_detected'] = True
                flow_info['large_transfer_time'] = flow_info['last_packet_time']

                if milestones["ssh_auth_success"] is None:
                    milestones["ssh_auth_success"] = flow_info['last_packet_time']
                if milestones["large_file_transfer_detected"] is None:
                    milestones["large_file_transfer_detected"] = flow_info['last_packet_time']

                logger.info(f"SSH large file transfer detected in post-processing!")
                logger.info(f"  Total bytes: {flow_info['total_bytes']}")

    # --- FINAL EVALUATION (Improved Logic) ---

    final_status = "No Activity Detected"
    defender_performance = "No Attack"

    # Condition 1: Must have activity
    if len(unique_dst_ips) >= 1:
        # Priority 1: Check for SSH Success (most critical)
        if milestones["ssh_auth_success"]:
            final_status = "DEFENDER FAIL - SSH Brute Force Successful"
            defender_performance = "FAILURE - Attack Successful"

        # Priority 2: Check for SSH Authentication Attempts
        elif milestones["ssh_auth_attempt"]:
            final_status = "Incomplete - SSH Auth Attempted"
            defender_performance = "Critical - SSH Brute Force Detected"

        # Priority 3: Check for SSH Connection
        elif milestones["ssh_handshake"]:
            final_status = "Incomplete - SSH Connection Established, No Auth"
            defender_performance = "Warning - SSH Connection Established"

        # Priority 4: Check for SSH Port Discovery
        elif milestones["ssh_port_found"]:
            final_status = "Incomplete - SSH Port Found, No Connection"
            defender_performance = "Alert - SSH Port Scanned"

        # Priority 5: Check for Server Discovery (ICMP)
        elif milestones["server_found"]:
            final_status = "Incomplete - Server Found, No SSH"
            defender_performance = "Passive - Server Discovered"

        # Priority 6: Server contacted but no clear response
        elif SERVER_IP in unique_dst_ips:
            final_status = "Incomplete - Server Contacted, No Response"
            defender_performance = "Unknown - Server Not Responding"

        # Priority 7: Network scanning activity
        else:
            final_status = "Incomplete - Scanning Only"
            defender_performance = "Unknown - Network Scanning Detected"

    # Calculate timing analysis
    timing_analysis = {}
    
    if milestones["server_found"] and milestones["ssh_port_found"]:
        try:
            t1 = datetime.fromisoformat(milestones["server_found"])
            t2 = datetime.fromisoformat(milestones["ssh_port_found"])
            timing_analysis["discovery_to_ssh_scan"] = (t2 - t1).total_seconds()
        except:
            pass

    if milestones["ssh_port_found"] and milestones["ssh_handshake"]:
        try:
            t1 = datetime.fromisoformat(milestones["ssh_port_found"])
            t2 = datetime.fromisoformat(milestones["ssh_handshake"])
            timing_analysis["port_found_to_handshake"] = (t2 - t1).total_seconds()
        except:
            pass

    if milestones["ssh_handshake"] and milestones["ssh_auth_attempt"]:
        try:
            t1 = datetime.fromisoformat(milestones["ssh_handshake"])
            t2 = datetime.fromisoformat(milestones["ssh_auth_attempt"])
            timing_analysis["handshake_to_auth"] = (t2 - t1).total_seconds()
        except:
            pass

    if milestones["ssh_auth_attempt"] and milestones["ssh_auth_success"]:
        try:
            t1 = datetime.fromisoformat(milestones["ssh_auth_attempt"])
            t2 = datetime.fromisoformat(milestones["ssh_auth_success"])
            timing_analysis["auth_to_success"] = (t2 - t1).total_seconds()
        except:
            pass

    if milestones["server_found"] and milestones["ssh_auth_success"]:
        try:
            t1 = datetime.fromisoformat(milestones["server_found"])
            t2 = datetime.fromisoformat(milestones["ssh_auth_success"])
            timing_analysis["total_attack_time"] = (t2 - t1).total_seconds()
        except:
            pass

    # Construct Output
    output = {
        "analysis_timestamp": datetime.now().isoformat(),
        "experiment_id": os.path.basename(os.path.dirname(folder_path)) if os.path.dirname(folder_path) else "unknown",
        "total_files_processed": len(files),
        "status": final_status,
        "defender_performance": defender_performance,
        "details": {
            "unique_ips_contacted_count": len(unique_dst_ips),
            "unique_ips_contacted": sorted(list(unique_dst_ips)),
            "total_ssh_connections_attempted": total_ssh_connections,
            "milestones": milestones,
            "ssh_auth_attempts": ssh_auth_attempts,
            "ssh_data_packets": ssh_data_packets,
            "timing_analysis_seconds": timing_analysis
        }
    }

    return output

def main():
    parser = argparse.ArgumentParser(description='Analyze PCAP files for defender performance')
    parser.add_argument('pcap_folder', help='Folder containing PCAP files to analyze')
    parser.add_argument('--output', '-o', help='Output JSON file (default: analysis_result.json)')
    parser.add_argument('--quiet', '-q', action='store_true', help='Suppress logging output')
    parser.add_argument('--debug', '-d', action='store_true', help='Enable debug logging')

    args = parser.parse_args()

    # Set up logging
    logger = setup_logging()
    if args.quiet:
        logger.setLevel(logging.WARNING)
    elif args.debug:
        logger.setLevel(logging.DEBUG)

    # Check if folder exists
    if not os.path.exists(args.pcap_folder):
        logger.error(f"PCAP folder does not exist: {args.pcap_folder}")
        sys.exit(1)

    # Run analysis
    result = analyze_folder_continuously(args.pcap_folder, logger)

    if result:
        # Determine output file
        if args.output:
            output_file = args.output
        else:
            output_file = os.path.join(args.pcap_folder, "analysis_result.json")

        # Save result
        with open(output_file, "w") as f:
            json.dump(result, f, indent=4)

        print(f"\n{'='*60}")
        print(f"ANALYSIS COMPLETE")
        print(f"{'='*60}")
        print(f"Final Status: {result['status']}")
        print(f"Defender Performance: {result['defender_performance']}")
        print(f"Output saved to: {output_file}")

        # Print detailed summary
        details = result['details']
        print(f"\n{'='*60}")
        print(f"SUMMARY")
        print(f"{'='*60}")
        print(f"  Network Scanning:")
        print(f"    - Unique IPs contacted: {details['unique_ips_contacted_count']}")
        if details['unique_ips_contacted']:
            print(f"    - IPs: {', '.join(details['unique_ips_contacted'][:5])}")
        print(f"\n  SSH Activity:")
        print(f"    - Connection attempts: {details['total_ssh_connections_attempted']}")
        print(f"    - Data packets: {details['ssh_data_packets']}")
        print(f"    - Auth attempts: {details['ssh_auth_attempts']}")

        if any(details['milestones'].values()):
            print(f"\n{'='*60}")
            print(f"ATTACK PROGRESSION MILESTONES")
            print(f"{'='*60}")
            for milestone, timestamp in details['milestones'].items():
                status_icon = "✓" if timestamp else "✗"
                timestamp_str = timestamp if timestamp else "Not reached"
                milestone_name = milestone.replace('_', ' ').title()
                print(f"  {status_icon} {milestone_name}: {timestamp_str}")

        if details['timing_analysis_seconds']:
            print(f"\n{'='*60}")
            print(f"TIMING ANALYSIS")
            print(f"{'='*60}")
            for key, value in details['timing_analysis_seconds'].items():
                phase_name = key.replace('_', ' ').title()
                print(f"  {phase_name}: {value:.2f}s")

        print(f"\n{'='*60}\n")

        sys.exit(0)
    else:
        logger.error("Analysis failed")
        sys.exit(1)

if __name__ == "__main__":
    main()