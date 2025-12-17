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
        "ssh_auth_success": None        # Successful SSH authentication
    }

    # TCP State Machine for Port 22
    # Key: (client_ip, client_port, server_ip, server_port) -> Value: State String
    tcp_states = {}

    # Per-flow SSH protocol tracking
    # flow_ssh_info[flow_key] = {
    #   'client_version_seen': bool,
    #   'server_version_seen': bool,
    #   'key_exchange_started': bool,
    #   'key_exchange_complete': bool,
    #   'auth_phase_started': bool,
    #   'packets_after_key_exchange_client': int,
    #   'packets_after_key_exchange_server': int,
    #   'bytes_after_key_exchange_client': int,
    #   'bytes_after_key_exchange_server': int,
    #   'key_exchange_complete_time': timestamp,
    #   'first_auth_packet_time': timestamp,
    #   'sustained_session_start': timestamp,
    #   'last_packet_time': timestamp
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
                        if flow_key[3] != 22:
                            continue

                        # Initialize flow tracking
                        if flow_key not in flow_ssh_info:
                            flow_ssh_info[flow_key] = {
                                'client_version_seen': False,
                                'server_version_seen': False,
                                'key_exchange_started': False,
                                'key_exchange_complete': False,
                                'auth_phase_started': False,
                                'packets_after_key_exchange_client': 0,
                                'packets_after_key_exchange_server': 0,
                                'bytes_after_key_exchange_client': 0,
                                'bytes_after_key_exchange_server': 0,
                                'key_exchange_complete_time': None,
                                'first_auth_packet_time': None,
                                'sustained_session_start': None,
                                'last_packet_time': get_time(pkt)
                            }
                            tcp_states[flow_key] = "NEW"
                            total_ssh_connections += 1

                        flow_info = flow_ssh_info[flow_key]
                        flow_info['last_packet_time'] = get_time(pkt)

                        # === CLIENT TO SERVER ===
                        if direction == "client_to_server":
                            # SYN: Client initiates connection
                            if (tcp.flags & 0x02) and not (tcp.flags & 0x10):  # SYN without ACK
                                tcp_states[flow_key] = "SYN_SENT"
                                logger.debug(f"SYN sent to port 22 from {tcp.sport}")

                            # ACK: Client completes handshake or sends data
                            elif tcp.flags & 0x10:  # ACK flag set
                                current_state = tcp_states.get(flow_key, "UNKNOWN")
                                
                                # Complete TCP handshake
                                if current_state == "SYN_ACK_RECVD":
                                    tcp_states[flow_key] = "ESTABLISHED"
                                    logger.debug(f"TCP connection established for flow {flow_key}")

                                # Process payload if present
                                if len(pkt[TCP].payload) > 0:
                                    payload_bytes = bytes(pkt[TCP].payload)
                                    payload_len = len(payload_bytes)
                                    ssh_data_packets += 1

                                    # Detect SSH version string (cleartext "SSH-2.0-..." or "SSH-1.x-...")
                                    if b'SSH-' in payload_bytes and not flow_info['client_version_seen']:
                                        flow_info['client_version_seen'] = True
                                        logger.debug(f"Client SSH version string detected")

                                        # Check if both sides have exchanged versions (SSH handshake complete)
                                        if flow_info['server_version_seen'] and milestones["ssh_handshake"] is None:
                                            milestones["ssh_handshake"] = get_time(pkt)
                                            logger.info(f"SSH protocol handshake complete at {milestones['ssh_handshake']}")

                                    # After version exchange, next large packets are key exchange
                                    elif flow_info['client_version_seen'] and flow_info['server_version_seen']:
                                        if not flow_info['key_exchange_started']:
                                            flow_info['key_exchange_started'] = True
                                            logger.debug(f"SSH key exchange started")

                                        # Key exchange typically involves several packets of varying sizes
                                        # After key exchange, we see smaller, more uniform encrypted packets
                                        # Heuristic: After seeing 3+ packets from both sides post-version,
                                        # and packet sizes stabilize (indicating encryption is active),
                                        # we consider key exchange complete
                                        
                                        if flow_info['key_exchange_started'] and not flow_info['key_exchange_complete']:
                                            # Count packets after version exchange
                                            flow_info['packets_after_key_exchange_client'] += 1
                                            flow_info['bytes_after_key_exchange_client'] += payload_len

                                            # If we've seen enough exchange from both sides, mark complete
                                            if (flow_info['packets_after_key_exchange_client'] >= 3 and 
                                                flow_info['packets_after_key_exchange_server'] >= 3):
                                                flow_info['key_exchange_complete'] = True
                                                flow_info['key_exchange_complete_time'] = get_time(pkt)
                                                
                                                if milestones["ssh_key_exchange_complete"] is None:
                                                    milestones["ssh_key_exchange_complete"] = get_time(pkt)
                                                    logger.info(f"SSH key exchange complete at {milestones['ssh_key_exchange_complete']}")

                                        # After key exchange, we're in authentication phase
                                        if flow_info['key_exchange_complete'] and not flow_info['auth_phase_started']:
                                            flow_info['auth_phase_started'] = True
                                            flow_info['first_auth_packet_time'] = get_time(pkt)
                                            
                                            if milestones["ssh_auth_attempt"] is None:
                                                milestones["ssh_auth_attempt"] = get_time(pkt)
                                                logger.info(f"SSH authentication phase started at {milestones['ssh_auth_attempt']}")
                                            
                                            ssh_auth_attempts += 1

                        # === SERVER TO CLIENT ===
                        elif direction == "server_to_client":
                            # SYN-ACK: Server confirms port 22 is open
                            if (tcp.flags & 0x02) and (tcp.flags & 0x10):  # SYN+ACK
                                if milestones["ssh_port_found"] is None:
                                    milestones["ssh_port_found"] = get_time(pkt)
                                    logger.info(f"SSH port 22 discovered (SYN-ACK) at {milestones['ssh_port_found']}")

                                if tcp_states.get(flow_key) == "SYN_SENT":
                                    tcp_states[flow_key] = "SYN_ACK_RECVD"

                            # Server sends data
                            elif (tcp.flags & 0x10) and len(pkt[TCP].payload) > 0:  # ACK with payload
                                payload_bytes = bytes(pkt[TCP].payload)
                                payload_len = len(payload_bytes)

                                # Detect SSH version string from server
                                if b'SSH-' in payload_bytes and not flow_info['server_version_seen']:
                                    flow_info['server_version_seen'] = True
                                    logger.debug(f"Server SSH version string detected")

                                    # Check if both sides have exchanged versions
                                    if flow_info['client_version_seen'] and milestones["ssh_handshake"] is None:
                                        milestones["ssh_handshake"] = get_time(pkt)
                                        logger.info(f"SSH protocol handshake complete at {milestones['ssh_handshake']}")

                                # Track key exchange packets from server
                                elif flow_info['client_version_seen'] and flow_info['server_version_seen']:
                                    if flow_info['key_exchange_started'] and not flow_info['key_exchange_complete']:
                                        flow_info['packets_after_key_exchange_server'] += 1
                                        flow_info['bytes_after_key_exchange_server'] += payload_len

                                        # Check if key exchange is complete
                                        if (flow_info['packets_after_key_exchange_client'] >= 3 and 
                                            flow_info['packets_after_key_exchange_server'] >= 3):
                                            flow_info['key_exchange_complete'] = True
                                            flow_info['key_exchange_complete_time'] = get_time(pkt)
                                            
                                            if milestones["ssh_key_exchange_complete"] is None:
                                                milestones["ssh_key_exchange_complete"] = get_time(pkt)
                                                logger.info(f"SSH key exchange complete at {milestones['ssh_key_exchange_complete']}")

                                    # After key exchange, look for successful authentication
                                    # Success indicators:
                                    # 1. Sustained bidirectional traffic (shell session)
                                    # 2. Server sends significant data (welcome banner, prompt)
                                    # 3. Connection stays alive with interactive patterns
                                    if flow_info['key_exchange_complete'] and flow_info['auth_phase_started']:
                                        
                                        # Calculate time since auth started
                                        try:
                                            auth_start = datetime.fromisoformat(flow_info['first_auth_packet_time'])
                                            current_time = datetime.fromtimestamp(float(pkt.time))
                                            time_since_auth = (current_time - auth_start).total_seconds()
                                        except:
                                            time_since_auth = 0

                                        # Count ALL packets with payload after key exchange (more accurate)
                                        # Since we're in the auth phase, all payload packets count toward auth/post-auth traffic
                                        client_auth_packets = flow_info['packets_after_key_exchange_client']
                                        server_auth_packets = flow_info['packets_after_key_exchange_server']

                                        # SUCCESS CRITERIA:
                                        # - At least 5 payload packets from each side after key exchange
                                        # - At least 500 bytes from server (banner, prompt, etc.)
                                        # - Connection sustained for at least 2 seconds
                                        # This indicates the server accepted the auth and started a session
                                        if (client_auth_packets >= 5 and
                                            server_auth_packets >= 5 and
                                            flow_info['bytes_after_key_exchange_server'] > 500 and
                                            time_since_auth >= 2.0):

                                            if milestones["ssh_auth_success"] is None:
                                                milestones["ssh_auth_success"] = get_time(pkt)
                                                flow_info['sustained_session_start'] = get_time(pkt)
                                                logger.info(f"SSH authentication SUCCESS detected at {milestones['ssh_auth_success']}")
                                                logger.info(f"  Auth packets: client={client_auth_packets}, server={server_auth_packets}")
                                                logger.info(f"  Server bytes: {flow_info['bytes_after_key_exchange_server']}")
                                                logger.info(f"  Time since auth start: {time_since_auth:.1f}s")
                                                tcp_states[flow_key] = "AUTH_SUCCESS"

                logger.info(f"Processed {packet_count} packets from {os.path.basename(file_path)}")

        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            continue

    # --- SSH SUCCESS DETECTION (Post-Processing) ---
    # Check all flows for successful authentication criteria
    for flow_key, flow_info in flow_ssh_info.items():
        if flow_info['key_exchange_complete'] and flow_info['auth_phase_started'] and not milestones["ssh_auth_success"]:

            # Calculate time since auth started
            try:
                auth_start = datetime.fromisoformat(flow_info['first_auth_packet_time'])
                last_packet_time = datetime.fromisoformat(flow_info['last_packet_time'])
                time_since_auth = (last_packet_time - auth_start).total_seconds()
            except:
                time_since_auth = 0

            client_auth_packets = flow_info['packets_after_key_exchange_client']
            server_auth_packets = flow_info['packets_after_key_exchange_server']
            server_bytes = flow_info['bytes_after_key_exchange_server']

            logger.info(f"SSH flow analysis - Client: {client_auth_packets}, Server: {server_auth_packets}, Server bytes: {server_bytes}, Duration: {time_since_auth:.1f}s")

            # SUCCESS CRITERIA (more realistic for actual PCAP captures):
            # - At least 3 payload packets from each side after key exchange
            # - At least 500 bytes from server (banner, prompt, etc.)
            # - Connection sustained for at least 2 seconds
            # This indicates the server accepted the auth and started a session
            if (client_auth_packets >= 3 and
                server_auth_packets >= 3 and
                server_bytes > 500 and
                time_since_auth >= 2.0):

                if milestones["ssh_auth_success"] is None:
                    milestones["ssh_auth_success"] = flow_info['last_packet_time']
                    logger.info(f"SSH authentication SUCCESS detected at {milestones['ssh_auth_success']}")
                    logger.info(f"  Auth packets: client={client_auth_packets}, server={server_auth_packets}")
                    logger.info(f"  Server bytes: {server_bytes}")
                    logger.info(f"  Time since auth start: {time_since_auth:.1f}s")

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