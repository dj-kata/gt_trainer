WUV ?= /mnt/c/Users/katao/.local/bin/uv.exe
APP_NAME := gt_trainer
DIST_DIR := dist/$(APP_NAME)

.PHONY: help sync test check run build clean

help:
	@echo "make sync   - Windows uvで開発・ビルド依存関係を同期"
	@echo "make test   - Windows uvでテストを実行"
	@echo "make check  - 構文チェックとテストを実行"
	@echo "make run    - Windows版アプリを起動"
	@echo "make build  - cx_Freezeで $(DIST_DIR) を生成"
	@echo "make clean  - 生成したbuild/distを削除"

sync:
	@$(WUV) sync --extra dev --extra build

test:
	@$(WUV) run --extra dev pytest -q

check:
	@$(WUV) run --extra dev python -m compileall -q src tests setup.py guitar_trainer.pyw
	@$(WUV) run --extra dev pytest -q

run:
	@$(WUV) run python guitar_trainer.pyw

build:
	@rm -rf $(DIST_DIR)
	@$(WUV) run --extra build python setup.py build_exe
	@echo "Build complete: $(DIST_DIR)/GuitarTrainer.exe"

clean:
	@rm -rf build dist

