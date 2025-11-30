SERVICES := router switch compromised server
COMPOSE ?= docker compose
PYTHON ?= python3

export COMPOSE_PROJECT_NAME := lab

.PHONY: build up down verify slips_verify clean ssh_keys

build:
	@for svc in $(SERVICES); do \
		echo "Building $$svc"; \
		docker build -t lab/$$svc:latest images/$$svc; \
	done
	@echo "Pulling slips_defender image"
	@docker pull stratosphereips/slips:latest

up:
	@RUN_ID_VALUE=$${RUN_ID:-run_local}; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips_output
	-@docker ps -aq --filter "name=^lab_" | xargs -r docker rm -f >/dev/null 2>&1 || true
	-@docker network rm lab_net_a >/dev/null 2>&1 || true
	-@docker network rm lab_net_b >/dev/null 2>&1 || true
	$(COMPOSE) up -d
	@echo "Setting up SSH keys for auto_responder..."
	./scripts/setup_ssh_keys_host.sh

down:
	$(COMPOSE) down --volumes

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
	@RUN_ID_VALUE=$${RUN_ID:-slips_verify_$$(date +%Y%m%d_%H%M%S)}; \
	export RUN_ID=$$RUN_ID_VALUE; \
	echo "[slips_verify] Using RUN_ID=$$RUN_ID_VALUE"; \
	echo "[slips_verify] Resetting lab"; \
	$(MAKE) down; \
	mkdir -p ./outputs/$$RUN_ID_VALUE/pcaps ./outputs/$$RUN_ID_VALUE/slips_output; \
	echo "[slips_verify] Bringing lab up"; \
	$(COMPOSE) up -d; \
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

clean:
	$(COMPOSE) down --rmi all --volumes --remove-orphans
