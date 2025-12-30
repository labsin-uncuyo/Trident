COMPOSE ?= docker compose
PYTHON ?= python3

export COMPOSE_PROJECT_NAME := lab
RUN_ID_FILE := ./outputs/.current_run

.PHONY: build up down verify slips_verify clean ssh_keys aracne_attack ghosts_psql defend not_defend

build:
	@echo "Building all compose services (including defender/benign/attacker)..."
	$(COMPOSE) build --pull

up:
	@RUN_ID_VALUE=$${RUN_ID:-logs_$$(date +%Y%m%d_%H%M%S)}; \
	echo $$RUN_ID_VALUE > $(RUN_ID_FILE); \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips ./outputs/$$RUN_ID_VALUE/aracne ./outputs/$$RUN_ID_VALUE/ghosts; \
	export RUN_ID=$$RUN_ID_VALUE; \
	docker ps -aq --filter "name=^lab_" | xargs -r docker rm -f >/dev/null 2>&1 || true; \
	docker network rm lab_net_a >/dev/null 2>&1 || true; \
	docker network rm lab_net_b >/dev/null 2>&1 || true; \
	opts="--profile core"; \
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d

down:
	$(COMPOSE) down --volumes
	@rm -f $(RUN_ID_FILE)

verify:
	@echo "[verify] Waiting for full lab readiness..."
	./scripts/wait_for_lab_ready.sh
	@echo "[verify] Checking server HTTP from compromised -> server"
	docker exec lab_compromised curl -sf -o /dev/null http://172.31.0.10:80 && echo "[verify] Server reachable"
	@echo "[verify] Checking SLIPS API health (only if defender is running)"
	@DEFENDER_PORT_VALUE=$${DEFENDER_PORT:-}; \
	for env_file in ".env" ".env.example"; do \
		if [ -z "$${DEFENDER_PORT_VALUE}" ] && [ -f "$$env_file" ]; then \
			val=$$(grep -E '^DEFENDER_PORT=' "$$env_file" | tail -n1 | cut -d'=' -f2); \
			if [ -n "$$val" ]; then DEFENDER_PORT_VALUE="$$val"; fi; \
		fi; \
	done; \
	DEFENDER_PORT_VALUE=$${DEFENDER_PORT_VALUE:-8000}; \
	if docker ps --filter "name=lab_slips_defender" --format '{{.Names}}' | grep -q lab_slips_defender; then \
		curl -sf "http://localhost:$${DEFENDER_PORT_VALUE}/health" >/dev/null && echo "[verify] SLIPS API healthy"; \
	else \
		echo "[verify] Defender not running (skip health check)"; \
	fi
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
	opts="--profile core --profile defender"; \
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
	@if [ ! -f $(RUN_ID_FILE) ]; then \
		echo "✗ Error: RUN_ID not found. Please run 'make up' first to initialize the infrastructure."; \
		exit 1; \
	fi; \
	RUN_ID_VALUE=$$(cat $(RUN_ID_FILE)); \
	echo $$RUN_ID_VALUE > $(RUN_ID_FILE); \
	export RUN_ID=$$RUN_ID_VALUE; \
	echo "[aracne_attack] Using RUN_ID=$$RUN_ID_VALUE"; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips ./outputs/$$RUN_ID_VALUE/aracne ./outputs/$$RUN_ID_VALUE/ghosts; \
	echo "[aracne_attack] Preparing ARACNE env"; \
	./scripts/prepare_aracne_env.sh; \
	if ! docker image inspect lab/aracne:latest >/dev/null 2>&1; then \
		echo "[aracne_attack] Building lab/aracne image..."; \
		$(COMPOSE) --profile core --profile attackers build --pull aracne_attacker; \
	fi; \
	opts="--profile core --profile attackers"; \
	echo "[aracne_attack] Ensuring core is running (no recreate)"; \
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d --no-recreate --no-build router server compromised; \
	echo "[aracne_attack] Starting ARACNE attacker"; \
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d --force-recreate --no-build aracne_attacker

defend:
	@if [ ! -f $(RUN_ID_FILE) ]; then \
		echo "✗ Error: RUN_ID not found. Please run 'make up' first to initialize the infrastructure."; \
		exit 1; \
	fi; \
	RUN_ID_VALUE=$$(cat $(RUN_ID_FILE)); \
	echo "[defend] Using RUN_ID=$$RUN_ID_VALUE"; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips ./outputs/$$RUN_ID_VALUE/aracne ./outputs/$$RUN_ID_VALUE/ghosts; \
	opts="--profile core --profile defender"; \
	echo "[defend] Starting defender components"; \
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d --no-recreate --no-build router server compromised switch slips_defender; \
	echo "[defend] Setting up SSH keys for auto_responder..."; \
	./scripts/setup_ssh_keys_host.sh

not_defend:
	@echo "[not_defend] Stopping defender components (containers stay present)"
	$(COMPOSE) --profile defender stop slips_defender switch || true

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
	RUN_ID=$$RUN_ID_VALUE GHOSTS_REPEATS=$$REPEATS GHOSTS_DELAY=$$DELAY $(COMPOSE) --profile core --profile benign up -d --no-recreate --no-build router server compromised; \
	RUN_ID=$$RUN_ID_VALUE GHOSTS_REPEATS=$$REPEATS GHOSTS_DELAY=$$DELAY $(COMPOSE) --profile core --profile benign up -d ghosts_driver; \
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
	echo "[ghosts_psql] Copying logs from container..."; \
	if docker cp lab_ghosts_driver:/opt/ghosts/bin/logs "./outputs/$$RUN_ID_VALUE/ghosts_tmp" 2>/dev/null; then \
		mkdir -p "./outputs/$$RUN_ID_VALUE/ghosts"; \
		cp -r "./outputs/$$RUN_ID_VALUE/ghosts_tmp/"* "./outputs/$$RUN_ID_VALUE/ghosts/" 2>/dev/null || true; \
		rm -rf "./outputs/$$RUN_ID_VALUE/ghosts_tmp"; \
		echo "✓ Logs copied to ./outputs/$$RUN_ID_VALUE/ghosts/"; \
	else \
		echo "✗ Failed to copy logs from lab_ghosts_driver (container missing or no logs)."; \
	fi; \
	ls -lh "./outputs/$$RUN_ID_VALUE/ghosts/" 2>/dev/null || true; \
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

# Target: ghosts_psql_llm
# Usage: make ghosts_psql_llm NUM_QUERIES=<num> SCENARIO=<type> ROLE=<db_role> DELAY=<seconds>
# Example: make ghosts_psql_llm NUM_QUERIES=10 SCENARIO=hr_audit ROLE=senior_developer_role DELAY=3
# 
# Prerequisites: 
#   - Run 'make up' first to initialize the infrastructure and RUN_ID
#   - OPENCODE_API_KEY must be set in .env file
# 
# Parameters:
#   NUM_QUERIES: Number of SQL queries to generate via LLM (default: 5)
#   SCENARIO: Scenario type - developer_routine, hr_audit, performance_review, exploratory (default: developer_routine)
#   ROLE: Database role name (determines permissions and behavior, default: senior_developer_role)
#   DELAY: Base delay in seconds between commands (default: 5, varies slightly for realism)
#
# This target:
# 1. Uses LLM (OpenCode) to dynamically generate SQL queries based on scenario and role
# 2. Creates GHOSTS timeline with generated queries
# 3. Executes timeline via ghosts_driver container
# 4. Logs are automatically saved to outputs/
ghosts_psql_llm:
	@NUM_QUERIES=$${NUM_QUERIES:-5}; \
	SCENARIO=$${SCENARIO:-developer_routine}; \
	ROLE=$${ROLE:-senior_developer_role}; \
	DELAY=$${DELAY:-5}; \
	echo "=== GHOSTS PostgreSQL Workflow (LLM-Driven) ==="; \
	echo "Parameters:"; \
	echo "  - Number of queries: $$NUM_QUERIES"; \
	echo "  - Scenario: $$SCENARIO"; \
	echo "  - Database Role: $$ROLE"; \
	echo "  - Delay between commands: $$DELAY seconds"; \
	echo ""; \
	if [ ! -f $(RUN_ID_FILE) ]; then \
		echo "✗ Error: RUN_ID not found. Please run 'make up' first to initialize the infrastructure."; \
		exit 1; \
	fi; \
	if ! grep -q "OPENCODE_API_KEY=" .env 2>/dev/null; then \
		echo "✗ Error: OPENCODE_API_KEY not found in .env file"; \
		exit 1; \
	fi; \
	RUN_ID_VALUE=$$(cat $(RUN_ID_FILE)); \
	echo "[ghosts_psql_llm] Using existing RUN_ID=$$RUN_ID_VALUE"; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/ghosts; \
	echo "[ghosts_psql_llm] Output directory: ./outputs/$$RUN_ID_VALUE/ghosts"; \
	echo ""; \
	DELAY_MS=$$(($$DELAY * 1000)); \
	TOTAL_TIME=$$(($$NUM_QUERIES * $$DELAY * 2 + 60)); \
	echo "[ghosts_psql_llm] Estimated execution time: $$TOTAL_TIME seconds (~$$(($$TOTAL_TIME / 60)) minutes)"; \
	echo "  - Queries to generate: $$NUM_QUERIES"; \
	echo "  - Scenario: $$SCENARIO"; \
	echo "  - Database Role: $$ROLE"; \
	echo "  - Delay per command: $$DELAY seconds"; \
	echo ""; \
	echo "[ghosts_psql_llm] Starting ghosts_driver container with LLM timeline generation..."; \
	RUN_ID=$$RUN_ID_VALUE GHOSTS_MODE=llm GHOSTS_NUM_QUERIES=$$NUM_QUERIES GHOSTS_SCENARIO=$$SCENARIO GHOSTS_ROLE=$$ROLE GHOSTS_DELAY=$$DELAY $(COMPOSE) --profile core --profile benign up -d --no-recreate --no-build router server compromised; \
	RUN_ID=$$RUN_ID_VALUE GHOSTS_MODE=llm GHOSTS_NUM_QUERIES=$$NUM_QUERIES GHOSTS_SCENARIO=$$SCENARIO GHOSTS_ROLE=$$ROLE GHOSTS_DELAY=$$DELAY $(COMPOSE) --profile core --profile benign up -d ghosts_driver; \
	echo "✓ Container started: lab_ghosts_driver"; \
	echo ""; \
	echo "[ghosts_psql_llm] Monitoring execution..."; \
	echo "  (You can watch logs with: docker logs -f lab_ghosts_driver)"; \
	echo ""; \
	sleep 10; \
	docker logs lab_ghosts_driver; \
	echo ""; \
	echo "[ghosts_psql_llm] Waiting for execution to complete..."; \
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
	echo "[ghosts_psql_llm] Stopping ghosts_driver container..."; \
	docker stop lab_ghosts_driver 2>/dev/null || true; \
	echo "✓ Container stopped"; \
	echo ""; \
	echo "[ghosts_psql_llm] Copying logs from container..."; \
	if docker cp lab_ghosts_driver:/opt/ghosts/bin/logs "./outputs/$$RUN_ID_VALUE/ghosts_tmp" 2>/dev/null; then \
		mkdir -p "./outputs/$$RUN_ID_VALUE/ghosts"; \
		cp -r "./outputs/$$RUN_ID_VALUE/ghosts_tmp/"* "./outputs/$$RUN_ID_VALUE/ghosts/" 2>/dev/null || true; \
		rm -rf "./outputs/$$RUN_ID_VALUE/ghosts_tmp"; \
		echo "✓ Logs copied to ./outputs/$$RUN_ID_VALUE/ghosts/"; \
	else \
		echo "✗ Failed to copy logs from lab_ghosts_driver (container missing or no logs)."; \
	fi; \
	if docker cp lab_ghosts_driver:/opt/ghosts/bin/config/timeline.json "./outputs/$$RUN_ID_VALUE/ghosts/timeline_generated.json" 2>/dev/null; then \
		echo "✓ Generated timeline copied to ./outputs/$$RUN_ID_VALUE/ghosts/timeline_generated.json"; \
	fi; \
	ls -lh "./outputs/$$RUN_ID_VALUE/ghosts/" 2>/dev/null || true; \
	echo ""; \
	echo "=== GHOSTS LLM Execution Complete ==="; \
	echo "✓ Logs saved to: ./outputs/$$RUN_ID_VALUE/ghosts/"; \
	echo "✓ Timeline log: ./outputs/$$RUN_ID_VALUE/ghosts/clientupdates.log"; \
	echo "✓ Generated timeline: ./outputs/$$RUN_ID_VALUE/ghosts/timeline_generated.json"; \
	echo ""; \
	if [ -f "./outputs/$$RUN_ID_VALUE/ghosts/clientupdates.log" ]; then \
		EVENTS=$$(grep -c "TIMELINE|" "./outputs/$$RUN_ID_VALUE/ghosts/clientupdates.log" 2>/dev/null || echo 0); \
		echo "📊 Statistics:"; \
		echo "  - Timeline events logged: $$EVENTS"; \
		echo "  - Scenario: $$SCENARIO"; \
		echo "  - Database Role: $$ROLE"; \
		echo "  - LLM-generated queries: $$NUM_QUERIES"; \
		echo "  - Log file size: $$(du -h ./outputs/$$RUN_ID_VALUE/ghosts/clientupdates.log 2>/dev/null | cut -f1 || echo '0')"; \
	fi

