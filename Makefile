# Pre-push safety net: `make check` runs lint + the sync-logic test suite.
.PHONY: check lint test sync-assets

check: lint test

lint:
	ruff check .

test:
	python -m pytest tests/ -q

# Copy shared frontend assets (sfx.js, Tone.js, dice.js) into the relay repo.
sync-assets:
	scripts/sync_shared_assets.sh
