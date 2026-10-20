# Lesson Makefile — copy into each lesson folder unchanged.
COMPOSE := $(wildcard docker-compose.yml)

.PHONY: up run test down

up:
ifneq ($(COMPOSE),)
	docker compose up -d --wait
else
	@echo "no infrastructure needed for this lesson"
endif

run:
	uv run python -m src.demo

test:
	uv run python -m pytest tests

down:
ifneq ($(COMPOSE),)
	docker compose down -v
else
	@echo "nothing to stop"
endif
