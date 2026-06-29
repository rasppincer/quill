#!/bin/bash
PIECE="the-ferret-protocol"
AGENT="fiction"
LOG=~/projects/quill/logs/ferret-run.log

echo "=== $(date) Starting full pipeline ===" | tee $LOG

run_stage() {
  local stage=$1
  echo "=== $(date +%H:%M:%S) Running $stage ===" | tee -a $LOG
  curl -s --max-time 3600 -X POST "http://localhost:8325/api/pieces/$PIECE/run" \
    -H "Content-Type: application/json" \
    -d "{\"stage\":\"$stage\",\"agent_set\":\"$AGENT\"}" >> $LOG 2>&1
  echo "" >> $LOG
  echo "=== $(date +%H:%M:%S) $stage done ===" | tee -a $LOG
}

# Advance to structure first
curl -s -X POST "http://localhost:8325/api/pieces/$PIECE/advance" > /dev/null 2>&1
run_stage "structure"
curl -s -X POST "http://localhost:8325/api/pieces/$PIECE/advance" > /dev/null 2>&1

run_stage "outline"
curl -s -X POST "http://localhost:8325/api/pieces/$PIECE/advance" > /dev/null 2>&1

run_stage "research"
curl -s -X POST "http://localhost:8325/api/pieces/$PIECE/advance" > /dev/null 2>&1

run_stage "draft"
curl -s -X POST "http://localhost:8325/api/pieces/$PIECE/advance" > /dev/null 2>&1

run_stage "review"
curl -s -X POST "http://localhost:8325/api/pieces/$PIECE/advance" > /dev/null 2>&1

run_stage "revise"
curl -s -X POST "http://localhost:8325/api/pieces/$PIECE/advance" > /dev/null 2>&1

run_stage "humanize"
curl -s -X POST "http://localhost:8325/api/pieces/$PIECE/advance" > /dev/null 2>&1

run_stage "validate"
curl -s -X POST "http://localhost:8325/api/pieces/$PIECE/advance" > /dev/null 2>&1

run_stage "polish"
curl -s -X POST "http://localhost:8325/api/pieces/$PIECE/advance" > /dev/null 2>&1

run_stage "state"

echo "" | tee -a $LOG
echo "=== $(date) Pipeline complete ===" | tee -a $LOG
