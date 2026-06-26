COMPOSE ?= docker compose
PYTHON ?= python3

export COMPOSE_PROJECT_NAME := lab
RUN_ID_FILE := ./outputs/.current_run

.PHONY: build up down clean ssh_keys aracne defend not_defend coder56 benign dashboard config

build:
	@echo "Building all compose services..."
	$(COMPOSE) --profile core --profile defender build --pull --no-cache

up:
	@mkdir -p ./outputs; \
	RUN_ID_VALUE=$${RUN_ID:-logs_$$(date +%Y%m%d_%H%M%S)}; \
	echo $$RUN_ID_VALUE > $(RUN_ID_FILE); \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips ./outputs/$$RUN_ID_VALUE/aracne ./outputs/$$RUN_ID_VALUE/benign_agent; \
	export RUN_ID=$$RUN_ID_VALUE; \
	docker ps -aq --filter "name=^lab_" | xargs -r docker rm -f >/dev/null 2>&1 || true; \
	docker network rm lab_net_a >/dev/null 2>&1 || true; \
	docker network rm lab_net_b >/dev/null 2>&1 || true; \
	docker network rm lab_egress >/dev/null 2>&1 || true; \
	opts="--profile core"; \
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d

down:
	$(COMPOSE) --profile core --profile attackers --profile defender down --volumes
	@rm -f $(RUN_ID_FILE)

DASHBOARD_BUILD_MARKER := .dashboard_build_marker

# Frontend files that trigger a rebuild
FRONTEND_FILES := $(shell find images/dashboard/frontend/src -type f -name '*.tsx' -o -name '*.ts' 2>/dev/null)
FRONTEND_CONFIG := $(shell ls images/dashboard/frontend/package.json images/dashboard/frontend/vite.config.ts images/dashboard/frontend/tsconfig.json 2>/dev/null)

dashboard:
	@echo "Starting dashboard..."
	@RUN_ID=$$(cat $(RUN_ID_FILE) 2>/dev/null || echo none); \
	needs_build=0; \
	 marker_content=""; \
	if [ -f $(DASHBOARD_BUILD_MARKER) ]; then \
		current_content=$$(find images/dashboard/frontend/src images/dashboard/frontend/package.json images/dashboard/frontend/vite.config.ts images/dashboard/frontend/tsconfig.json -type f -exec stat -c "%Y %n" {} \; 2>/dev/null | sort | md5sum | cut -d' ' -f1); \
		stored_content=$$(cat $(DASHBOARD_BUILD_MARKER) 2>/dev/null); \
		if [ "$$current_content" != "$$stored_content" ]; then \
			echo "Frontend files changed, rebuilding..."; \
			needs_build=1; \
		fi; \
	else \
		echo "No build marker found, building..."; \
		needs_build=1; \
	fi; \
	if [ $$needs_build -eq 1 ]; then \
		echo "Building dashboard image..."; \
		$(COMPOSE) --profile core build dashboard; \
		find images/dashboard/frontend/src images/dashboard/frontend/package.json images/dashboard/frontend/vite.config.ts images/dashboard/frontend/tsconfig.json -type f -exec stat -c "%Y %n" {} \; 2>/dev/null | sort | md5sum | cut -d' ' -f1 > $(DASHBOARD_BUILD_MARKER); \
		echo "✓ Build complete"; \
	else \
		echo "✓ Using cached dashboard image (no frontend changes)"; \
	fi; \
	echo "Starting containers..."; \
	$(COMPOSE) --profile core up -d --no-recreate --no-build router server compromised 2>/dev/null || true; \
	if [ $$needs_build -eq 1 ]; then \
		RUN_ID=$$RUN_ID $(COMPOSE) --profile core up -d --force-recreate dashboard; \
	else \
		RUN_ID=$$RUN_ID $(COMPOSE) --profile core up -d --no-recreate dashboard 2>/dev/null || \
		RUN_ID=$$RUN_ID $(COMPOSE) --profile core up -d dashboard; \
	fi; \
	echo "✓ Dashboard running at http://localhost:8888"

CONFIG_BUILD_MARKER := .config_build_marker

config:
	@echo "Starting config app..."
	@needs_build=0; \
	if [ -f $(CONFIG_BUILD_MARKER) ]; then \
		current_content=$$(find images/config_app/frontend/src images/config_app/frontend/package.json images/config_app/frontend/vite.config.ts images/config_app/frontend/tsconfig.json images/config_app/backend -type f -exec stat -c "%Y %n" {} \; 2>/dev/null | sort | md5sum | cut -d' ' -f1); \
		stored_content=$$(cat $(CONFIG_BUILD_MARKER) 2>/dev/null); \
		if [ "$$current_content" != "$$stored_content" ]; then \
			echo "Config app files changed, rebuilding..."; \
			needs_build=1; \
		fi; \
	else \
		echo "No build marker found, building..."; \
		needs_build=1; \
	fi; \
	if [ $$needs_build -eq 1 ]; then \
		echo "Building config image..."; \
		$(COMPOSE) --profile core build config; \
		find images/config_app/frontend/src images/config_app/frontend/package.json images/config_app/frontend/vite.config.ts images/config_app/frontend/tsconfig.json images/config_app/backend -type f -exec stat -c "%Y %n" {} \; 2>/dev/null | sort | md5sum | cut -d' ' -f1 > $(CONFIG_BUILD_MARKER); \
		echo "✓ Build complete"; \
	else \
		echo "✓ Using cached config image (no changes)"; \
	fi; \
	echo "Starting config app..."; \
	$(COMPOSE) --profile core rm -sf config 2>/dev/null || true; \
	$(COMPOSE) --profile core up -d config; \
	echo "✓ Config app running at http://localhost:8889"

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
	RUN_ID=$$RUN_ID_VALUE $(COMPOSE) $${opts} up -d --no-build router server compromised slips_defender; \
	echo "[defend] Setting up SSH keys for auto_responder..."; \
	./scripts/setup_ssh_keys_host.sh

not_defend:
	@echo "[not_defend] Stopping defender components (containers stay present)"
	$(COMPOSE) --profile defender stop slips_defender|| true

clean:
	$(COMPOSE) --profile core --profile defender --profile attackers down --rmi all --volumes --remove-orphans
	docker image prune -f

coder56:
	@goal="$(filter-out $@,$(MAKECMDGOALS))"; \
	if [ -z "$$goal" ]; then \
		echo "Usage: make coder56 \"<goal text>\""; \
		exit 1; \
	fi; \
	RUN_ID_VALUE=$$(cat $(RUN_ID_FILE) 2>/dev/null || echo "manual"); \
	echo "[coder56] Starting with RUN_ID=$$RUN_ID_VALUE"; \
	echo "[coder56] Goal: $$goal"; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/coder56; \
	docker exec \
		-e RUN_ID=$$RUN_ID_VALUE \
		-e TRIDENT_HOME=/ \
		lab_compromised \
		sh -c "python3 /scripts/coder56_opencode_client.py \"$$goal\""

# Usage:
#   make benign                          # default goal, natural completion (no time limit)
#   make benign MAX_WAIT=1800            # natural completion, 30min safety backstop
#   make benign GOAL="my goal"           # custom goal, natural completion
#   make benign GOAL="my goal" MAX_WAIT=600
#   make benign-timed TIME_LIMIT=900     # old behavior: forced time limit
GOAL ?=
MAX_WAIT ?= 3600

benign:
	@if [ ! -f $(RUN_ID_FILE) ]; then \
		echo "✗ Error: RUN_ID not found. Please run 'make up' first to initialize the infrastructure."; \
		exit 1; \
	fi; \
	RUN_ID_VALUE=$$(cat $(RUN_ID_FILE)); \
	echo "[benign] Starting db_admin agent (natural completion) with RUN_ID=$$RUN_ID_VALUE"; \
	if [ -n "$(GOAL)" ]; then \
		echo "[benign] Goal: $(GOAL)"; \
	else \
		echo "[benign] Using default goal"; \
	fi; \
	echo "[benign] Max wait (safety backstop): $(MAX_WAIT)s"; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/benign_agent; \
	cmd="python3 /opt/db_admin_natural.py --max-wait $(MAX_WAIT)"; \
	if [ -n "$(GOAL)" ]; then \
		cmd="$$cmd \"$(GOAL)\""; \
	fi; \
	docker exec \
		-e RUN_ID=$$RUN_ID_VALUE \
		-e TRIDENT_HOME=/ \
		lab_compromised \
		sh -c "$$cmd"

# Legacy time-limited benign agent (kept for backward compatibility)
TIME_LIMIT ?=

benign-timed:
	@if [ ! -f $(RUN_ID_FILE) ]; then \
		echo "✗ Error: RUN_ID not found. Please run 'make up' first to initialize the infrastructure."; \
		exit 1; \
	fi; \
	RUN_ID_VALUE=$$(cat $(RUN_ID_FILE)); \
	echo "[benign-timed] Starting db_admin agent (time-limited) with RUN_ID=$$RUN_ID_VALUE"; \
	if [ -n "$(GOAL)" ]; then \
		echo "[benign-timed] Goal: $(GOAL)"; \
	else \
		echo "[benign-timed] Using default goal"; \
	fi; \
	if [ -n "$(TIME_LIMIT)" ]; then \
		echo "[benign-timed] Time limit: $(TIME_LIMIT) seconds"; \
	else \
		echo "[benign-timed] Time limit: None (run until manually stopped)"; \
	fi; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/benign_agent; \
	cmd="python3 /opt/db_admin_opencode_client.py"; \
	if [ -n "$(GOAL)" ]; then \
		cmd="$$cmd \"$(GOAL)\""; \
	fi; \
	if [ -n "$(TIME_LIMIT)" ]; then \
		cmd="$$cmd --time-limit $(TIME_LIMIT)"; \
	fi; \
	docker exec \
		-e RUN_ID=$$RUN_ID_VALUE \
		-e TRIDENT_HOME=/ \
		lab_compromised \
		sh -c "$$cmd"

.PHONY: benign-run benign-natural benign-timed
benign-run:
	@:

# Alias for backward compatibility
benign-natural: benign

%:
	@:
