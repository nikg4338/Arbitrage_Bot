.PHONY: api-install web-install api-dev web-dev dev test

api-install:
	cd apps/api && python3 -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -r requirements.txt

web-install:
	cd apps/web && npm install

api-dev:
	cd apps/api && . .venv/bin/activate && uvicorn main:app --reload --port 8000

web-dev:
	cd apps/web && npm run dev

dev:
	@echo "Run in two terminals:"
	@echo "  1) make api-dev"
	@echo "  2) make web-dev"

test:
	cd apps/api && . .venv/bin/activate && pytest ../../tests -q
