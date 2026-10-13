#!/bin/sh
# Ship the committed version to the live site. Every step must pass or nothing changes:
#   1. all tests (including the no-internet test, tests/test_offline.py);
#   2. the safety gate (tools/gate.py): a full practice run of this exact code with 0 wrong answers either way;
#   3. build the container on an arm64 builder (git archive HEAD: only committed files the Dockerfile uses);
#   4. start it with networking switched off and check both sample labels give the right answer;
#   5. only then point the Lambda at the new image, and check the live site.
# Needs: AWS CLI logged in; BUILDER=user@host of an arm64 machine with Docker; BUILDER_KEY=its ssh key.
# Usage: BUILDER=ec2-user@1.2.3.4 BUILDER_KEY=~/.ssh/key.pem sh tools/deploy.sh [out/eval/<run>.json]
set -e
cd "$(dirname "$0")/.."
PY=${PYTHON:-.venv/bin/python}
REGION=us-east-1; FN=alcohol-label-verification
REPO=739275480230.dkr.ecr.$REGION.amazonaws.com/alcohol-label-verification; TAG=$(git rev-parse --short HEAD)
URL=https://3jirlgdkpcw55t54gz32ggdnbq0yfrjp.lambda-url.$REGION.on.aws
b() { ssh -i "$BUILDER_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 "$BUILDER" "$@"; }

echo "--- 1. tests"
$PY -m pytest -q | tail -1
echo "--- 2. safety gate"
$PY tools/gate.py "$@"

echo "--- 3. build $TAG"
# Only what the Dockerfile copies: the test data in the repo is large and not part of the app.
git archive HEAD -- Dockerfile .dockerignore requirements.txt app tools/make_dynamic_det.py \
  data/synthetic/syn_spirits_00_none data/synthetic/syn_malt_01_warning_titlecase | b 'rm -rf ctx && mkdir ctx && tar -x -C ctx'
aws ecr get-login-password --region $REGION | b "docker login --username AWS --password-stdin ${REPO%%/*} >/dev/null 2>&1"
b "cd ctx && docker build --provenance=false -t $REPO:$TAG . > ../build.log 2>&1" || { b "tail -20 build.log"; exit 1; }

echo "--- 4. no-internet check"
b sh -s -- "$REPO:$TAG" <<'EOF'
set -e
docker rm -f lvoff >/dev/null 2>&1 || true
docker run -d --name lvoff --network none "$1" >/dev/null
get() { docker exec lvoff python -c "import sys,urllib.request as u;print(u.urlopen('http://127.0.0.1:8080'+sys.argv[1],data=sys.argv[2].encode() if len(sys.argv)>2 else None,timeout=60).read().decode())" "$@"; }
if docker exec lvoff python -c "import socket;socket.create_connection(('1.1.1.1',443),3)" 2>/dev/null; then
  echo "The test container could reach the internet: the check would prove nothing."; exit 1; fi
for i in $(seq 1 90); do get /readyz 2>/dev/null | grep -q true && break; sleep 2; done
match=$(get /check sample=match); problem=$(get /check sample=problem)
docker rm -f lvoff >/dev/null
echo "$match" | grep -q "Matches" && ! echo "$match" | grep -q "Does not match\|Please check" \
  || { echo "With no internet, the matching sample did not come back Matches."; exit 1; }
echo "$problem" | grep -q "Does not match\|Please check" \
  || { echo "With no internet, the sample with a problem was not flagged."; exit 1; }
echo "No internet: matching sample Matches, problem sample flagged."
EOF

echo "--- 5. switch the live site"
b "docker push $REPO:$TAG 2>&1 | tail -1; docker image prune -af >/dev/null 2>&1; docker builder prune -af >/dev/null 2>&1; true"
echo "live was: $(aws lambda get-function --region $REGION --function-name $FN --query Code.ImageUri --output text)"
aws lambda update-function-code --region $REGION --function-name $FN --image-uri $REPO:$TAG >/dev/null
aws lambda wait function-updated --region $REGION --function-name $FN
for i in $(seq 1 40); do curl -s $URL/readyz | grep -q true && break; sleep 3; done
echo "live now: $(aws lambda get-function --region $REGION --function-name $FN --query Code.ImageUri --output text)"
curl -s -X POST -F sample=match $URL/check | grep -q "Matches" && echo "live: matching sample Matches" \
  || { echo "LIVE CHECK FAILED: roll back with aws lambda update-function-code --image-uri <the 'live was' image>"; exit 1; }
