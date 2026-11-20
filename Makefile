.PHONY: install test eval usecases ask serve
install:  ; pip install -r requirements-dev.txt
test:     ; pytest -q
eval:     ; python evals/run_eval.py
usecases: ; python usecases/score_usecases.py
ask:      ; python -m copilot "How do I reset my password?" --groups all-employees
serve:    ; DEMO_AUTH=1 uvicorn copilot.api:app --reload
