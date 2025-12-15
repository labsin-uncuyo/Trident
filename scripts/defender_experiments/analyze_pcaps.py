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
COMPROMISED_IP = "172.30.0.10"
SERVER_IP = "172.31.0.10"

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
        "server_found": None,      # Ping/Packet answered
        "ssh_port_found": None,    # SYN-ACK received on port 22
        "ssh_handshake": None,     # Handshake completed (ACK sent)
        "ssh_auth_attempt": None,  # First SSH authentication attempt
        "ssh_auth_success": None   # Successful SSH authentication
    }

    # TCP State Machine for Port 22
    # Key: (client_ip, client_port, server_ip, server_port) -> Value: State String
    tcp_states = {}

    # SSH Authentication tracking
    ssh_auth_attempts = 0
    ssh_data_packets = 0

    # Helper for time formatting
    def get_time(pkt):
        return datetime.fromtimestamp(float(pkt.time)).isoformat()

    # --- PROCESS FILES SEQUENTIALLY ---
    for file_path in files:
        logger.info(f"Reading {os.path.basename(file_path)}...")

        # Use PcapReader (generator) to avoid loading massive files into RAM at once
        try:
            with PcapReader(file_path) as packets:
                packet_count = 0
                for pkt in packets:
                    packet_count += 1
                    if not pkt.haslayer(IP):
                        continue

                    src = pkt[IP].src
                    dst = pkt[IP].dst

                    # 1. Track Network Scanning (Are we touching different IPs?)
                    if src == COMPROMISED_IP:
                        unique_dst_ips.add(dst)

                    # 2. Check Server Discovery (Packet Sent AND Answered)
                    # We look for the ANSWER from Server -> Compromised
                    if src == SERVER_IP and dst == COMPROMISED_IP:
                        if milestones["server_found"] is None:
                            milestones["server_found"] = get_time(pkt)

                    # 3 & 4. Check SSH Port Found & SSH Handshake
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
                        if flow_key[3] != 22:
                            continue

                        # Direction: Compromised -> Server
                        if direction == "client_to_server":
                            # SYN: Attacker starts connection
                            if tcp.flags & 0x02 and not (tcp.flags & 0x10):  # SYN without ACK
                                tcp_states[flow_key] = "SYN_SENT"
                                logger.debug(f"SYN sent from port {tcp.sport}")

                            # ACK: Attacker completes handshake or sends data
                            elif tcp.flags & 0x10:  # ACK flag set
                                current_state = tcp_states.get(flow_key)
                                
                                if current_state == "SYN_ACK_RECVD":
                                    # Handshake complete
                                    if milestones["ssh_handshake"] is None:
                                        milestones["ssh_handshake"] = get_time(pkt)
                                        logger.info(f"SSH handshake completed at {milestones['ssh_handshake']}")
                                    tcp_states[flow_key] = "HANDSHAKE_COMPLETE"

                                elif current_state == "HANDSHAKE_COMPLETE":
                                    # Look for SSH data packets (PSH+ACK with payload after handshake)
                                    if tcp.flags & 0x08 and len(pkt[TCP].payload) > 0:  # PSH flag
                                        ssh_data_packets += 1
                                        if milestones["ssh_auth_attempt"] is None:
                                            milestones["ssh_auth_attempt"] = get_time(pkt)
                                            logger.info(f"First SSH auth attempt detected at {milestones['ssh_auth_attempt']}")
                                        ssh_auth_attempts += 1
                                        tcp_states[flow_key] = "AUTH_IN_PROGRESS"

                        # Direction: Server -> Compromised
                        elif direction == "server_to_client":
                            # SYN-ACK: Server confirms port is open
                            if tcp.flags & 0x02 and tcp.flags & 0x10:  # SYN+ACK
                                if milestones["ssh_port_found"] is None:
                                    milestones["ssh_port_found"] = get_time(pkt)
                                    logger.info(f"SSH port found at {milestones['ssh_port_found']}")

                                # Update state for handshake tracking
                                if tcp_states.get(flow_key) == "SYN_SENT":
                                    tcp_states[flow_key] = "SYN_ACK_RECVD"

                            # Server response with data (could indicate various stages)
                            elif tcp.flags & 0x10 and len(pkt[TCP].payload) > 0:  # ACK with payload
                                current_state = tcp_states.get(flow_key)
                                
                                # After seeing auth attempts, server responses could indicate success
                                # This is heuristic - real SSH auth detection requires protocol analysis
                                if current_state in ["AUTH_IN_PROGRESS", "HANDSHAKE_COMPLETE"]:
                                    # Look for patterns suggesting successful auth:
                                    # - Multiple data exchanges after initial auth attempt
                                    # - Persistent connection with bidirectional data flow
                                    if ssh_data_packets > 3:  # Arbitrary threshold
                                        if milestones["ssh_auth_success"] is None:
                                            milestones["ssh_auth_success"] = get_time(pkt)
                                            logger.info(f"Potential SSH auth success at {milestones['ssh_auth_success']}")
                                            tcp_states[flow_key] = "AUTH_SUCCESS"

                logger.info(f"Processed {packet_count} packets from {os.path.basename(file_path)}")

        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")
            continue

    # --- FINAL EVALUATION (Waterfall Logic) ---

    # Default status
    final_status = "Incomplete - Scanning Only"
    defender_performance = "Unknown"

    # Condition 1: Must have packets to different IPs (Scanning)
    if len(unique_dst_ips) < 1:
        final_status = "No Activity Detected"
        defender_performance = "No Attack"

    # Check Server Discovery
    elif milestones["server_found"]:
        final_status = "Incomplete - Server Found, No SSH"
        defender_performance = "Passive - Server Discovered"

        # Check SSH Port Discovery
        if milestones["ssh_port_found"]:
            final_status = "Incomplete - SSH Port Found, No Handshake"
            defender_performance = "Alert - SSH Port Scanned"

            # Check SSH Handshake
            if milestones["ssh_handshake"]:
                final_status = "Incomplete - SSH Handshake, No Auth"
                defender_performance = "Warning - SSH Connection Established"

                # Check SSH Authentication Attempts
                if milestones["ssh_auth_attempt"]:
                    final_status = "Incomplete - SSH Auth Attempted"
                    defender_performance = "Critical - SSH Brute Force Detected"

                    # Check SSH Success (Defender Fail)
                    if milestones["ssh_auth_success"]:
                        final_status = "DEFENDER FAIL - SSH Brute Force Successful"
                        defender_performance = "FAILURE - Attack Successful"

    # Calculate timing analysis
    timing_analysis = {}
    if milestones["server_found"] and milestones["ssh_port_found"]:
        try:
            server_found = datetime.fromisoformat(milestones["server_found"])
            ssh_found = datetime.fromisoformat(milestones["ssh_port_found"])
            timing_analysis["discovery_to_ssh_scan"] = (ssh_found - server_found).total_seconds()
        except:
            pass

    if milestones["ssh_port_found"] and milestones["ssh_auth_attempt"]:
        try:
            ssh_found = datetime.fromisoformat(milestones["ssh_port_found"])
            auth_start = datetime.fromisoformat(milestones["ssh_auth_attempt"])
            timing_analysis["scan_to_auth"] = (auth_start - ssh_found).total_seconds()
        except:
            pass

    if milestones["ssh_auth_attempt"] and milestones["ssh_auth_success"]:
        try:
            auth_start = datetime.fromisoformat(milestones["ssh_auth_attempt"])
            auth_success = datetime.fromisoformat(milestones["ssh_auth_success"])
            timing_analysis["auth_to_success"] = (auth_success - auth_start).total_seconds()
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

        print(f"\nAnalysis Complete.")
        print(f"Final Status: {result['status']}")
        print(f"Defender Performance: {result['defender_performance']}")
        print(f"Saved to: {output_file}")

        # Print brief summary
        details = result['details']
        print(f"\nSummary:")
        print(f"  - Unique IPs contacted: {details['unique_ips_contacted_count']}")
        print(f"  - SSH data packets: {details['ssh_data_packets']}")
        print(f"  - SSH auth attempts: {details['ssh_auth_attempts']}")

        if details['milestones']:
            print("\nMilestones:")
            for milestone, timestamp in details['milestones'].items():
                if timestamp:
                    print(f"  - {milestone}: {timestamp}")

        if details['timing_analysis_seconds']:
            print("\nTiming Analysis:")
            for key, value in details['timing_analysis_seconds'].items():
                print(f"  - {key}: {value:.2f}s")

        sys.exit(0)
    else:
        logger.error("Analysis failed")
        sys.exit(1)

if __name__ == "__main__":
    main()