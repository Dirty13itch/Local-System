.PHONY: help up down restart logs dev test lint proto deploy health clean

NODE ?= hydra-storage
SERVICE ?= all
COMPOSE = docker compose
DEPLOY_COMPOSE = $(COMPOSE) -f deploy/$(NODE)/docker-compose.yml

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Local Development ---

dev: ## Run a service locally (SERVICE=gateway)
	cd services/$(SERVICE) && uvicorn main:app --reload --host 0.0.0.0

dev-ui: ## Run the Next.js UI in dev mode
	cd ui && npm run dev

install: ## Install all dependencies
	pip install -e shared/python[dev]
	cd ui && npm install

# --- Docker Operations ---

up: ## Start services on a node (NODE=hydra-storage)
	$(DEPLOY_COMPOSE) up -d

down: ## Stop services on a node (NODE=hydra-storage)
	$(DEPLOY_COMPOSE) down

restart: ## Restart services on a node (NODE=hydra-storage)
	$(DEPLOY_COMPOSE) restart

logs: ## View logs (NODE=hydra-storage SERVICE=gateway)
ifeq ($(SERVICE),all)
	$(DEPLOY_COMPOSE) logs -f --tail=100
else
	$(DEPLOY_COMPOSE) logs -f --tail=100 $(SERVICE)
endif

build: ## Build Docker images (NODE=hydra-storage)
	$(DEPLOY_COMPOSE) build

# --- Deployment ---

deploy: ## Deploy to a specific node (NODE=hydra-storage)
	@echo "Deploying to $(NODE)..."
	$(DEPLOY_COMPOSE) pull
	$(DEPLOY_COMPOSE) up -d --remove-orphans

deploy-all: ## Deploy to all nodes
	@for node in hydra-ai hydra-compute hydra-storage; do \
		echo "=== Deploying to $$node ==="; \
		$(COMPOSE) -f deploy/$$node/docker-compose.yml up -d --remove-orphans; \
	done

# --- Code Generation ---

proto: ## Generate gRPC stubs from proto files
	python -m grpc_tools.protoc \
		-I proto/ \
		--python_out=shared/python/local_system/proto \
		--grpc_python_out=shared/python/local_system/proto \
		--pyi_out=shared/python/local_system/proto \
		proto/*.proto
	@echo "Proto stubs generated."

# --- Testing ---

test: ## Run all tests
	pytest tests/ -v

test-unit: ## Run unit tests only
	pytest tests/ -v -m "not integration and not e2e"

test-integration: ## Run integration tests
	pytest tests/ -v -m integration

lint: ## Run linters
	ruff check .
	ruff format --check .
	mypy shared/python/local_system services/

format: ## Auto-format code
	ruff check --fix .
	ruff format .

# --- Health & Monitoring ---

health: ## Check health of all nodes
	@bash scripts/health-check.sh

status: ## Show running services on a node (NODE=hydra-storage)
	$(DEPLOY_COMPOSE) ps

# --- Cleanup ---

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .next -exec rm -rf {} + 2>/dev/null || true
