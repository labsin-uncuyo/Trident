COMPOSE ?= docker compose
PYTHON ?= python3

export COMPOSE_PROJECT_NAME := lab
RUN_ID_FILE := ./outputs/.current_run

.PHONY: generate build up down clean ssh_keys defend not_defend coder56 benign dashboard

generate:
	@echo "Generating docker-compose.yml from topology..."
	$(PYTHON) -m iac_engine --config topologies/lab_config.json --output docker-compose.yml

build: generate
	@echo "Building all compose services..."
	$(COMPOSE) build --pull --no-cache

up: generate
	@RUN_ID_VALUE=$${RUN_ID:-logs_$$(date +%Y%m%d_%H%M%S)}; \
	echo $$RUN_ID_VALUE > $(RUN_ID_FILE); \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips ./outputs/$$RUN_ID_VALUE/benign_agent; \
	export RUN_ID=$$RUN_ID_VALUE; \
	docker ps -aq --filter "name=^lab_" | xargs -r docker rm -f >/dev/null 2>&1 || true; \
	docker network rm net_a >/dev/null 2>&1 || true; \
	docker network rm net_b >/dev/null 2>&1 || true; \
	docker network rm egress >/dev/null 2>&1 || true; \
	opts="--profile core"; \
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d

down:
	$(COMPOSE) --profile core --profile defender down --volumes
	@rm -f $(RUN_ID_FILE)

dashboard:
	@echo "Building and starting dashboard..."
	$(COMPOSE) --profile core build lab_dashboard
	RUN_ID=$$(cat $(RUN_ID_FILE) 2>/dev/null || echo none) $(COMPOSE) --profile core up -d --no-recreate --no-build lab_router lab_server lab_compromised
	RUN_ID=$$(cat $(RUN_ID_FILE) 2>/dev/null || echo none) $(COMPOSE) --profile core up -d --force-recreate --build lab_dashboard
	@echo "✓ Dashboard running at http://localhost:8080"

ssh_keys:
	@echo "Setting up SSH keys for auto_responder..."
	./scripts/setup_ssh_keys_host.sh


defend:
	@if [ ! -f $(RUN_ID_FILE) ]; then \
		echo "✗ Error: RUN_ID not found. Please run 'make up' first to initialize the infrastructure."; \
		exit 1; \
	fi; \
	RUN_ID_VALUE=$$(cat $(RUN_ID_FILE)); \
	echo "[defend] Using RUN_ID=$$RUN_ID_VALUE"; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips ./outputs/$$RUN_ID_VALUE/benign_agent; \
	opts="--profile core --profile defender"; \
	echo "[defend] Starting defender components"; \
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d --no-recreate --no-build lab_router lab_server lab_compromised lab_slips_defender; \
	echo "[defend] Setting up SSH keys for auto_responder..."; \
	./scripts/setup_ssh_keys_host.sh

not_defend:
	@echo "[not_defend] Stopping defender components (containers stay present)"
	$(COMPOSE) --profile defender stop lab_slips_defender || true

clean:
	$(COMPOSE) down --rmi all --volumes --remove-orphans

coder56:
	@goal="$(filter-out $@,$(MAKECMDGOALS))"; \
	if [ -z "$$goal" ]; then \
		echo "Usage: make coder56 \"<goal text>\""; \
		exit 1; \
	fi; \
	RUN_ID_VALUE=$$(cat $(RUN_ID_FILE) 2>/dev/null || echo "manual"); \
	mkdir -p ./outputs/$$RUN_ID_VALUE/coder56; \
	nohup $(PYTHON) ./scripts/attacker_opencode_interactive.py $$goal > /dev/null 2>&1 & \
	echo "[coder56] Started in background (PID=$$!)"

# Usage:
#   make benign                          # default goal, no time limit
#   make benign TIME_LIMIT=900           # default goal, 900s limit
#   make benign GOAL="my goal"           # custom goal, no time limit
#   make benign GOAL="my goal" TIME_LIMIT=900
GOAL ?=
TIME_LIMIT ?=

benign:
	@if [ ! -f $(RUN_ID_FILE) ]; then \
		echo "✗ Error: RUN_ID not found. Please run 'make up' first to initialize the infrastructure."; \
		exit 1; \
	fi; \
	RUN_ID_VALUE=$$(cat $(RUN_ID_FILE)); \
	echo "[benign] Starting db_admin agent with RUN_ID=$$RUN_ID_VALUE"; \
	if [ -n "$(GOAL)" ]; then \
		echo "[benign] Goal: $(GOAL)"; \
	else \
		echo "[benign] Using default goal"; \
	fi; \
	if [ -n "$(TIME_LIMIT)" ]; then \
		echo "[benign] Time limit: $(TIME_LIMIT) seconds"; \
	else \
		echo "[benign] Time limit: None (run until manually stopped)"; \
	fi; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/benign_agent; \
	export RUN_ID=$$RUN_ID_VALUE; \
	cmd="python /workspace/images/compromised/db_admin_opencode_client.py"; \
	if [ -n "$(GOAL)" ]; then \
		cmd="$$cmd \"$(GOAL)\""; \
	fi; \
	if [ -n "$(TIME_LIMIT)" ]; then \
		cmd="$$cmd --time-limit $(TIME_LIMIT)"; \
	fi; \
	docker run --rm \
		--network lab_net_a \
		-e RUN_ID=$$RUN_ID_VALUE \
		-v "$$(pwd)":/workspace \
		-w /workspace \
		lab/dashboard:latest \
		sh -lc "$$cmd"

.PHONY: benign-run
benign-run:
	@:

%:
	@:
