SERVICES := router switch compromised server slips_defender
COMPOSE ?= docker compose
PYTHON ?= python3

export COMPOSE_PROJECT_NAME := lab
RUN_ID_FILE := ./outputs/.current_run

.PHONY: build up down verify slips_verify clean ssh_keys aracne_attack

build:
	@for svc in $(SERVICES); do \
		echo "Building $$svc"; \
		docker build -t lab/$$svc:latest images/$$svc; \
	done
	@echo "Building aracne_attacker"
	$(COMPOSE) build aracne_attacker

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
