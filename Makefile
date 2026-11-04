# Shortcuts for dev.py. Every target is one line, so you can also run dev.py directly:
#   python dev.py help
# macOS / Linux where the command is python3:  make PY=python3 setup
PY ?= python
Q  ?= Am I over budget this month?
WHO ?= 1

.PHONY: help setup setup-here check check-gateway test pull pull-all ask persona personas eval eval-persona eval-gateway clean serve coach-secret demo-seed demo-remove demo-status demo-reader-sql demo-up app-up app-finance app-coach uat-up uat-report

UAT_DATE ?= 2026-11-04

help:
	@$(PY) dev.py help

setup:
	@$(PY) dev.py setup

setup-here:
	@$(PY) dev.py setup --here

check:
	@$(PY) dev.py check

check-gateway:
	@$(PY) dev.py check --gateway

test:
	@$(PY) dev.py test

pull:
	@$(PY) dev.py pull

pull-all:
	@$(PY) dev.py pull --all

# make ask Q="How much did I spend on food in July?"
ask:
	@$(PY) dev.py ask "$(Q)"

# make persona WHO=3 Q="Am I over budget this month?"
persona:
	@$(PY) dev.py persona --user $(WHO) "$(Q)"

personas:
	@$(PY) dev.py persona --list

eval:
	@$(PY) dev.py eval

eval-persona:
	@$(PY) dev.py eval-persona

eval-gateway:
	@$(PY) dev.py eval-gateway

clean:
	@$(PY) dev.py clean

serve:
	@$(PY) dev.py serve

coach-secret:
	@$(PY) dev.py coach-secret

demo-seed:
	@$(PY) dev.py demo-seed

demo-remove:
	@$(PY) dev.py demo-remove

demo-status:
	@$(PY) dev.py demo-status

demo-reader-sql:
	@$(PY) dev.py demo-reader-sql

# Seed (dry run unless YES=1) then start the coach server.
demo-up:
	@$(PY) dev.py demo-seed $(if $(YES),--yes,)
	@$(PY) dev.py serve

# From the parent workspace: make -C b-buddy app-up
# Start Ollama separately; Ctrl-C here stops the app and coach processes.
app-up:
	@$(MAKE) -j2 app-finance app-coach

app-finance:
	@$(MAKE) -C ../finance-tracker dev

app-coach:
	@$(PY) dev.py serve

# One terminal for the integrated app and the live UAT report. Ctrl-C stops all watchers.
uat-up:
	@$(MAKE) -j2 app-up uat-report

uat-report:
	@$(PY) Harness/scripts/uat_report.py --date $(UAT_DATE) --watch
