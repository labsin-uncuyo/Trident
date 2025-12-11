SERVICES := router switch compromised server
COMPOSE ?= docker compose
PYTHON ?= python3

export COMPOSE_PROJECT_NAME := lab
RUN_ID_FILE := ./outputs/.current_run

.PHONY: build up down verify slips_verify clean ssh_keys aracne_attack ghosts_psql

build:
	@for svc in $(SERVICES); do \
		echo "Building $$svc"; \
		docker build -t lab/$$svc:latest images/$$svc; \
	done
	@echo "Pulling slips_defender image"
	@docker pull stratosphereips/slips:latest

up:
	@RUN_ID_VALUE=$$( [ -f $(RUN_ID_FILE) ] && cat $(RUN_ID_FILE) || echo logs_$$(date +%Y%m%d_%H%M%S) ); \
	echo $$RUN_ID_VALUE > $(RUN_ID_FILE); \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips ./outputs/$$RUN_ID_VALUE/aracne ./outputs/$$RUN_ID_VALUE/ghosts; \
	export RUN_ID=$$RUN_ID_VALUE; \
	docker ps -aq --filter "name=^lab_" | xargs -r docker rm -f >/dev/null 2>&1 || true; \
	docker network rm lab_net_a >/dev/null 2>&1 || true; \
	docker network rm lab_net_b >/dev/null 2>&1 || true; \
	opts=""; \
	for p in core defender; do opts="$${opts} --profile $$p"; done; \
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d; \
	echo "Setting up SSH keys for auto_responder..."; \
	./scripts/setup_ssh_keys_host.sh

down:
	$(COMPOSE) down --volumes
	@rm -f $(RUN_ID_FILE)

verify:
	@echo "[verify] Waiting for full lab readiness..."
	./scripts/wait_for_lab_ready.sh
	@echo "[verify] Checking server HTTP from compromised -> server"
	docker exec lab_compromised curl -sf -o /dev/null http://172.31.0.10:80 && echo "[verify] Server reachable"
	@echo "[verify] Checking SLIPS API health"
	@DEFENDER_PORT_VALUE=$${DEFENDER_PORT:-}; \
	for env_file in ".env" ".env.example"; do \
		if [ -z "$${DEFENDER_PORT_VALUE}" ] && [ -f "$$env_file" ]; then \
			val=$$(grep -E '^DEFENDER_PORT=' "$$env_file" | tail -n1 | cut -d'=' -f2); \
			if [ -n "$$val" ]; then DEFENDER_PORT_VALUE="$$val"; fi; \
		fi; \
	done; \
	DEFENDER_PORT_VALUE=$${DEFENDER_PORT_VALUE:-8000}; \
	curl -sf "http://localhost:$${DEFENDER_PORT_VALUE}/health" >/dev/null && echo "[verify] SLIPS API healthy"
	@echo "[verify] Lab containers status (lab_*)"
	docker ps --filter "name=lab_" --format "table {{.Names}}\t{{.Status}}"

slips_verify:
	@RUN_ID_VALUE=$$( [ -f $(RUN_ID_FILE) ] && cat $(RUN_ID_FILE) || echo logs_$$(date +%Y%m%d_%H%M%S) ); \
	echo $$RUN_ID_VALUE > $(RUN_ID_FILE); \
	export RUN_ID=$$RUN_ID_VALUE; \
	echo "[slips_verify] Using RUN_ID=$$RUN_ID_VALUE"; \
	echo "[slips_verify] Resetting lab"; \
	$(MAKE) down; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips; \
	echo "[slips_verify] Bringing lab up"; \
	opts=""; \
	for p in core defender; do opts="$${opts} --profile $$p"; done; \
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d; \
	echo "[slips_verify] Waiting for full lab readiness..."; \
	./scripts/wait_for_lab_ready.sh; \
	echo "[slips_verify] Running Nmap service scan from compromised -> server"; \
	docker exec lab_compromised nmap -sV -Pn -T4 172.31.0.10 || true; \
	echo "[slips_verify] Running Nmap full port scan from compromised -> server"; \
	docker exec lab_compromised nmap -sS -T4 -p- 172.31.0.10 || true; \
	echo "[slips_verify] Running SSH brute-force attempts (200) from compromised -> server"; \
	for i in $$(seq 1 200); do \
		docker exec lab_compromised ssh -n -T \
			-o BatchMode=yes \
			-o PreferredAuthentications=password \
			-o PubkeyAuthentication=no \
			-o UserKnownHostsFile=/dev/null \
			-o StrictHostKeyChecking=no \
			-o ConnectTimeout=1 \
			fakeuser$$i@172.31.0.10 -p 22 >/dev/null 2>&1 || true; \
	done; \
	echo "[slips_verify] Forcing SLIPS processing of captured traffic"; \
	$(PYTHON) scripts/slips_verify.py --run-id $$RUN_ID_VALUE; \
	echo "[slips_verify] Done. Outputs in ./outputs/$$RUN_ID_VALUE"

ssh_keys:
	@echo "Setting up SSH keys for auto_responder..."
	./scripts/setup_ssh_keys_host.sh

aracne_attack:
	@RUN_ID_VALUE=$$( [ -f $(RUN_ID_FILE) ] && cat $(RUN_ID_FILE) || echo logs_$$(date +%Y%m%d_%H%M%S) ); \
	echo $$RUN_ID_VALUE > $(RUN_ID_FILE); \
	export RUN_ID=$$RUN_ID_VALUE; \
	echo "[aracne_attack] Using RUN_ID=$$RUN_ID_VALUE"; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips ./outputs/$$RUN_ID_VALUE/aracne ./outputs/$$RUN_ID_VALUE/ghosts; \
	echo "[aracne_attack] Preparing ARACNE env"; \
	./scripts/prepare_aracne_env.sh; \
	opts=""; \
	for p in core defender attackers; do opts="$${opts} --profile $$p"; done; \
	echo "[aracne_attack] Ensuring core/defender are running (no recreate)"; \
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d --no-recreate --no-build router switch server compromised slips_defender; \
	echo "[aracne_attack] Starting ARACNE attacker"; \
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d --force-recreate --no-build aracne_attacker

clean:
	$(COMPOSE) down --rmi all --volumes --remove-orphans

# Target: ghosts_psql
# Usage: make ghosts_psql REPEATS=<num> DELAY=<seconds>
# Example: make ghosts_psql REPEATS=3 DELAY=2
# 
# Prerequisites: Run 'make up' first to initialize the infrastructure and RUN_ID
# 
# Parameters:
#   REPEATS: Number of times to repeat the workflow/timeline (default: 1)
#   DELAY: Delay in seconds between commands (default: 5)
#
# This target:
# 1. Uses existing RUN_ID from outputs/.current_run (created by 'make up')
# 2. Starts ghosts_driver container with adjusted timeline
# 3. Waits for execution to complete
# 4. Stops the container (logs are automatically copied by entrypoint.sh)
ghosts_psql:
	@REPEATS=$${REPEATS:-1}; \
	DELAY=$${DELAY:-5}; \
	echo "=== GHOSTS PostgreSQL Workflow ==="; \
	echo "Parameters:"; \
	echo "  - Repeats: $$REPEATS"; \
	echo "  - Delay between commands: $$DELAY seconds"; \
	echo ""; \
	if [ ! -f $(RUN_ID_FILE) ]; then \
		echo "✗ Error: RUN_ID not found. Please run 'make up' first to initialize the infrastructure."; \
		exit 1; \
	fi; \
	RUN_ID_VALUE=$$(cat $(RUN_ID_FILE)); \
	echo "[ghosts_psql] Using existing RUN_ID=$$RUN_ID_VALUE"; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/ghosts; \
	echo "[ghosts_psql] Output directory: ./outputs/$$RUN_ID_VALUE/ghosts"; \
	echo ""; \
	TIMELINE_SRC="images/ghosts_driver/john_scott_dummy/timeline_john_scott.json"; \
	NUM_COMMANDS=$$(grep -c '"Command":' $$TIMELINE_SRC || echo 6); \
	TOTAL_TIME=$$(($$REPEATS * $$NUM_COMMANDS * $$DELAY * 2 + 60)); \
	echo "[ghosts_psql] Estimated execution time: $$TOTAL_TIME seconds (~$$(($$TOTAL_TIME / 60)) minutes)"; \
	echo "  - Commands per cycle: $$NUM_COMMANDS"; \
	echo "  - Total cycles: $$REPEATS"; \
	echo "  - Delay per command: $$DELAY seconds"; \
	echo ""; \
	echo "[ghosts_psql] Starting ghosts_driver container..."; \
	RUN_ID=$$RUN_ID_VALUE GHOSTS_REPEATS=$$REPEATS GHOSTS_DELAY=$$DELAY $(COMPOSE) up -d ghosts_driver; \
	echo "✓ Container started: lab_ghosts_driver"; \
	echo ""; \
	echo "[ghosts_psql] Monitoring execution..."; \
	echo "  (You can watch logs with: docker logs -f lab_ghosts_driver)"; \
	echo ""; \
	sleep 5; \
	docker logs lab_ghosts_driver; \
	echo ""; \
	echo "[ghosts_psql] Waiting for execution to complete..."; \
	echo "  (Max wait time: $$TOTAL_TIME seconds)"; \
	ELAPSED=0; \
	while [ $$ELAPSED -lt $$TOTAL_TIME ]; do \
		if ! docker ps --filter "name=lab_ghosts_driver" --filter "status=running" | grep -q lab_ghosts_driver; then \
			echo "✓ Container has stopped (execution completed)"; \
			break; \
		fi; \
		sleep 10; \
		ELAPSED=$$(($$ELAPSED + 10)); \
		REMAINING=$$(($$TOTAL_TIME - $$ELAPSED)); \
		if [ $$(($$ELAPSED % 60)) -eq 0 ]; then \
			echo "  [$$ELAPSED/$$TOTAL_TIME seconds] Container still running ($$REMAINING seconds remaining)..."; \
		fi; \
	done; \
	echo ""; \
	echo "[ghosts_psql] Stopping ghosts_driver container..."; \
	docker stop lab_ghosts_driver 2>/dev/null || true; \
	echo "✓ Container stopped"; \
	echo ""; \
	echo "=== GHOSTS Execution Complete ==="; \
	echo "✓ Logs saved to: ./outputs/$$RUN_ID_VALUE/ghosts/"; \
	echo "✓ Timeline log: ./outputs/$$RUN_ID_VALUE/ghosts/clientupdates.log"; \
	echo ""; \
	if [ -f "./outputs/$$RUN_ID_VALUE/ghosts/clientupdates.log" ]; then \
		EVENTS=$$(grep -c "TIMELINE|" "./outputs/$$RUN_ID_VALUE/ghosts/clientupdates.log" 2>/dev/null || echo 0); \
		echo "📊 Statistics:"; \
		echo "  - Timeline events logged: $$EVENTS"; \
		echo "  - Log file size: $$(du -h ./outputs/$$RUN_ID_VALUE/ghosts/clientupdates.log 2>/dev/null | cut -f1 || echo '0')"; \
	fi
