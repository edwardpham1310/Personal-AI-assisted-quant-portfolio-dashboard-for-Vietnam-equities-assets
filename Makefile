.PHONY: ai-context ai-context-src ai-check

ai-context:
	npx repomix

ai-context-src:
	npx repomix --include "src/**/*,datapipe/src/**/*,quant/src/**/*,datapipe/tests/**/*,quant/tests/**/*,tests/**/*,README.md,docs/**/*"

ai-check:
	@echo "Claude 1M context is disabled via .claude/settings.json"
	@echo "Agents must not read data/raw, data/processed, data/cache, db, package data directories, or generated context files"
