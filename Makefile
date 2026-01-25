COMPOSE ?= docker compose
PYTHON ?= python3

export COMPOSE_PROJECT_NAME := lab
RUN_ID_FILE := ./outputs/.current_run

.PHONY: build up down verify clean ssh_keys aracne_attack ghosts_psql defend not_defend coder56 benign

build:
	@echo "Building all compose services (including defender/benign/attacker)..."
	$(COMPOSE) build --pull --no-cache

up:
	@RUN_ID_VALUE=$${RUN_ID:-logs_$$(date +%Y%m%d_%H%M%S)}; \
	echo $$RUN_ID_VALUE > $(RUN_ID_FILE); \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips ./outputs/$$RUN_ID_VALUE/aracne ./outputs/$$RUN_ID_VALUE/ghosts ./outputs/$$RUN_ID_VALUE/benign_agent; \
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
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips ./outputs/$$RUN_ID_VALUE/aracne ./outputs/$$RUN_ID_VALUE/ghosts ./outputs/$$RUN_ID_VALUE/benign_agent; \
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
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips ./outputs/$$RUN_ID_VALUE/aracne ./outputs/$$RUN_ID_VALUE/ghosts ./outputs/$$RUN_ID_VALUE/benign_agent; \
	opts="--profile core --profile defender"; \
	echo "[defend] Starting defender components"; \
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d --no-recreate --no-build router server compromised slips_defender; \
	echo "[defend] Setting up SSH keys for auto_responder..."; \
	./scripts/setup_ssh_keys_host.sh

not_defend:
	@echo "[not_defend] Stopping defender components (containers stay present)"
	$(COMPOSE) --profile defender stop slips_defender switch || true

clean:
	$(COMPOSE) down --rmi all --volumes --remove-orphans

coder56:
	@goal="$(filter-out $@,$(MAKECMDGOALS))"; \
	if [ -z "$$goal" ]; then \
		echo "Usage: make coder56 \"<goal text>\""; \
		exit 1; \
	fi; \
	$(PYTHON) ./scripts/attacker_opencode_interactive.py $$goal

benign:
	@goal="$(filter-out $@,$(MAKECMDGOALS))"; \
	if [ -z "$$goal" ]; then \
		echo "Usage: make benign \"<goal text>\""; \
		echo "Example: make benign \"Perform morning database checks\""; \
		exit 1; \
	fi; \
	if [ ! -f $(RUN_ID_FILE) ]; then \
		echo "✗ Error: RUN_ID not found. Please run 'make up' first to initialize the infrastructure."; \
		exit 1; \
	fi; \
	RUN_ID_VALUE=$$(cat $(RUN_ID_FILE)); \
	echo "[benign] Starting db_admin agent with RUN_ID=$$RUN_ID_VALUE"; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/benign_agent; \
	export RUN_ID=$$RUN_ID_VALUE; \
	$(PYTHON) ./images/compromised/db_admin_logger.py "$$goal" --timeout 120

%:
	@:
