# Repo-level shortcuts. Lesson-level targets live in each lesson's own Makefile.
TRACKER := uv run python scripts/tracker.py
LESSONS := $(sort $(dir $(wildcard modules/*/*/Makefile)))

.PHONY: plan status due dashboard validate test-all

plan:
	@$(TRACKER) plan

status:
	@$(TRACKER) status

due:
	@$(TRACKER) due

dashboard:
	@uv run python scripts/build_dashboard.py

validate:
	@$(TRACKER) validate

# Run every lesson's tests (starts and stops Docker infra per lesson).
test-all:
	@set -e; for d in $(LESSONS); do \
		echo "== $$d"; $(MAKE) -s -C $$d up test down; \
	done
