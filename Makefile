COMPOSE ?= docker compose
PYTHON ?= python3

export COMPOSE_PROJECT_NAME := lab
RUN_ID_FILE := ./outputs/.current_run

.PHONY: build up down clean ssh_keys aracne defend not_defend coder56 benign

build:
	@echo "Building all compose services (including defender/benign/attacker)..."
	$(COMPOSE) build --pull --no-cache

up:
	@RUN_ID_VALUE=$${RUN_ID:-logs_$$(date +%Y%m%d_%H%M%S)}; \
	echo $$RUN_ID_VALUE > $(RUN_ID_FILE); \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips ./outputs/$$RUN_ID_VALUE/aracne ./outputs/$$RUN_ID_VALUE/benign_agent; \
	export RUN_ID=$$RUN_ID_VALUE; \
	docker ps -aq --filter "name=^lab_" | xargs -r docker rm -f >/dev/null 2>&1 || true; \
	docker network rm lab_net_a >/dev/null 2>&1 || true; \
	docker network rm lab_net_b >/dev/null 2>&1 || true; \
	opts="--profile core"; \
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d

down:
	$(COMPOSE) --profile core --profile attackers --profile defender down --volumes
	@rm -f $(RUN_ID_FILE)

ssh_keys:
	@echo "Setting up SSH keys for auto_responder..."
	./scripts/setup_ssh_keys_host.sh

aracne:
	@goal="$(filter-out $@,$(MAKECMDGOALS))"; \
	if [ -z "$$goal" ]; then \
		echo "Usage: make aracne \"<goal text>\""; \
		exit 1; \
	fi; \
	if [ ! -f $(RUN_ID_FILE) ]; then \
		echo "✗ Error: RUN_ID not found. Please run 'make up' first to initialize the infrastructure."; \
		exit 1; \
	fi; \
	RUN_ID_VALUE=$$(cat $(RUN_ID_FILE)); \
	echo $$RUN_ID_VALUE > $(RUN_ID_FILE); \
	export RUN_ID=$$RUN_ID_VALUE; \
	echo "[aracne] Using RUN_ID=$$RUN_ID_VALUE"; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips ./outputs/$$RUN_ID_VALUE/aracne ./outputs/$$RUN_ID_VALUE/benign_agent; \
	echo "[aracne] Preparing ARACNE env"; \
	./scripts/prepare_aracne_env.sh; \
	if ! docker image inspect lab/aracne:latest >/dev/null 2>&1; then \
		echo "[aracne] Building lab/aracne image..."; \
		$(COMPOSE) --profile core --profile attackers build --pull aracne_attacker; \
	fi; \
	opts="--profile core --profile attackers"; \
	echo "[aracne] Ensuring core is running (no recreate)"; \
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d --no-recreate --no-build router server compromised; \
	echo "[aracne] Starting ARACNE attacker"; \
	RUN_ID=$$RUN_ID_VALUE GOAL="$$goal" $(COMPOSE) $${opts} up -d --force-recreate --no-build aracne_attacker

defend:
	@if [ ! -f $(RUN_ID_FILE) ]; then \
		echo "✗ Error: RUN_ID not found. Please run 'make up' first to initialize the infrastructure."; \
		exit 1; \
	fi; \
	RUN_ID_VALUE=$$(cat $(RUN_ID_FILE)); \
	echo "[defend] Using RUN_ID=$$RUN_ID_VALUE"; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips ./outputs/$$RUN_ID_VALUE/aracne ./outputs/$$RUN_ID_VALUE/benign_agent; \
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
	$(PYTHON) ./images/compromised/db_admin_logger.py "$$goal"

%:
	@:
