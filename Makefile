PACKAGE = .
PYTHON_DIRS := $(PACKAGE)


qa: analyze typecheck test

analyze:
	@echo "Running code analysis..."
	@uv run ruff check $(PYTHON_DIRS)

format:
	@echo "Formatting code..."
	@uv run ruff format $(PYTHON_DIRS)
	@uv run ruff check --fix $(PYTHON_DIRS)

lock:
	@echo "Updating dependency lock..."
	@uv run uv lock

typecheck:
	@echo "Running type checking..."
	@uv run ty check $(PYTHON_DIRS)

test:
	@echo "Running tests..."
	@uv run pytest $(TEST_DIR)

.PHONY: analyze \
				build-docker \
				format \
				lock \
				qa \
				test \
				typecheck \
				generate-api-schema
