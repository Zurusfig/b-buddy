# Shortcuts for dev.py. Every target is one line, so you can also run dev.py directly:
#   python dev.py help
# macOS / Linux where the command is python3:  make PY=python3 setup
PY ?= python
Q  ?= Am I over budget this month?
WHO ?= 1

.PHONY: help setup setup-here check check-gateway test pull pull-all ask persona personas eval eval-persona eval-gateway clean

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
